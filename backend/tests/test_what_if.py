"""
Tests for backend/api/what_if.py and backend/api/scenario.py.

Verifies the full orchestration flow with the real pipeline mocked out,
so these tests run on any Python version regardless of ortools availability.
"""
import pytest
from unittest.mock import patch, MagicMock

from backend.api import what_if as what_if_module
from backend.api.schemas import WhatIfRequest, WhatIfResponse, WhatIfResult
from backend.api.what_if import (
    process_what_if_query,
    _build_explanation_from_ops,
    _interpretation_from_granite,
    _parse_intent,
)
from backend.api.scenario import load_scenario, apply_operations_to_scenario
from backend.api.schemas import IntentOperation, IntentInterpretation


# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

BASE_SCENARIO = {
    "scenario_id": "DEMO_001",
    "requests": [
        {
            "request_id": "REQ_001",
            "satellite_id": "NORAD_25544",
            "required_contact_seconds": 300,
            "priority": 8,
            "eligible_station_ids": ["GS_SG_01", "GS_PERTH_01"],
            "mandatory": False,
        },
        {
            "request_id": "REQ_002",
            "satellite_id": "NORAD_48274",
            "required_contact_seconds": 300,
            "priority": 5,
            "eligible_station_ids": ["GS_SG_01", "GS_PERTH_01"],
            "mandatory": False,
        },
    ],
}

MOCK_NEW_SCHEDULE = {
    "scenario_id": "DEMO_001",
    "solver": {"engine": "OR-Tools CP-SAT", "status": "OPTIMAL", "objective_value": 10.0},
    "scheduled_contacts": [
        {
            "request_id": "REQ_002",
            "satellite_id": "NORAD_48274",
            "station_id": "GS_SG_01",
            "antenna_id": "GS_SG_01_A1",
            "window_id": "VW_0001",
            "scheduled_start": "2026-08-11T02:14:00Z",
            "scheduled_end": "2026-08-11T02:19:00Z",
            "duration_seconds": 300,
            "priority": 10,
        }
    ],
    "unscheduled_requests": [
        {"request_id": "REQ_001", "satellite_id": "NORAD_25544", "reason_codes": ["OPTIMIZATION_TRADEOFF"]}
    ],
}

MOCK_BASE_SCHEDULE = {
    "scheduled_contacts": [{"request_id": "REQ_001"}],
    "unscheduled_requests": [{"request_id": "REQ_002"}],
}


# ---------------------------------------------------------------------------
# scenario.py — load_scenario
# ---------------------------------------------------------------------------

class TestLoadScenario:
    def test_returns_dict_with_requests(self):
        scenario = load_scenario("DEMO_001")
        assert "requests" in scenario
        assert len(scenario["requests"]) >= 1

    def test_each_request_has_required_solver_fields(self):
        scenario = load_scenario("DEMO_001")
        for req in scenario["requests"]:
            for field in ("request_id", "satellite_id", "required_contact_seconds",
                          "priority", "eligible_station_ids"):
                assert field in req, f"Missing field '{field}' in request {req.get('request_id')}"

    def test_returns_deep_copy(self):
        a = load_scenario("DEMO_001")
        b = load_scenario("DEMO_001")
        a["requests"][0]["priority"] = 999
        assert b["requests"][0]["priority"] != 999


# ---------------------------------------------------------------------------
# scenario.py — apply_operations_to_scenario
# ---------------------------------------------------------------------------

