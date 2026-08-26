import json
from pathlib import Path
from unittest.mock import MagicMock

from backend.api.explanations import explain_request_conflict
from backend.api.scheduling import run_scheduling


FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(filename):
    with open(FIXTURES / filename, "r", encoding="utf-8") as file:
        return json.load(file)


def test_real_p2_conflict_evidence_flows_through_p4_to_p3():
    visibility_data = load_fixture("visibility_windows_p2_realistic.json")
    mission_data = load_fixture("mission_requests_p2_realistic.json")
    mission_data["requests"] = mission_data["requests"][:2]
    scheduling_run = run_scheduling(visibility_data, mission_data)

    p2_evidence = scheduling_run.conflict_evidence
    client = MagicMock()
    client.chat.return_value = "REQ_HST_DOWNLINK lost the GS-SG conflict."

    explanation = explain_request_conflict(
        p2_evidence,
        "REQ_HST_DOWNLINK",
        client=client,
    )

    assert explanation == "REQ_HST_DOWNLINK lost the GS-SG conflict."
    client.chat.assert_called_once()
    messages = client.chat.call_args.args[0]
    user_content = messages[1]["content"]
    supplied_evidence = json.loads(
        user_content[user_content.index("{"):]
    )
    assert supplied_evidence == {
        "scenario_id": "P2_REALISTIC_INTEGRATION_001",
        "evidence": [p2_evidence["evidence"][0]],
    }
    record = supplied_evidence["evidence"][0]
    assert record["request_id"] == "REQ_HST_DOWNLINK"
    assert record["reason_codes"] == ["ANTENNA_RESOURCE_CONFLICT"]
    assert record["conflicts"][0]["conflicting_request_id"] == (
        "REQ_ISS_DOWNLINK"
    )
