import copy
import json
import sys

from backend.ai import granite, intent_parser
from backend.api import data_pipeline, what_if
from backend.api.scenario import apply_operations_to_scenario
from backend.api.schemas import WhatIfRequest
from backend.solver.conflicts import build_conflict_evidence
from backend.solver.scheduler import solve_schedule


TARGET_REQUEST_ID = "REQ_E2E_WHATIF_TARGET"
BASELINE_WINNER_ID = "REQ_E2E_WHATIF_BASELINE_WINNER"


class StaticWhatIfAIClient:
    def chat(self, messages, **kwargs):
        return json.dumps(
            {
                "intent": "MODIFY_SCENARIO",
                "operations": [
                    {
                        "operation": "SET_PRIORITY",
                        "request_id": TARGET_REQUEST_ID,
                        "value": 10,
                    }
                ],
                "requires_resolve": True,
            }
        )


def _priority(scenario, request_id):
    return next(
        request["priority"]
        for request in scenario["requests"]
        if request["request_id"] == request_id
    )


def test_what_if_solver_and_evidence_share_modified_temp_scenario(monkeypatch):
    baseline_scenario = {
        "scenario_id": "E2E_WHATIF_EVIDENCE_CONSISTENCY",
        "requests": [
            {
                "request_id": TARGET_REQUEST_ID,
                "satellite_id": "NORAD_92001",
                "required_contact_seconds": 900,
                "priority": 5,
                "eligible_station_ids": ["GS_E2E_WHATIF_SHARED"],
                "mandatory": False,
            },
            {
                "request_id": BASELINE_WINNER_ID,
                "satellite_id": "NORAD_92002",
                "required_contact_seconds": 900,
                "priority": 9,
                "eligible_station_ids": ["GS_E2E_WHATIF_SHARED"],
                "mandatory": False,
            },
        ],
    }
    visibility_data = {
        "planning_horizon": {
            "start": "2026-08-24T00:00:00Z",
            "end": "2026-08-25T00:00:00Z",
        },
        "minimum_elevation_deg": 10.0,
        "visibility_windows": [
            {
                "window_id": "VW_E2E_WHATIF_TARGET",
                "satellite_id": "NORAD_92001",
                "station_id": "GS_E2E_WHATIF_SHARED",
                "aos": "2026-08-24T10:00:00Z",
                "los": "2026-08-24T10:15:00Z",
                "duration_seconds": 900,
                "max_elevation_deg": 40.0,
            },
            {
                "window_id": "VW_E2E_WHATIF_BASELINE_WINNER",
                "satellite_id": "NORAD_92002",
                "station_id": "GS_E2E_WHATIF_SHARED",
                "aos": "2026-08-24T10:00:00Z",
                "los": "2026-08-24T10:15:00Z",
                "duration_seconds": 900,
                "max_elevation_deg": 42.0,
            },
        ],
    }
    ai_client = StaticWhatIfAIClient()

    monkeypatch.setattr(
        what_if,
        "load_scenario",
        lambda scenario_id: copy.deepcopy(baseline_scenario),
    )
    monkeypatch.setattr(
        data_pipeline,
        "_load_mission_requests",
        lambda: copy.deepcopy(baseline_scenario),
    )
    monkeypatch.setattr(
        data_pipeline,
        "_get_visibility_data",
        lambda: visibility_data,
    )
    monkeypatch.setattr(intent_parser, "GraniteClient", lambda: ai_client)
    monkeypatch.setattr(granite, "GraniteClient", lambda: ai_client)

    observed = {
        "apply_inputs": [],
        "temp_scenarios": [],
        "solver_missions": [],
        "evidence_runs": [],
    }
    evidence_frames = {}

    def record_real_data_flow(frame, event, arg):
        if frame.f_code is apply_operations_to_scenario.__code__:
            if event == "call":
                observed["apply_inputs"].append(frame.f_locals["base_scenario"])
            elif event == "return":
                observed["temp_scenarios"].append(arg)

        elif frame.f_code is solve_schedule.__code__ and event == "call":
            observed["solver_missions"].append(frame.f_locals["mission_data"])

        elif frame.f_code is build_conflict_evidence.__code__:
            if event == "call":
                evidence_frames[id(frame)] = frame.f_locals["mission_data"]
            elif event == "return":
                mission_data = evidence_frames.pop(id(frame))
                observed["evidence_runs"].append((mission_data, arg))

    request = WhatIfRequest(
        base_scenario_id=baseline_scenario["scenario_id"],
        user_query=f"Raise {TARGET_REQUEST_ID} to priority 10",
    )
    what_if._PENDING_WHAT_IFS.clear()
    previous_profile = sys.getprofile()
    sys.setprofile(record_real_data_flow)
    try:
        first_response = what_if.process_what_if_query(request)
        second_response = what_if.process_what_if_query(request)
        pending_schedules = [
            copy.deepcopy(
                what_if._PENDING_WHAT_IFS[response.what_if_id]["schedule"]
            )
            for response in (first_response, second_response)
        ]
    finally:
        sys.setprofile(previous_profile)
        what_if._PENDING_WHAT_IFS.clear()

    assert _priority(baseline_scenario, TARGET_REQUEST_ID) == 5
    assert len(observed["apply_inputs"]) == 2
    assert all(
        _priority(base_input, TARGET_REQUEST_ID) == 5
        for base_input in observed["apply_inputs"]
    )
    assert observed["apply_inputs"][0] is not observed["apply_inputs"][1]

    assert len(observed["temp_scenarios"]) == 2
    assert all(
        _priority(temp_scenario, TARGET_REQUEST_ID) == 10
        for temp_scenario in observed["temp_scenarios"]
    )
    assert observed["temp_scenarios"][0] is not observed["temp_scenarios"][1]

    for temp_scenario in observed["temp_scenarios"]:
        modified_solver_missions = [
            mission
            for mission in observed["solver_missions"]
            if mission is temp_scenario
        ]
        modified_evidence_runs = [
            evidence
            for mission, evidence in observed["evidence_runs"]
            if mission is temp_scenario
        ]
        assert len(modified_solver_missions) == 1
        assert len(modified_evidence_runs) == 1

        evidence_record = modified_evidence_runs[0]["evidence"][0]
        assert evidence_record["request_id"] == BASELINE_WINNER_ID
        assert evidence_record["reason_codes"] == ["ANTENNA_RESOURCE_CONFLICT"]
        assert evidence_record["conflicts"][0]["conflicting_request_id"] == (
            TARGET_REQUEST_ID
        )
        assert evidence_record["conflicts"][0][
            "conflicting_request_priority"
        ] == 10
        assert evidence_record["conflicts"][0][
            "conflicting_request_priority"
        ] != 5

    proposed_identities = []
    for response, pending_schedule in zip(
        (first_response, second_response),
        pending_schedules,
    ):
        assert response.result is not None
        assert response.result.can_apply is True
        scheduled_ids = {
            contact["request_id"]
            for contact in response.result.proposed_schedule["scheduled_contacts"]
        }
        assert scheduled_ids == {TARGET_REQUEST_ID}
        assert response.result.proposed_schedule["scheduled_contacts"][0][
            "priority"
        ] == 10

        proposed_unscheduled = response.result.proposed_schedule[
            "unscheduled_requests"
        ]
        assert len(proposed_unscheduled) == 1
        assert proposed_unscheduled[0]["request_id"] == BASELINE_WINNER_ID
        assert proposed_unscheduled[0]["reason_codes"] == [
            "ANTENNA_RESOURCE_CONFLICT"
        ]
        assert proposed_unscheduled[0]["reason_codes"] != ["UNSCHEDULED"]
        assert proposed_unscheduled[0]["conflicts"] == [
            {
                "conflicting_request_id": TARGET_REQUEST_ID,
                "station_id": "GS_E2E_WHATIF_SHARED",
                "overlap_start": "2026-08-24T10:00:00Z",
                "overlap_end": "2026-08-24T10:15:00Z",
                "overlap_seconds": 900,
                "request_priority": 9,
                "conflicting_request_priority": 10,
            }
        ]

        exposed_evidence = response.result.conflict_evidence
        assert exposed_evidence is not None
        assert exposed_evidence["scenario_id"] == baseline_scenario["scenario_id"]
        assert exposed_evidence["evidence"][0]["request_id"] == BASELINE_WINNER_ID
        assert exposed_evidence["evidence"][0]["reason_codes"] == [
            "ANTENNA_RESOURCE_CONFLICT"
        ]
        assert exposed_evidence["evidence"][0]["conflicts"] == (
            proposed_unscheduled[0]["conflicts"]
        )
        assert response.result.model_dump()["conflict_evidence"] == exposed_evidence
        assert pending_schedule == response.result.proposed_schedule
        assert pending_schedule["unscheduled_requests"][0]["reason_codes"] == [
            "ANTENNA_RESOURCE_CONFLICT"
        ]
        proposed_identities.append(
            (
                tuple(sorted(scheduled_ids)),
                tuple(
                    request["request_id"]
                    for request in proposed_unscheduled
                ),
            )
        )

    assert proposed_identities[0] == proposed_identities[1]

    assert _priority(baseline_scenario, TARGET_REQUEST_ID) == 5
