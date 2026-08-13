from backend.solver.scheduler import solve_schedule
from backend.solver.conflicts import build_conflict_evidence


def make_visibility_data(windows):
    return {
        "planning_horizon": {
            "start": "2026-08-15T00:00:00Z",
            "end": "2026-08-16T00:00:00Z"
        },
        "minimum_elevation_deg": 10.0,
        "visibility_windows": windows
    }


def make_mission_data(requests):
    return {
        "scenario_id": "TEST_SCENARIO",
        "requests": requests
    }


def test_antenna_resource_conflict():

    visibility_data = make_visibility_data([
        {
            "window_id": "VW_A",
            "satellite_id": "SAT_A",
            "station_id": "GS_1",
            "aos": "2026-08-15T10:00:00Z",
            "los": "2026-08-15T10:15:00Z",
            "duration_seconds": 900,
            "max_elevation_deg": 40.0
        },
        {
            "window_id": "VW_B",
            "satellite_id": "SAT_B",
            "station_id": "GS_1",
            "aos": "2026-08-15T10:00:00Z",
            "los": "2026-08-15T10:15:00Z",
            "duration_seconds": 900,
            "max_elevation_deg": 40.0
        }
    ])

    mission_data = make_mission_data([
        {
            "request_id": "REQ_A",
            "satellite_id": "SAT_A",
            "required_contact_seconds": 900,
            "priority": 9,
            "eligible_station_ids": ["GS_1"],
            "mandatory": False
        },
        {
            "request_id": "REQ_B",
            "satellite_id": "SAT_B",
            "required_contact_seconds": 900,
            "priority": 5,
            "eligible_station_ids": ["GS_1"],
            "mandatory": False
        }
    ])

    schedule_result = solve_schedule(
        visibility_data,
        mission_data
    )

    evidence = build_conflict_evidence(
        visibility_data,
        mission_data,
        schedule_result
    )

    record = evidence["evidence"][0]

    assert record["request_id"] == "REQ_B"

    assert (
        "ANTENNA_RESOURCE_CONFLICT"
        in record["reason_codes"]
    )

    assert len(record["conflicts"]) == 1

    assert (
        record["conflicts"][0]["conflicting_request_id"]
        == "REQ_A"
    )

    assert (
        record["conflicts"][0]["overlap_seconds"]
        == 900
    )


def test_insufficient_window_duration():

    visibility_data = make_visibility_data([
        {
            "window_id": "VW_A",
            "satellite_id": "SAT_A",
            "station_id": "GS_1",
            "aos": "2026-08-15T10:00:00Z",
            "los": "2026-08-15T10:10:00Z",
            "duration_seconds": 600,
            "max_elevation_deg": 40.0
        }
    ])

    mission_data = make_mission_data([
        {
            "request_id": "REQ_A",
            "satellite_id": "SAT_A",

            # Needs 15 minutes
            "required_contact_seconds": 900,

            "priority": 9,
            "eligible_station_ids": ["GS_1"],
            "mandatory": False
        }
    ])

    schedule_result = solve_schedule(
        visibility_data,
        mission_data
    )

    evidence = build_conflict_evidence(
        visibility_data,
        mission_data,
        schedule_result
    )

    record = evidence["evidence"][0]

    assert record["request_id"] == "REQ_A"

    assert (
        "INSUFFICIENT_WINDOW_DURATION"
        in record["reason_codes"]
    )

    assert record["conflicts"] == []



def test_no_eligible_visibility_window():

    visibility_data = make_visibility_data([
        {
            "window_id": "VW_A",
            "satellite_id": "SAT_A",

            # Pass exists at GS_2
            "station_id": "GS_2",

            "aos": "2026-08-15T10:00:00Z",
            "los": "2026-08-15T10:20:00Z",
            "duration_seconds": 1200,
            "max_elevation_deg": 40.0
        }
    ])

    mission_data = make_mission_data([
        {
            "request_id": "REQ_A",
            "satellite_id": "SAT_A",
            "required_contact_seconds": 900,
            "priority": 9,

            # But mission is only allowed GS_1
            "eligible_station_ids": ["GS_1"],

            "mandatory": False
        }
    ])

    schedule_result = solve_schedule(
        visibility_data,
        mission_data
    )

    evidence = build_conflict_evidence(
        visibility_data,
        mission_data,
        schedule_result
    )

    record = evidence["evidence"][0]

    assert record["request_id"] == "REQ_A"

    assert (
        "NO_ELIGIBLE_VISIBILITY_WINDOW"
        in record["reason_codes"]
    )

    assert record["conflicts"] == []