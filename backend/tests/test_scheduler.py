from backend.solver.scheduler import solve_schedule


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


def test_higher_priority_request_wins_conflict():

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

    result = solve_schedule(
        visibility_data,
        mission_data
    )

    scheduled_ids = {
        contact["request_id"]
        for contact in result["scheduled_contacts"]
    }

    assert "REQ_A" in scheduled_ids
    assert "REQ_B" not in scheduled_ids # test 1: priority conflict, assert means must be true else test fails

def test_reversing_priority_changes_winner():

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
            "priority": 10,
            "eligible_station_ids": ["GS_1"],
            "mandatory": False
        }
    ])

    result = solve_schedule(
        visibility_data,
        mission_data
    )

    scheduled_ids = {
        contact["request_id"]
        for contact in result["scheduled_contacts"]
    }

    assert "REQ_B" in scheduled_ids
    assert "REQ_A" not in scheduled_ids # reverse priority  


def test_non_overlapping_requests_are_both_scheduled():

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
            "aos": "2026-08-15T10:20:00Z",
            "los": "2026-08-15T10:35:00Z",
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

    result = solve_schedule(
        visibility_data,
        mission_data
    )

    scheduled_ids = {
        contact["request_id"]
        for contact in result["scheduled_contacts"]
    }

    assert scheduled_ids == {
        "REQ_A",
        "REQ_B"
    } # no conflict 



def test_request_uses_alternative_station():

    visibility_data = make_visibility_data([
        {
            "window_id": "VW_A_GS1",
            "satellite_id": "SAT_A",
            "station_id": "GS_1",
            "aos": "2026-08-15T10:00:00Z",
            "los": "2026-08-15T10:15:00Z",
            "duration_seconds": 900,
            "max_elevation_deg": 40.0
        },
        {
            "window_id": "VW_B_GS1",
            "satellite_id": "SAT_B",
            "station_id": "GS_1",
            "aos": "2026-08-15T10:00:00Z",
            "los": "2026-08-15T10:15:00Z",
            "duration_seconds": 900,
            "max_elevation_deg": 40.0
        },
        {
            "window_id": "VW_B_GS2",
            "satellite_id": "SAT_B",
            "station_id": "GS_2",
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
            "eligible_station_ids": [
                "GS_1",
                "GS_2"
            ],
            "mandatory": False
        }
    ])

    result = solve_schedule(
        visibility_data,
        mission_data
    )

    contacts = {
        contact["request_id"]: contact
        for contact in result["scheduled_contacts"]
    }

    assert "REQ_A" in contacts
    assert "REQ_B" in contacts

    assert contacts["REQ_B"]["station_id"] == "GS_2" # alt station 

    