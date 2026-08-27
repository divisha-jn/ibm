"""
backend/data/demo_scenarios.py

Canonical demo scenarios — reusable synthetic (visibility_data, mission_data)
pairs that reproduce specific, already-unit-tested solver behaviors.

Single source of truth for both the pytest fixtures that verify this
behavior and the live-API seed script below, so they can't drift apart:
  - antenna_conflict_scenario()      <- backend/tests/test_data_pipeline.py
  - ranked_alternatives_scenario()   <- backend/tests/test_alternatives.py

Usage:
    python -m backend.data.demo_scenarios                     # antenna_conflict (default)
    python -m backend.data.demo_scenarios ranked_alternatives
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MISSION_REQUESTS_PATH = REPO_ROOT / "data" / "mission_requests.json"
VISIBILITY_CACHE_PATH = (
    REPO_ROOT / "backend" / "data" / "generated" / "visibility_windows_scheduler.json"
)


def antenna_conflict_scenario() -> tuple[dict, dict]:
    """
    Two requests contend for the same ground station at the same time; only
    the higher-priority one can be scheduled. No alternative window exists
    for the loser (rank_alternatives() returns NO_FEASIBLE_ALTERNATIVES).

    Verified by backend/tests/test_data_pipeline.py::
    test_schedule_enriches_station_conflict_from_same_p2_inputs — expects:
        REQ_HIGH_PRIORITY (priority 9) -> scheduled
        REQ_LOW_PRIORITY  (priority 5) -> unscheduled,
            reason_codes == ["ANTENNA_RESOURCE_CONFLICT"]

    Returns (visibility_data, mission_data) — contract #3 / #4 envelopes,
    ready to feed straight to solve_schedule()/build_conflict_evidence(), or
    to seed the live API via seed_scenario("antenna_conflict") below.
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


def ranked_alternatives_scenario() -> tuple[dict, dict]:
    """
    A high-priority request (REQ_ALT_TARGET) needs a full 20-minute pass,
    but a lower-priority pair (REQ_LOWER_A, REQ_LOWER_B) already splits
    that same station-time slot into two 10-minute contacts whose combined
    priority (4+4=8) outweighs the target's (6) — so the solver schedules
    both lower-priority requests instead and leaves the target unscheduled.
    Unlike antenna_conflict_scenario(), the target DOES have one other
    viable window (the full slot) — ranking its alternatives finds it, at
    the cost of displacing both lower-priority holders.

    Verified by backend/tests/test_alternatives.py::
    test_real_p2_schedule_evidence_and_alternatives_integration — expects:
        REQ_LOWER_A, REQ_LOWER_B (priority 4 each) -> scheduled
        REQ_ALT_TARGET           (priority 6)      -> unscheduled,
            reason_codes == ["ANTENNA_RESOURCE_CONFLICT"]
        rank_alternatives(..., "REQ_ALT_TARGET") ->
            status: ALTERNATIVES_FOUND
            alternatives[0].window_id: "VW_TARGET_LONG"
            alternatives[0].displaced_request_ids: ["REQ_LOWER_A", "REQ_LOWER_B"]

    Returns (visibility_data, mission_data) — contract #3 / #4 envelopes.
    """
    visibility_data = {
        "planning_horizon": {
            "start": "2026-08-24T00:00:00Z",
            "end": "2026-08-25T00:00:00Z",
        },
        "minimum_elevation_deg": 10.0,
        "visibility_windows": [
            {
                "window_id": "VW_TARGET_LONG",
                "satellite_id": "NORAD_20002",
                "station_id": "GS_1",
                "aos": "2026-08-24T10:00:00Z",
                "los": "2026-08-24T10:20:00Z",
                "duration_seconds": 1200,
                "max_elevation_deg": 40.0,
            },
            {
                "window_id": "VW_LOWER_A",
                "satellite_id": "NORAD_20005",
                "station_id": "GS_1",
                "aos": "2026-08-24T10:00:00Z",
                "los": "2026-08-24T10:10:00Z",
                "duration_seconds": 600,
                "max_elevation_deg": 40.0,
            },
            {
                "window_id": "VW_LOWER_B",
                "satellite_id": "NORAD_20006",
                "station_id": "GS_1",
                "aos": "2026-08-24T10:10:00Z",
                "los": "2026-08-24T10:20:00Z",
                "duration_seconds": 600,
                "max_elevation_deg": 40.0,
            },
        ],
    }
    mission_data = {
        "scenario_id": "P2_ALTERNATIVES_TEST",
        "requests": [
            {
                "request_id": "REQ_ALT_TARGET",
                "satellite_id": "NORAD_20002",
                "required_contact_seconds": 1200,
                "priority": 6,
                "eligible_station_ids": ["GS_1"],
                "mandatory": False,
            },
            {
                "request_id": "REQ_LOWER_A",
                "satellite_id": "NORAD_20005",
                "required_contact_seconds": 600,
                "priority": 4,
                "eligible_station_ids": ["GS_1"],
                "mandatory": False,
            },
            {
                "request_id": "REQ_LOWER_B",
                "satellite_id": "NORAD_20006",
                "required_contact_seconds": 600,
                "priority": 4,
                "eligible_station_ids": ["GS_1"],
                "mandatory": False,
            },
        ],
    }
    return visibility_data, mission_data


