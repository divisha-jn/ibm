"""
backend/api/data_pipeline.py

Wires together the three pieces that produce a live baseline schedule and
conflict evidence:

    P1: generate_all_visibility_windows()  →  visibility_data dict  (contract #3)
    P2: solve_schedule()                   →  schedule_result dict  (contract #5)
    P2: build_conflict_evidence()          →  evidence dict          (contract #6)
    P4: build_live_schedule()              →  called from GET /schedule
    P4: build_live_conflict_evidence()     →  called from POST /explain
    P4: build_live_alternatives()          →  called from POST /alternatives
    P4: build_live_risk()                  →  called from POST /risk
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
MISSION_REQUESTS_PATH = REPO_ROOT / "data" / "mission_requests.json"
GENERATED_DIR = REPO_ROOT / "backend" / "data" / "generated"
# Keep P2's canonical cache separate from P1's frozen display/cache contract.
VISIBILITY_CACHE_PATH = GENERATED_DIR / "visibility_windows_scheduler.json"
VISIBILITY_HORIZON_HOURS = 48
SCHEDULER_WINDOW_FIELDS = frozenset(
    {
        "window_id",
        "satellite_id",
        "station_id",
        "aos",
        "los",
        "duration_seconds",
        "max_elevation_deg",
    }
)

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
    """True if the canonical scheduler cache exists and is younger than the TTL."""
    if not VISIBILITY_CACHE_PATH.exists():
        return False
    age = time.time() - VISIBILITY_CACHE_PATH.stat().st_mtime
    return age < VISIBILITY_CACHE_TTL_SECONDS


def _visibility_cache_is_compatible(envelope: object) -> bool:
    """Return whether a cache envelope has P2's current canonical structure."""
    if not isinstance(envelope, dict):
        return False

    planning_horizon = envelope.get("planning_horizon")
    windows = envelope.get("visibility_windows")
    if (
        not isinstance(planning_horizon, dict)
        or set(planning_horizon) != {"start", "end"}
        or not isinstance(planning_horizon["start"], str)
        or not isinstance(planning_horizon["end"], str)
        or not isinstance(envelope.get("minimum_elevation_deg"), (int, float))
        or not isinstance(windows, list)
        or not windows
    ):
        return False

    return all(
        isinstance(window, dict)
        and set(window) == SCHEDULER_WINDOW_FIELDS
        and isinstance(window["window_id"], str)
        and bool(window["window_id"])
        and isinstance(window["satellite_id"], str)
        and window["satellite_id"].startswith("NORAD_")
        and isinstance(window["station_id"], str)
        and bool(window["station_id"])
        and isinstance(window["aos"], str)
        and isinstance(window["los"], str)
        and isinstance(window["duration_seconds"], int)
        and isinstance(window["max_elevation_deg"], (int, float))
        for window in windows
    )


def _save_visibility_cache(envelope: dict) -> None:
    """Atomically persist canonical visibility data for P2."""
    VISIBILITY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = VISIBILITY_CACHE_PATH.with_suffix(
        VISIBILITY_CACHE_PATH.suffix + ".tmp"
    )
    with open(temporary_path, "w", encoding="utf-8") as f:
        json.dump(envelope, f, indent=2)
    temporary_path.replace(VISIBILITY_CACHE_PATH)


def _get_visibility_data() -> dict:
    """
    Return canonical solver-ready visibility data, regenerating when needed.

    TTL behaviour:
      fresh compatible cache → load from disk immediately
      stale / incompatible   → generate P1 objects, adapt, cache, then return
    """
    from backend.api.visibility_adapter import adapt_visibility_for_scheduler
    from backend.data.ground_stations import load_ground_stations
    from backend.data.passes import generate_all_visibility_windows

    if _cache_is_fresh():
        try:
            with open(VISIBILITY_CACHE_PATH, encoding="utf-8") as f:
                envelope = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read visibility cache (%s) — regenerating.", exc)
        else:
            if _visibility_cache_is_compatible(envelope):
                logger.info(
                    "Loaded %d canonical visibility windows from cache (age < %dh).",
                    len(envelope["visibility_windows"]),
                    VISIBILITY_CACHE_TTL_SECONDS // 3600,
                )
                return envelope
            logger.info(
                "Visibility cache is incompatible with the current scheduler "
                "contract — regenerating."
            )
    else:
        if VISIBILITY_CACHE_PATH.exists():
            logger.info("Visibility window cache is stale — regenerating.")
        else:
            logger.info("No visibility window cache found — generating for the first time.")

    logger.info("Generating and adapting visibility windows from CelesTrak/Skyfield …")
    # P1 serializes AOS/LOS at whole-second precision; keep P2's horizon on
    # that same boundary so integer solver offsets reconstruct exact times.
    planning_start = datetime.now(timezone.utc).replace(microsecond=0)
    planning_end = planning_start + timedelta(hours=VISIBILITY_HORIZON_HOURS)
    windows = generate_all_visibility_windows(
        horizon_hours=VISIBILITY_HORIZON_HOURS
    )
    if not windows:
        raise RuntimeError("generate_all_visibility_windows() returned no windows.")

    stations = load_ground_stations()
    visibility_data = adapt_visibility_for_scheduler(
        windows,
        planning_start=planning_start,
        planning_end=planning_end,
        minimum_elevation_deg=min(
            station.min_elevation_deg for station in stations
        ),
    )
    _save_visibility_cache(visibility_data)

    return visibility_data


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