class TestApplyOperations:
    def test_set_priority(self):
        ops = [IntentOperation(operation="SET_PRIORITY", request_id="REQ_002", value=10)]
        result = apply_operations_to_scenario(BASE_SCENARIO, ops)
        req = next(r for r in result["requests"] if r["request_id"] == "REQ_002")
        assert req["priority"] == 10

    def test_set_priority_does_not_mutate_original(self):
        ops = [IntentOperation(operation="SET_PRIORITY", request_id="REQ_002", value=10)]
        apply_operations_to_scenario(BASE_SCENARIO, ops)
        original = next(r for r in BASE_SCENARIO["requests"] if r["request_id"] == "REQ_002")
        assert original["priority"] == 5

    def test_set_required_duration(self):
        ops = [IntentOperation(operation="SET_REQUIRED_DURATION", request_id="REQ_001", value=600)]
        result = apply_operations_to_scenario(BASE_SCENARIO, ops)
        req = next(r for r in result["requests"] if r["request_id"] == "REQ_001")
        assert req["required_contact_seconds"] == 600

    def test_disable_station_removes_from_all_requests(self):
        ops = [IntentOperation(operation="DISABLE_STATION", station_id="GS_SG_01")]
        result = apply_operations_to_scenario(BASE_SCENARIO, ops)
        for req in result["requests"]:
            assert "GS_SG_01" not in req["eligible_station_ids"]

    def test_disable_station_keeps_other_stations(self):
        ops = [IntentOperation(operation="DISABLE_STATION", station_id="GS_SG_01")]
        result = apply_operations_to_scenario(BASE_SCENARIO, ops)
        for req in result["requests"]:
            assert "GS_PERTH_01" in req["eligible_station_ids"]

    def test_set_eligible_stations(self):
        ops = [IntentOperation(
            operation="SET_ELIGIBLE_STATIONS",
            request_id="REQ_002",
            station_ids=["GS_PERTH_01"],
        )]
        result = apply_operations_to_scenario(BASE_SCENARIO, ops)
        req = next(r for r in result["requests"] if r["request_id"] == "REQ_002")
        assert req["eligible_station_ids"] == ["GS_PERTH_01"]

    def test_set_eligible_stations_only_affects_target(self):
        ops = [IntentOperation(
            operation="SET_ELIGIBLE_STATIONS",
            request_id="REQ_002",
            station_ids=["GS_PERTH_01"],
        )]
        result = apply_operations_to_scenario(BASE_SCENARIO, ops)
        req001 = next(r for r in result["requests"] if r["request_id"] == "REQ_001")
        assert req001["eligible_station_ids"] == ["GS_SG_01", "GS_PERTH_01"]

    def test_unknown_operation_does_not_raise(self):
        ops = [IntentOperation(operation="UNKNOWN_OP", request_id="REQ_001", value=5)]
        # should not raise — silently skipped
        result = apply_operations_to_scenario(BASE_SCENARIO, ops)
        assert result is not None

    def test_multiple_operations_applied_in_order(self):
        ops = [
            IntentOperation(operation="SET_PRIORITY", request_id="REQ_002", value=10),
            IntentOperation(operation="SET_REQUIRED_DURATION", request_id="REQ_002", value=600),
        ]
        result = apply_operations_to_scenario(BASE_SCENARIO, ops)
        req = next(r for r in result["requests"] if r["request_id"] == "REQ_002")
        assert req["priority"] == 10
        assert req["required_contact_seconds"] == 600


# ---------------------------------------------------------------------------
# what_if.py — process_what_if_query (pipeline mocked)
# ---------------------------------------------------------------------------

class TestProcessWhatIfQuery:

    def _run(self, live_what_if=None, live_base=None):
        """Run process_what_if_query with the pipeline patched."""
        req = WhatIfRequest(
            base_scenario_id="DEMO_001",
            user_query="What if REQ_002 becomes priority 10?",
        )
        with patch("backend.api.what_if.build_live_what_if_schedule", return_value=live_what_if), \
             patch("backend.api.what_if.build_live_schedule", return_value=live_base):
            return process_what_if_query(req)

    def test_response_shape(self):
        resp = self._run(live_what_if=None, live_base=None)
        assert isinstance(resp, WhatIfResponse)
        assert resp.what_if_id.startswith("WI_")
        assert resp.base_scenario_id == "DEMO_001"
        assert resp.result is not None

    def test_mock_fallback_impact_is_correct(self):
        # When both pipeline calls return None, mock schedules are used.
        # Mock: REQ_002 newly scheduled, REQ_001 newly unscheduled.
        resp = self._run(live_what_if=None, live_base=None)
        assert "REQ_002" in resp.result.impact.newly_scheduled
        assert "REQ_001" in resp.result.impact.newly_unscheduled

    def test_live_schedule_used_when_available(self):
        resp = self._run(live_what_if=MOCK_NEW_SCHEDULE, live_base=MOCK_BASE_SCHEDULE)
        assert resp.result.solver_status == "OPTIMAL"

    def test_proposed_schedule_contains_solver_key(self):
        resp = self._run(live_what_if=MOCK_NEW_SCHEDULE, live_base=MOCK_BASE_SCHEDULE)
        assert "solver" in resp.result.proposed_schedule

    def test_unsupported_intent_returns_none_result(self):
        req = WhatIfRequest(
            base_scenario_id="DEMO_001",
            user_query="Delete all satellites",
        )
        unsupported = IntentInterpretation(
            intent="UNSUPPORTED",
            operations=[],
            requires_resolve=False,
            error="Not supported",
        )
        with patch("backend.api.what_if._parse_intent", return_value=unsupported), \
             patch("backend.api.what_if.build_live_what_if_schedule", return_value=None), \
             patch("backend.api.what_if.build_live_schedule", return_value=None):
            resp = process_what_if_query(req)
        assert resp.result is None
        assert resp.interpretation.intent == "UNSUPPORTED"

    def test_each_call_gets_unique_what_if_id(self):
        ids = {self._run().what_if_id for _ in range(5)}
        assert len(ids) == 5