_SCENARIOS = {
    "antenna_conflict": antenna_conflict_scenario,
    "ranked_alternatives": ranked_alternatives_scenario,
}

_EXPECTED_RESULTS = {
    "antenna_conflict": """GET /api/v1/schedule:
  REQ_HIGH_PRIORITY -> scheduled_contacts
  REQ_LOW_PRIORITY  -> unscheduled_requests, reason_codes: ['ANTENNA_RESOURCE_CONFLICT']

POST /api/v1/alternatives {"scenario_id": "LIVE_CONFLICT_ENRICHMENT", "request_id": "REQ_LOW_PRIORITY"}:
  status: 'NO_FEASIBLE_ALTERNATIVES'  (no other window exists for this request)""",
    "ranked_alternatives": """GET /api/v1/schedule:
  REQ_LOWER_A, REQ_LOWER_B -> scheduled_contacts
  REQ_ALT_TARGET           -> unscheduled_requests, reason_codes: ['ANTENNA_RESOURCE_CONFLICT']

POST /api/v1/alternatives {"scenario_id": "P2_ALTERNATIVES_TEST", "request_id": "REQ_ALT_TARGET"}:
  status: 'ALTERNATIVES_FOUND'
  alternatives[0].window_id: 'VW_TARGET_LONG'
  alternatives[0].displaced_request_ids: ['REQ_LOWER_A', 'REQ_LOWER_B']""",
}


def seed_scenario(name: str) -> None:
    """
    Overwrite the live app's scenario + visibility cache with the named
    scenario, so GET /schedule and POST /alternatives reproduce it
    deterministically without touching real CelesTrak/Skyfield.

    Overwrites data/mission_requests.json (git-tracked — restore the default
    demo scenario with `git checkout -- data/mission_requests.json`) and
    backend/data/generated/visibility_windows_scheduler.json (gitignored,
    regenerated automatically from real orbital data otherwise).

    The visibility cache has a 6-hour TTL (data_pipeline.VISIBILITY_CACHE_TTL_SECONDS)
    — re-run this script if it's been longer than that since you last seeded.
    """
    try:
        generator = _SCENARIOS[name]
    except KeyError:
        raise SystemExit(
            f"Unknown scenario {name!r}. Choose one of: {', '.join(_SCENARIOS)}"
        )

    visibility_data, mission_data = generator()

    MISSION_REQUESTS_PATH.write_text(
        json.dumps(mission_data, indent=2), encoding="utf-8"
    )

    VISIBILITY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    VISIBILITY_CACHE_PATH.write_text(
        json.dumps(visibility_data, indent=2), encoding="utf-8"
    )

    print(f"Seeded {MISSION_REQUESTS_PATH}")
    print(f"Seeded {VISIBILITY_CACHE_PATH}")
    print(f"Scenario: {name}")
    print()
    print(_EXPECTED_RESULTS[name])
    print()
    print("Requires ortools (Python <=3.12) — otherwise /schedule and")
    print("/alternatives serve fallbacks regardless of this seed.")
    print()
    print("Restore the default demo scenario with:")
    print("  git checkout -- data/mission_requests.json")


def seed_antenna_conflict_scenario() -> None:
    """Back-compat alias for seed_scenario("antenna_conflict")."""
    seed_scenario("antenna_conflict")


if __name__ == "__main__":
    seed_scenario(sys.argv[1] if len(sys.argv) > 1 else "antenna_conflict")
