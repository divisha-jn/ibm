"""
backend/api/data_pipeline.py

Wires together the three pieces that produce a live baseline schedule and
conflict evidence:

    P1: generate_all_visibility_windows()  →  visibility_data dict  (contract #3)
    P2: solve_schedule()                   →  schedule_result dict  (contract #5)
    P2: build_conflict_evidence()          →  evidence dict          (contract #6)
    P4: build_live_schedule()              →  called from GET /schedule
    P4: build_live_conflict_evidence()     →  called from POST /explain
    P4: build_live_what_if_schedule()      →  called from POST /what-if

Design goals
------------
* All P2 imports are lazy — the app starts on Python 3.13 even when ortools
  crashes at the C-extension level.
* _ortools_available() probes in a subprocess so a SIGABRT never kills us.
* Every public function returns None on failure; callers fall back to stubs.
* No scheduling or conflict logic lives here — only wiring and backfilling.

Backfill conventions (removed when P2 adds the fields natively)
---------------------------------------------------------------
antenna_id    → station_id + "_A1"   (first antenna of the station)
reason_codes  → ["UNSCHEDULED"]      (replaced by real codes from conflict engine)
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
MISSION_REQUESTS_PATH = REPO_ROOT / "data" / "mission_requests.json"
GENERATED_DIR = REPO_ROOT / "backend" / "data" / "generated"
VISIBILITY_CACHE_PATH = GENERATED_DIR / "visibility_windows.json"

# 6-hour TTL — matches CelesTrak GP element cache in celestrak.py.
# Visibility windows are derived from those elements, so there is no
# point holding them longer.
VISIBILITY_CACHE_TTL_SECONDS = 6 * 60 * 60


# ---------------------------------------------------------------------------
# Helpers shared across all public entry points
# ---------------------------------------------------------------------------

def _ortools_available() -> bool:
    """
    Probe ortools in a subprocess so a SIGABRT on Python 3.13 never
    kills the parent FastAPI process.
    """
    probe = subprocess.run(
        [sys.executable, "-c", "from ortools.sat.python import cp_model"],
        capture_output=True,
    )
    return probe.returncode == 0


def _load_mission_requests() -> dict:
    """Load data/mission_requests.json.  Raises if missing or empty."""
    if not MISSION_REQUESTS_PATH.exists():
        raise FileNotFoundError(
            f"Mission requests file not found: {MISSION_REQUESTS_PATH}"
        )
    with open(MISSION_REQUESTS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    if not data or not data.get("requests"):
        raise ValueError("mission_requests.json is empty or has no requests.")
    return data


def _cache_is_fresh() -> bool:
    """True if visibility_windows.json exists and is younger than the TTL."""
    if not VISIBILITY_CACHE_PATH.exists():
        return False
    age = time.time() - VISIBILITY_CACHE_PATH.stat().st_mtime
    return age < VISIBILITY_CACHE_TTL_SECONDS


def _get_visibility_data() -> dict:
    """
    Return the contract #3 visibility envelope, regenerating when stale.

    TTL behaviour:
      fresh cache   → load from disk immediately
      stale / empty → generate_all_visibility_windows() + save, then return
    """
    from backend.data.passes import generate_all_visibility_windows, save_visibility_windows

    if _cache_is_fresh():
        with open(VISIBILITY_CACHE_PATH, encoding="utf-8") as f:
            envelope = json.load(f)
        if envelope.get("visibility_windows"):
            logger.info(
                "Loaded %d visibility windows from cache (age < %dh).",
                len(envelope["visibility_windows"]),
                VISIBILITY_CACHE_TTL_SECONDS // 3600,
            )
            return envelope
        logger.warning("Cached visibility_windows.json is empty — regenerating.")
    else:
        if VISIBILITY_CACHE_PATH.exists():
            logger.info("Visibility window cache is stale — regenerating.")
        else:
            logger.info("No visibility window cache found — generating for the first time.")

    logger.info("Generating visibility windows from CelesTrak/Skyfield …")
    windows = generate_all_visibility_windows()
    if not windows:
        raise RuntimeError("generate_all_visibility_windows() returned no windows.")

    now = datetime.now(timezone.utc)
    save_visibility_windows(windows, start=now)

    with open(VISIBILITY_CACHE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _backfill_contract_fields(schedule_result: dict) -> dict:
    """
    Fill contract #5 fields that P2 does not yet emit.
    Safe to call after P2 adds them — presence check skips the backfill.
    """
    for contact in schedule_result.get("scheduled_contacts", []):
        if "antenna_id" not in contact:
            contact["antenna_id"] = contact["station_id"] + "_A1"

    for req in schedule_result.get("unscheduled_requests", []):
        if "reason_codes" not in req:
            req["reason_codes"] = ["UNSCHEDULED"]

    return schedule_result


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def build_live_schedule() -> Optional[dict]:
    """
    Run the full P1 → P2 scheduling pipeline.

    Returns a contract #5 dict, or None when ortools is unavailable or
    any step fails (caller should serve the hardcoded stub instead).
    """
    if not _ortools_available():
        logger.warning(
            "ortools unavailable — GET /schedule will serve the hardcoded stub. "
            "Install ortools on Python ≤3.12 to enable the live pipeline."
        )
        return None

    try:
        from backend.solver.scheduler import solve_schedule
        mission_data = _load_mission_requests()
        visibility_data = _get_visibility_data()
        result = solve_schedule(visibility_data, mission_data)
        return _backfill_contract_fields(result)
    except Exception as exc:  # noqa: BLE001
        logger.error("build_live_schedule failed: %s", exc, exc_info=True)
        return None


def build_live_conflict_evidence(
    schedule_result: dict,
    visibility_data: Optional[dict] = None,
    mission_data: Optional[dict] = None,
) -> Optional[dict]:
    """
    Run P2's build_conflict_evidence() against an already-solved schedule.

    Arguments
    ---------
    schedule_result  Contract #5 dict (from build_live_schedule or what-if solver).
    visibility_data  Contract #3 envelope.  Loaded from cache if omitted.
    mission_data     Mission requests dict.  Loaded from disk if omitted.

    Returns a contract #6 evidence dict, or None on any failure.
    """
    if not _ortools_available():
        return None

    try:
        from backend.solver.conflicts import build_conflict_evidence
        if visibility_data is None:
            visibility_data = _get_visibility_data()
        if mission_data is None:
            mission_data = _load_mission_requests()
        return build_conflict_evidence(visibility_data, mission_data, schedule_result)
    except Exception as exc:  # noqa: BLE001
        logger.error("build_live_conflict_evidence failed: %s", exc, exc_info=True)
        return None


def build_live_what_if_schedule(
    modified_mission_data: dict,
) -> Optional[dict]:
    """
    Re-solve with a modified mission_data dict (from apply_operations_to_scenario).

    Shares the same visibility windows as the baseline schedule — only the
    mission parameters change between a base run and a what-if run.

    Returns a contract #5 dict, or None on failure.
    """
    if not _ortools_available():
        return None

    try:
        from backend.solver.scheduler import solve_schedule
        visibility_data = _get_visibility_data()
        result = solve_schedule(visibility_data, modified_mission_data)
        return _backfill_contract_fields(result)
    except Exception as exc:  # noqa: BLE001
        logger.error("build_live_what_if_schedule failed: %s", exc, exc_info=True)
        return None