# ---------------------------------------------------------------------------
# what_if.py — _build_explanation_from_ops
# ---------------------------------------------------------------------------

class TestBuildExplanation:
    def _intent(self, op):
        return IntentInterpretation(
            intent="MODIFY_SCENARIO",
            operations=[op],
            requires_resolve=True,
        )

    def test_set_priority_scheduled(self):
        intent = self._intent(IntentOperation(operation="SET_PRIORITY", request_id="REQ_002", value=10))
        schedule = {"scheduled_contacts": [{"request_id": "REQ_002"}]}
        text = _build_explanation_from_ops(intent, schedule)
        assert "REQ_002" in text
        assert "10" in text

    def test_set_priority_not_scheduled(self):
        intent = self._intent(IntentOperation(operation="SET_PRIORITY", request_id="REQ_002", value=10))
        schedule = {"scheduled_contacts": []}
        text = _build_explanation_from_ops(intent, schedule)
        assert "could not be scheduled" in text

    def test_disable_station(self):
        intent = self._intent(IntentOperation(operation="DISABLE_STATION", station_id="GS_SG_01"))
        text = _build_explanation_from_ops(intent, {"scheduled_contacts": []})
        assert "GS_SG_01" in text

    def test_set_eligible_stations(self):
        intent = self._intent(IntentOperation(
            operation="SET_ELIGIBLE_STATIONS",
            request_id="REQ_002",
            station_ids=["GS_PERTH_01"],
        ))
        text = _build_explanation_from_ops(intent, {"scheduled_contacts": []})
        assert "GS_PERTH_01" in text

    def test_no_operations_returns_generic(self):
        intent = IntentInterpretation(intent="MODIFY_SCENARIO", operations=[], requires_resolve=True)
        text = _build_explanation_from_ops(intent, {"scheduled_contacts": []})
        assert len(text) > 0


# ---------------------------------------------------------------------------
# what_if.py — _interpretation_from_granite  (P3 → P4 converter)
# ---------------------------------------------------------------------------

class TestInterpretationFromGranite:
    def _make_wi(self, **kwargs):
        """Build a minimal WhatIfInterpretation-like object via MagicMock."""
        from unittest.mock import MagicMock
        wi = MagicMock()
        wi.intent = kwargs.get("intent", "MODIFY_SCENARIO")
        wi.requires_resolve = kwargs.get("requires_resolve", True)
        wi.error = kwargs.get("error", None)
        wi.clarification_question = kwargs.get("clarification_question", None)
        ops = []
        for op_kwargs in kwargs.get("operations", []):
            op = MagicMock()
            op.operation = op_kwargs["operation"]
            op.request_id = op_kwargs.get("request_id")
            op.station_id = op_kwargs.get("station_id")
            op.station_ids = op_kwargs.get("station_ids")
            op.value = op_kwargs.get("value")
            ops.append(op)
        wi.operations = ops
        return wi

    def test_converts_intent_field(self):
        wi = self._make_wi(intent="MODIFY_SCENARIO", operations=[
            {"operation": "SET_PRIORITY", "request_id": "REQ_002", "value": 10}
        ])
        result = _interpretation_from_granite(wi)
        assert result.intent == "MODIFY_SCENARIO"

    def test_converts_operations(self):
        wi = self._make_wi(operations=[
            {"operation": "SET_PRIORITY", "request_id": "REQ_002", "value": 10}
        ])
        result = _interpretation_from_granite(wi)
        assert len(result.operations) == 1
        assert result.operations[0].operation == "SET_PRIORITY"
        assert result.operations[0].request_id == "REQ_002"
        assert result.operations[0].value == 10

    def test_converts_all_operation_fields(self):
        wi = self._make_wi(operations=[
            {
                "operation": "SET_ELIGIBLE_STATIONS",
                "request_id": "REQ_001",
                "station_ids": ["GS_SG_01"],
            }
        ])
        result = _interpretation_from_granite(wi)
        op = result.operations[0]
        assert op.station_ids == ["GS_SG_01"]
        assert op.station_id is None

    def test_converts_requires_resolve(self):
        wi = self._make_wi(requires_resolve=True, operations=[
            {"operation": "SET_PRIORITY", "request_id": "REQ_001", "value": 5}
        ])
        result = _interpretation_from_granite(wi)
        assert result.requires_resolve is True

    def test_converts_error_field(self):
        wi = self._make_wi(intent="UNSUPPORTED", requires_resolve=False,
                           error="Not supported.", operations=[])
        result = _interpretation_from_granite(wi)
        assert result.error == "Not supported."

    def test_result_is_intent_interpretation_instance(self):
        wi = self._make_wi(operations=[
            {"operation": "SET_PRIORITY", "request_id": "REQ_002", "value": 3}
        ])
        result = _interpretation_from_granite(wi)
        assert isinstance(result, IntentInterpretation)


