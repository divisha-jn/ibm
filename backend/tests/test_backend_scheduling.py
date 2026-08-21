import json
from copy import deepcopy
from pathlib import Path

from backend.api.scheduling import run_scheduling


FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(filename):
    with open(FIXTURES / filename, "r", encoding="utf-8") as file:
        return json.load(file)


def test_backend_uses_p2_and_priority_change_changes_conflict_winner():
    visibility_data = load_fixture("visibility_windows_p2_realistic.json")
    mission_data = load_fixture("mission_requests_p2_realistic.json")
    mission_data["requests"] = mission_data["requests"][:2]

    baseline = run_scheduling(visibility_data, mission_data)

    changed_missions = deepcopy(mission_data)
    changed_missions["requests"][1]["priority"] = 10
    changed = run_scheduling(visibility_data, changed_missions)

    assert baseline.schedule_result["solver"]["status"] == "OPTIMAL"
    assert changed.schedule_result["solver"]["status"] == "OPTIMAL"
    assert {
        contact["request_id"]
        for contact in baseline.schedule_result["scheduled_contacts"]
    } == {"REQ_ISS_DOWNLINK"}
    assert {
        contact["request_id"]
        for contact in changed.schedule_result["scheduled_contacts"]
    } == {"REQ_HST_DOWNLINK"}

    assert baseline.conflict_evidence["evidence"][0]["request_id"] == (
        "REQ_HST_DOWNLINK"
    )
    assert changed.conflict_evidence["evidence"][0]["request_id"] == (
        "REQ_ISS_DOWNLINK"
    )
    assert changed.conflict_evidence["evidence"][0]["reason_codes"] == [
        "ANTENNA_RESOURCE_CONFLICT"
    ]
