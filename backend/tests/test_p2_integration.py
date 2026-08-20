import json
from pathlib import Path

from backend.solver.conflicts import build_conflict_evidence
from backend.solver.scheduler import solve_schedule


FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(filename):
    with open(FIXTURES / filename, "r", encoding="utf-8") as file:
        return json.load(file)


def realistic_inputs(request_ids):
    visibility_data = load_fixture("visibility_windows_p2_realistic.json")
    mission_data = load_fixture("mission_requests_p2_realistic.json")

    requests = [
        request
        for request in mission_data["requests"]
        if request["request_id"] in request_ids
    ]
    satellite_ids = {request["satellite_id"] for request in requests}

    mission_data["requests"] = requests
    visibility_data["visibility_windows"] = [
        window
        for window in visibility_data["visibility_windows"]
        if window["satellite_id"] in satellite_ids
    ]
    return visibility_data, mission_data


def test_realistic_eligible_request_is_scheduled_inside_visibility_window():
    visibility_data, mission_data = realistic_inputs({"REQ_ISS_DOWNLINK"})

    result = solve_schedule(visibility_data, mission_data)

    assert result["unscheduled_requests"] == []
    assert result["scheduled_contacts"] == [
        {
            "request_id": "REQ_ISS_DOWNLINK",
            "satellite_id": "NORAD_25544",
            "station_id": "GS-SG",
            "window_id": "VW_NORAD_25544_GS-SG_20260820T101200Z",
            "scheduled_start": "2026-08-20T10:12:00Z",
            "scheduled_end": "2026-08-20T10:22:00Z",
            "duration_seconds": 600,
            "priority": 9,
        }
    ]


def test_realistic_request_longer_than_window_is_unscheduled():
    visibility_data, mission_data = realistic_inputs({"REQ_AQUA_DOWNLINK"})

    result = solve_schedule(visibility_data, mission_data)

    assert result["scheduled_contacts"] == []
    assert [
        request["request_id"] for request in result["unscheduled_requests"]
    ] == ["REQ_AQUA_DOWNLINK"]


def test_realistic_overlapping_contacts_share_one_station_resource():
    visibility_data, mission_data = realistic_inputs(
        {"REQ_ISS_DOWNLINK", "REQ_HST_DOWNLINK"}
    )

    result = solve_schedule(visibility_data, mission_data)

    assert len(result["scheduled_contacts"]) == 1
    assert len(result["unscheduled_requests"]) == 1


def test_realistic_station_conflict_prefers_higher_priority_request():
    visibility_data, mission_data = realistic_inputs(
        {"REQ_ISS_DOWNLINK", "REQ_HST_DOWNLINK"}
    )

    result = solve_schedule(visibility_data, mission_data)

    assert {
        contact["request_id"] for contact in result["scheduled_contacts"]
    } == {"REQ_ISS_DOWNLINK"}
    assert {
        request["request_id"] for request in result["unscheduled_requests"]
    } == {"REQ_HST_DOWNLINK"}


def test_realistic_conflict_evidence_identifies_station_and_winner():
    visibility_data, mission_data = realistic_inputs(
        {"REQ_ISS_DOWNLINK", "REQ_HST_DOWNLINK"}
    )
    schedule_result = solve_schedule(visibility_data, mission_data)

    evidence = build_conflict_evidence(
        visibility_data,
        mission_data,
        schedule_result,
    )

    assert evidence["scenario_id"] == "P2_REALISTIC_INTEGRATION_001"
    assert len(evidence["evidence"]) == 1
    record = evidence["evidence"][0]
    assert record["request_id"] == "REQ_HST_DOWNLINK"
    assert record["reason_codes"] == ["ANTENNA_RESOURCE_CONFLICT"]
    assert record["conflicts"] == [
        {
            "conflicting_request_id": "REQ_ISS_DOWNLINK",
            "station_id": "GS-SG",
            "overlap_start": "2026-08-20T10:12:00Z",
            "overlap_end": "2026-08-20T10:22:00Z",
            "overlap_seconds": 600,
            "request_priority": 5,
            "conflicting_request_priority": 9,
        }
    ]
