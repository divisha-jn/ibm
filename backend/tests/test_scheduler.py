from backend.solver.scheduler import solve_schedule
import pytest


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


def _constrained_inputs():
    visibility_data = make_visibility_data([
        {
            "window_id": "VW_TARGET_EARLY",
            "satellite_id": "NORAD_10001",
            "station_id": "GS_1",
            "aos": "2026-08-15T10:00:00Z",
            "los": "2026-08-15T10:15:00Z",
            "duration_seconds": 900,
            "max_elevation_deg": 40.0,
        },
        {
            "window_id": "VW_TARGET_LATE",
            "satellite_id": "NORAD_10001",
            "station_id": "GS_2",
            "aos": "2026-08-15T11:00:00Z",
            "los": "2026-08-15T11:15:00Z",
            "duration_seconds": 900,
            "max_elevation_deg": 45.0,
        },
        {
            "window_id": "VW_PROTECTED_CONFLICT",
            "satellite_id": "NORAD_10002",
            "station_id": "GS_2",
            "aos": "2026-08-15T11:00:00Z",
            "los": "2026-08-15T11:15:00Z",
            "duration_seconds": 900,
            "max_elevation_deg": 38.0,
        },
        {
            "window_id": "VW_PROTECTED_BACKUP",
            "satellite_id": "NORAD_10002",
            "station_id": "GS_1",
            "aos": "2026-08-15T12:00:00Z",
            "los": "2026-08-15T12:15:00Z",
            "duration_seconds": 900,
            "max_elevation_deg": 42.0,
        },
    ])
    mission_data = make_mission_data([
        {
            "request_id": "REQ_TARGET",
            "satellite_id": "NORAD_10001",
            "required_contact_seconds": 900,
            "priority": 5,
            "eligible_station_ids": ["GS_1", "GS_2"],
            "mandatory": False,
        },
        {
            "request_id": "REQ_PROTECTED",
            "satellite_id": "NORAD_10002",
            "required_contact_seconds": 900,
            "priority": 9,
            "eligible_station_ids": ["GS_1", "GS_2"],
            "mandatory": False,
        },
    ])
    return visibility_data, mission_data


def test_existing_two_argument_solver_call_remains_supported():
    visibility_data, mission_data = _constrained_inputs()

    result = solve_schedule(visibility_data, mission_data)

    assert result["solver"]["status"] in {"OPTIMAL", "FEASIBLE"}
    assert {contact["request_id"] for contact in result["scheduled_contacts"]} == {
        "REQ_TARGET",
        "REQ_PROTECTED",
    }


def test_required_window_forces_exact_target_window():
    visibility_data, mission_data = _constrained_inputs()

    result = solve_schedule(
        visibility_data,
        mission_data,
        required_window_by_request={"REQ_TARGET": "VW_TARGET_LATE"},
        deterministic=True,
    )

    target = next(
        contact
        for contact in result["scheduled_contacts"]
        if contact["request_id"] == "REQ_TARGET"
    )
    assert target["window_id"] == "VW_TARGET_LATE"
    assert target["station_id"] == "GS_2"


def test_required_request_remains_scheduled_during_forced_validation():
    visibility_data, mission_data = _constrained_inputs()

    result = solve_schedule(
        visibility_data,
        mission_data,
        required_request_ids={"REQ_PROTECTED"},
        required_window_by_request={"REQ_TARGET": "VW_TARGET_LATE"},
        deterministic=True,
    )

    contacts = {
        contact["request_id"]: contact
        for contact in result["scheduled_contacts"]
    }
    assert set(contacts) == {"REQ_TARGET", "REQ_PROTECTED"}
    assert contacts["REQ_PROTECTED"]["window_id"] == "VW_PROTECTED_BACKUP"


@pytest.mark.parametrize(
    ("required_request_ids", "required_window_by_request", "message"),
    [
        ({"REQ_UNKNOWN"}, None, "do not exist"),
        (None, {"REQ_TARGET": "VW_UNKNOWN"}, "does not exist"),
    ],
)
def test_invalid_required_request_or_window_fails_explicitly(
    required_request_ids,
    required_window_by_request,
    message,
):
    visibility_data, mission_data = _constrained_inputs()

    with pytest.raises(ValueError, match=message):
        solve_schedule(
            visibility_data,
            mission_data,
            required_request_ids=required_request_ids,
            required_window_by_request=required_window_by_request,
        )


def test_ineligible_required_window_fails_explicitly():
    visibility_data, mission_data = _constrained_inputs()
    mission_data["requests"][0]["eligible_station_ids"] = ["GS_1"]

    with pytest.raises(ValueError, match="ineligible station"):
        solve_schedule(
            visibility_data,
            mission_data,
            required_window_by_request={"REQ_TARGET": "VW_TARGET_LATE"},
        )


def test_too_short_required_window_fails_explicitly():
    visibility_data, mission_data = _constrained_inputs()
    mission_data["requests"][0]["required_contact_seconds"] = 901

    with pytest.raises(ValueError, match="too short"):
        solve_schedule(
            visibility_data,
            mission_data,
            required_window_by_request={"REQ_TARGET": "VW_TARGET_LATE"},
        )


def test_deterministic_constrained_solve_is_repeatable():
    visibility_data, mission_data = _constrained_inputs()
    kwargs = {
        "required_request_ids": {"REQ_PROTECTED"},
        "required_window_by_request": {"REQ_TARGET": "VW_TARGET_LATE"},
        "deterministic": True,
    }

    first = solve_schedule(visibility_data, mission_data, **kwargs)
    second = solve_schedule(visibility_data, mission_data, **kwargs)

    assert first == second