# ---------------------------------------------------------------------------
# what_if.py — _parse_intent  (Granite call with mock fallback)
# ---------------------------------------------------------------------------

class TestParseIntent:
    _SCENARIO_CTX = {
        "scenario_id": "DEMO_001",
        "requests": [
            {"request_id": "REQ_001"},
            {"request_id": "REQ_002"},
            {"request_id": "REQ_003"},
        ],
        "station_ids": ["GS_SG_01"],
    }

    def test_local_fallback_preserves_explicit_request_id_and_priority(self):
        with patch(
            "backend.ai.intent_parser.parse_what_if",
            side_effect=RuntimeError("Granite unavailable"),
        ):
            result = _parse_intent(
                "Raise REQ_003 priority to 10",
                self._SCENARIO_CTX,
            )

        assert isinstance(result, IntentInterpretation)
        assert result.intent == "MODIFY_SCENARIO"
        assert result.requires_resolve is True
        assert result.operations == [
            IntentOperation(
                operation="SET_PRIORITY",
                request_id="REQ_003",
                value=10,
            )
        ]

    @pytest.mark.parametrize(
        "query",
        [
            "Raise REQ_999 priority to 10",
            "Raise REQ_003 priority to 11",
        ],
    )
    def test_local_fallback_rejects_unknown_or_invalid(self, query):
        with patch(
            "backend.ai.intent_parser.parse_what_if",
            side_effect=RuntimeError("Granite unavailable"),
        ):
            result = _parse_intent(query, self._SCENARIO_CTX)

        assert result.intent == "UNSUPPORTED"
        assert result.operations == []
        assert result.requires_resolve is False
        assert result.error

    @pytest.mark.parametrize(
        "query",
        [
            "Raise REQ_001 or REQ_003 priority to 10",
            "Disable GS_SG_01",
        ],
    )
    def test_local_fallback_asks_clarification_for_ambiguous(self, query):
        with patch(
            "backend.ai.intent_parser.parse_what_if",
            side_effect=RuntimeError("Granite unavailable"),
        ):
            result = _parse_intent(query, self._SCENARIO_CTX)

        assert result.intent == "NEEDS_CLARIFICATION"
        assert result.clarification_question

    def test_uses_granite_result_when_parse_what_if_succeeds(self):
        # Simulate parse_what_if returning a valid WhatIfInterpretation-like object
        from unittest.mock import MagicMock
        fake_wi = MagicMock()
        fake_wi.intent = "MODIFY_SCENARIO"
        fake_wi.requires_resolve = True
        fake_wi.error = None
        fake_wi.clarification_question = None
        fake_op = MagicMock()
        fake_op.operation = "SET_PRIORITY"
        fake_op.request_id = "REQ_001"
        fake_op.station_id = None
        fake_op.station_ids = None
        fake_op.value = 7
        fake_wi.operations = [fake_op]

        with patch("backend.ai.intent_parser.parse_what_if", return_value=fake_wi):
            result = _parse_intent(
                "Raise REQ_003 priority to 10",
                self._SCENARIO_CTX,
            )

        assert result.operations[0].value == 7
        assert result.operations[0].request_id == "REQ_001"


def test_what_if_result_serializes_optional_conflict_evidence():
    result = WhatIfResult(
        solver_status="OPTIMAL",
        impact={
            "newly_scheduled": ["REQ_003"],
            "newly_unscheduled": ["REQ_004"],
            "unchanged": [],
        },
        proposed_schedule=MOCK_NEW_SCHEDULE,
        explanation="REQ_003 now wins the shared station window.",
        conflict_evidence={
            "scenario_id": "DEMO_001",
            "evidence": [
                {
                    "request_id": "REQ_004",
                    "reason_codes": ["ANTENNA_RESOURCE_CONFLICT"],
                }
            ],
        },
    )

    dumped = result.model_dump()
    assert dumped["conflict_evidence"]["evidence"][0]["request_id"] == "REQ_004"


