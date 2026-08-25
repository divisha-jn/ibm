"""
backend/data/demo_scenarios.py

Canonical demo scenarios — reusable synthetic (visibility_data, mission_data)
pairs that reproduce specific, already-unit-tested solver behaviors.

Single source of truth for both the pytest fixture that verifies this
behavior (backend/tests/test_data_pipeline.py imports antenna_conflict_scenario()
from here) and the live-API seed script below, so they can't drift apart.

Usage:
    python -m backend.data.demo_scenarios   # seed the antenna-conflict demo
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MISSION_REQUESTS_PATH = REPO_ROOT / "data" / "mission_requests.json"
VISIBILITY_CACHE_PATH = (
    REPO_ROOT / "backend" / "data" / "generated" / "visibility_windows_scheduler.json"
)


def antenna_conflict_scenario() -> tuple[dict, dict]:
    """
    Two requests contend for the same ground station at the same time; only
    the higher-priority one can be scheduled.

    Verified by backend/tests/test_data_pipeline.py::
    test_schedule_enriches_station_conflict_from_same_p2_inputs — expects:
        REQ_HIGH_PRIORITY (priority 9) -> scheduled
        REQ_LOW_PRIORITY  (priority 5) -> unscheduled,
            reason_codes == ["ANTENNA_RESOURCE_CONFLICT"]

    Returns (visibility_data, mission_data) — contract #3 / #4 envelopes,
    ready to feed straight to solve_schedule()/build_conflict_evidence(), or
    to seed the live API via seed_antenna_conflict_scenario() below.
    """
    visibility_data = {
        "planning_horizon": {
            "start": "2026-08-24T00:00:00Z",
            "end": "2026-08-25T00:00:00Z",
        },
        "minimum_elevation_deg": 10.0,
        "visibility_windows": [
            {
                "window_id": "VW_HIGH_PRIORITY",
                "satellite_id": "NORAD_25544",  # ISS (ZARYA)
                "station_id": "GS_SG_01",
                "aos": "2026-08-24T10:00:00Z",
                "los": "2026-08-24T10:15:00Z",
                "duration_seconds": 900,
                "max_elevation_deg": 40.0,
            },
            {
                "window_id": "VW_LOW_PRIORITY",
                "satellite_id": "NORAD_48274",  # NOAA-20
                "station_id": "GS_SG_01",
                "aos": "2026-08-24T10:00:00Z",
                "los": "2026-08-24T10:15:00Z",
                "duration_seconds": 900,
                "max_elevation_deg": 35.0,
            },
        ],
    }
    mission_data = {
        "scenario_id": "LIVE_CONFLICT_ENRICHMENT",
        "requests": [
            {
                "request_id": "REQ_HIGH_PRIORITY",
                "satellite_id": "NORAD_25544",
                "required_contact_seconds": 900,
                "priority": 9,
                "eligible_station_ids": ["GS_SG_01"],
                "mandatory": False,
            },
            {
                "request_id": "REQ_LOW_PRIORITY",
                "satellite_id": "NORAD_48274",
                "required_contact_seconds": 900,
                "priority": 5,
                "eligible_station_ids": ["GS_SG_01"],
                "mandatory": False,
            },
        ],
    }
    return visibility_data, mission_data


def seed_antenna_conflict_scenario() -> None:
    """
    Overwrite the live app's scenario + visibility cache with
    antenna_conflict_scenario(), so GET /schedule reproduces it
    deterministically without touching real CelesTrak/Skyfield.

    Overwrites data/mission_requests.json (git-tracked — restore the default
    demo scenario with `git checkout -- data/mission_requests.json`) and
    backend/data/generated/visibility_windows_scheduler.json (gitignored,
    regenerated automatically from real orbital data otherwise).

    The visibility cache has a 6-hour TTL (data_pipeline.VISIBILITY_CACHE_TTL_SECONDS)
    — re-run this script if it's been longer than that since you last seeded.
    """
    visibility_data, mission_data = antenna_conflict_scenario()

    MISSION_REQUESTS_PATH.write_text(
        json.dumps(mission_data, indent=2), encoding="utf-8"
    )

    VISIBILITY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    VISIBILITY_CACHE_PATH.write_text(
        json.dumps(visibility_data, indent=2), encoding="utf-8"
    )

    print(f"Seeded {MISSION_REQUESTS_PATH}")
    print(f"Seeded {VISIBILITY_CACHE_PATH}")
    print()
    print("GET /api/v1/schedule should now return:")
    print("  REQ_HIGH_PRIORITY -> scheduled_contacts")
    print("  REQ_LOW_PRIORITY  -> unscheduled_requests,")
    print("                       reason_codes: ['ANTENNA_RESOURCE_CONFLICT']")
    print()
    print("Requires ortools (Python <=3.12) — otherwise /schedule serves the")
    print("hardcoded stub regardless of this seed.")
    print()
    print("Restore the default demo scenario with:")
    print("  git checkout -- data/mission_requests.json")


if __name__ == "__main__":
    seed_antenna_conflict_scenario()