def _enrich_unscheduled_requests(
    schedule_result: dict,
    conflict_evidence: dict,
) -> dict:
    """
    Attach P2 reason codes and conflict detail to matching unscheduled
    schedule records, so /schedule's unscheduled_requests carry the same
    conflicts[] detail /explain's evidence does — P5 can render a rejection
    banner straight from /schedule without a follow-up /explain call per
    request. Raw conflict dicts pass through as-is; the ScheduleResult
    response_model (UnscheduledRequest.conflicts: List[ConflictRecord])
    filters them down to the contracted shape at serialization time.
    """
    evidence_by_request_id = {
        record["request_id"]: record
        for record in conflict_evidence.get("evidence", [])
    }

    for unscheduled in schedule_result.get("unscheduled_requests", []):
        request_id = unscheduled["request_id"]
        evidence = evidence_by_request_id.get(request_id)
        if evidence is None:
            raise ValueError(
                f"Conflict evidence missing for unscheduled request {request_id}."
            )

        reason_codes = evidence.get("reason_codes")
        if not isinstance(reason_codes, list) or not reason_codes:
            raise ValueError(
                f"Conflict evidence has no reason codes for {request_id}."
            )

        unscheduled["reason_codes"] = list(reason_codes)
        unscheduled["conflicts"] = evidence.get("conflicts", [])

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
        from backend.solver.conflicts import build_conflict_evidence
        from backend.solver.scheduler import solve_schedule
        mission_data = _load_mission_requests()
        visibility_data = _get_visibility_data()
        result = solve_schedule(
            visibility_data,
            mission_data,
            deterministic=True,
        )
        evidence = build_conflict_evidence(
            visibility_data,
            mission_data,
            result,
        )
        _enrich_unscheduled_requests(result, evidence)
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


def build_live_alternatives(
    schedule_result: dict,
    conflict_evidence: dict,
    request_id: str,
    *,
    visibility_data: Optional[dict] = None,
    mission_data: Optional[dict] = None,
    limit: int = 3,
) -> Optional[dict]:
    """
    Run P2's rank_alternatives() to find solver-validated alternative
    windows for one unscheduled request, ranked by operational disruption
    (real re-solves against candidate windows — not an LLM suggestion).

    Returns a contract #8 dict (contracts/alternatives.example.json), or
    None on any failure — unknown request_id, malformed inputs, and solver
    errors all collapse to None here, matching every other build_live_*
    function's fail-inward style. The caller serves a PIPELINE_UNAVAILABLE
    fallback.
    """
    if not _ortools_available():
        return None

    try:
        from backend.solver.alternatives import rank_alternatives
        if visibility_data is None:
            visibility_data = _get_visibility_data()
        if mission_data is None:
            mission_data = _load_mission_requests()
        return rank_alternatives(
            visibility_data,
            mission_data,
            schedule_result,
            conflict_evidence,
            request_id,
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("build_live_alternatives failed: %s", exc, exc_info=True)
        return None


def build_live_risk(
    schedule_result: dict,
    conflict_evidence: dict,
    request_id: str,
    *,
    visibility_data: Optional[dict] = None,
    mission_data: Optional[dict] = None,
    include_weather: bool = True,
) -> Optional[dict]:
    """
    Run P2's assess_operational_risk() for one request and return the result.

    Fetches space-weather from NASA DONKI when include_weather=True (default).
    Pass include_weather=False to skip the DONKI call and keep the response fast.

    Returns a risk assessment dict, or None on any failure.
    """
    if not _ortools_available():
        return None

    try:
        from backend.solver.risk import assess_operational_risk
        if visibility_data is None:
            visibility_data = _get_visibility_data()
        if mission_data is None:
            mission_data = _load_mission_requests()

        space_weather_events: list = []
        space_weather_status: dict | None = None

        if include_weather:
            try:
                from backend.data.space_weather import fetch_space_weather_events
                planning_horizon = visibility_data.get("planning_horizon", {})
                start_str = planning_horizon.get("start", "")[:10]
                end_str = planning_horizon.get("end", "")[:10]
                if start_str and end_str:
                    weather = fetch_space_weather_events(start_str, end_str)
                    space_weather_events = weather.get("events", [])
                    space_weather_status = {"FLR": weather["fetch_status"].get("FLR", "failed"),
                                            "GST": weather["fetch_status"].get("GST", "failed")}
            except Exception as exc:  # noqa: BLE001
                logger.warning("Space weather fetch failed (%s) — proceeding without it.", exc)

        # Build alternatives so the recovery factor is populated
        alternatives_result: dict | None = None
        try:
            from backend.solver.alternatives import rank_alternatives
            alternatives_result = rank_alternatives(
                visibility_data,
                mission_data,
                schedule_result,
                conflict_evidence,
                request_id,
                limit=3,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "rank_alternatives failed for %r during risk assessment (%s) — "
                "recovery factor will be UNKNOWN.",
                request_id, exc,
            )

        return assess_operational_risk(
            visibility_data,
            mission_data,
            schedule_result,
            conflict_evidence,
            request_id,
            space_weather_events=space_weather_events,
            space_weather_status=space_weather_status,
            alternatives_result=alternatives_result,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("build_live_risk failed for %r: %s", request_id, exc, exc_info=True)
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
        result = solve_schedule(
            visibility_data,
            modified_mission_data,
            deterministic=True,
        )
        return _backfill_contract_fields(result)
    except Exception as exc:  # noqa: BLE001
        logger.error("build_live_what_if_schedule failed: %s", exc, exc_info=True)
        return None
