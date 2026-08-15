"""Offline tests for the backend/ai layer.

All tests mock GraniteClient.chat so no .env credentials are needed.
"""

import json
import pytest
from unittest.mock import MagicMock

from backend.ai.explain import explain_conflict
from backend.ai.intent_parser import (
    IntentParserError,
    WhatIfInterpretation,
    _extract_json,
    parse_what_if,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_client(response: str) -> MagicMock:
    """Return a mock GraniteClient whose .chat() returns `response`."""
    client = MagicMock()
    client.chat.return_value = response
    return client


def make_evidence(request_id: str = "REQ_002", reason: str = "ANTENNA_RESOURCE_CONFLICT") -> dict:
    """Minimal valid conflict evidence matching Person 2's output format."""
    return {
        "scenario_id": "DEMO_001",
        "evidence": [
            {
                "request_id": request_id,
                "status": "UNSCHEDULED",
                "reason_codes": [reason],
                "conflicts": [
                    {
                        "conflicting_request_id": "REQ_001",
                        "station_id": "GS_SG_01",
                        "overlap_start": "2026-08-11T02:15:00Z",
                        "overlap_end": "2026-08-11T02:19:00Z",
                        "overlap_seconds": 240,
                        "request_priority": 5,
                        "conflicting_request_priority": 8,
                    }
                ],
                "feasibility": {
                    "requested_contact_seconds": 300,
                    "available_unconflicted_seconds": 180,
                },
            }
        ],
    }


def make_scenario_context() -> dict:
    """Minimal scenario context with known request and station IDs."""
    return {
        "requests": [
            {"request_id": "REQ_001"},
            {"request_id": "REQ_002"},
        ],
        "station_ids": ["GS_SG_01", "GS_SG_02"],
    }


# ---------------------------------------------------------------------------
# Feature A — explain_conflict()
# ---------------------------------------------------------------------------

class TestExplainConflict:

    def test_returns_granite_explanation(self):
        """Happy path: Granite's text is returned unchanged."""
        expected = "REQ_002 was not scheduled because GS_SG_01 was already occupied by REQ_001."
        client = make_client(expected)

        result = explain_conflict(make_evidence(), client=client)

        assert result == expected

    def test_passes_evidence_to_chat(self):
        """The evidence dict must reach Granite inside the user message."""
        client = make_client("some explanation")

        explain_conflict(make_evidence("REQ_002"), client=client)

        # chat() must have been called exactly once
        client.chat.assert_called_once()
        messages = client.chat.call_args[0][0]  # first positional arg

        # There must be a system message and a user message
        roles = [m["role"] for m in messages]
        assert roles == ["system", "user"]

        # The user message must contain the request_id from the evidence
        user_content = messages[1]["content"]
        assert "REQ_002" in user_content

    def test_raises_on_missing_evidence_key(self):
        """evidence dict without the 'evidence' key must raise ValueError."""
        client = make_client("irrelevant")

        with pytest.raises(ValueError, match="No conflict evidence"):
            explain_conflict({"scenario_id": "DEMO_001"}, client=client)

    def test_raises_on_empty_evidence_list(self):
        """An empty evidence list must raise ValueError."""
        client = make_client("irrelevant")

        with pytest.raises(ValueError, match="No conflict evidence"):
            explain_conflict({"scenario_id": "DEMO_001", "evidence": []}, client=client)

    def test_raises_on_non_dict_evidence(self):
        """Passing a non-dict must raise TypeError."""
        client = make_client("irrelevant")

        with pytest.raises(TypeError, match="evidence must be a dictionary"):
            explain_conflict(["not", "a", "dict"], client=client)

    def test_different_reason_codes_reach_granite(self):
        """Reason code variants from P2 must all flow through without error."""
        for reason in ("NO_ELIGIBLE_VISIBILITY_WINDOW", "INSUFFICIENT_WINDOW_DURATION", "OPTIMIZATION_TRADEOFF"):
            client = make_client(f"Explanation for {reason}")
            result = explain_conflict(make_evidence(reason=reason), client=client)
            assert reason in client.chat.call_args[0][0][1]["content"]


# ---------------------------------------------------------------------------
# Feature B — parse_what_if()
# ---------------------------------------------------------------------------

class TestParseWhatIf:

    def _valid_set_priority_json(self, request_id: str = "REQ_002", value: int = 10) -> str:
        return json.dumps({
            "intent": "MODIFY_SCENARIO",
            "operations": [
                {"operation": "SET_PRIORITY", "request_id": request_id, "value": value}
            ],
            "requires_resolve": True,
        })

    def test_set_priority_parses_correctly(self):
        """Happy path: Granite returns valid SET_PRIORITY JSON."""
        client = make_client(self._valid_set_priority_json())

        result = parse_what_if("What if REQ_002 becomes priority 10?", make_scenario_context(), client=client)

        assert result.intent == "MODIFY_SCENARIO"
        assert result.requires_resolve is True
        assert len(result.operations) == 1
        op = result.operations[0]
        assert op.operation == "SET_PRIORITY"
        assert op.request_id == "REQ_002"
        assert op.value == 10

    def test_disable_station_parses_correctly(self):
        """DISABLE_STATION with a known station_id must parse without error."""
        raw = json.dumps({
            "intent": "MODIFY_SCENARIO",
            "operations": [
                {"operation": "DISABLE_STATION", "station_id": "GS_SG_01"}
            ],
            "requires_resolve": True,
        })
        client = make_client(raw)

        result = parse_what_if("Disable GS_SG_01", make_scenario_context(), client=client)

        assert result.operations[0].operation == "DISABLE_STATION"
        assert result.operations[0].station_id == "GS_SG_01"

    def test_set_eligible_stations_parses_correctly(self):
        """SET_ELIGIBLE_STATIONS with known ids must parse without error."""
        raw = json.dumps({
            "intent": "MODIFY_SCENARIO",
            "operations": [
                {
                    "operation": "SET_ELIGIBLE_STATIONS",
                    "request_id": "REQ_001",
                    "station_ids": ["GS_SG_01", "GS_SG_02"],
                }
            ],
            "requires_resolve": True,
        })
        client = make_client(raw)

        result = parse_what_if("Restrict REQ_001 to both stations", make_scenario_context(), client=client)

        assert result.operations[0].station_ids == ["GS_SG_01", "GS_SG_02"]

    def test_unsupported_intent_returns_unsupported(self):
        """Granite returning UNSUPPORTED must be surfaced as-is."""
        raw = json.dumps({
            "intent": "UNSUPPORTED",
            "operations": [],
            "requires_resolve": False,
            "error": "Cannot reschedule past contacts.",
        })
        client = make_client(raw)

        result = parse_what_if("Move REQ_001 to last week", make_scenario_context(), client=client)

        assert result.intent == "UNSUPPORTED"
        assert result.error == "Cannot reschedule past contacts."
        assert result.operations == []

    def test_raises_on_empty_query(self):
        """Empty user query must raise ValueError before hitting Granite."""
        client = make_client("irrelevant")

        with pytest.raises(ValueError, match="user_query cannot be empty"):
            parse_what_if("   ", make_scenario_context(), client=client)

        client.chat.assert_not_called()

    def test_raises_on_invented_request_id(self):
        """Granite inventing an unknown request_id must raise IntentParserError."""
        client = make_client(self._valid_set_priority_json(request_id="REQ_999"))

        with pytest.raises(IntentParserError, match="Unknown request_id"):
            parse_what_if("What if REQ_999 becomes priority 10?", make_scenario_context(), client=client)

    def test_raises_on_invented_station_id(self):
        """Granite inventing an unknown station_id must raise IntentParserError."""
        raw = json.dumps({
            "intent": "MODIFY_SCENARIO",
            "operations": [
                {"operation": "DISABLE_STATION", "station_id": "GS_FAKE_99"}
            ],
            "requires_resolve": True,
        })
        client = make_client(raw)

        with pytest.raises(IntentParserError, match="Unknown station_id"):
            parse_what_if("Disable GS_FAKE_99", make_scenario_context(), client=client)

    def test_raises_on_negative_priority(self):
        """A negative priority value must raise IntentParserError."""
        client = make_client(self._valid_set_priority_json(value=-1))

        with pytest.raises(IntentParserError):
            parse_what_if("Set REQ_002 priority to -1", make_scenario_context(), client=client)

    def test_raises_on_granite_returning_plain_text(self):
        """Non-JSON response from Granite must raise IntentParserError."""
        client = make_client("Sure! I'll change the priority for you.")

        with pytest.raises(IntentParserError, match="did not return valid JSON"):
            parse_what_if("What if REQ_002 becomes priority 10?", make_scenario_context(), client=client)


# ---------------------------------------------------------------------------
# _extract_json() — internal JSON parsing edge cases
# ---------------------------------------------------------------------------

class TestExtractJson:

    def test_parses_plain_json(self):
        raw = '{"intent": "UNSUPPORTED", "operations": [], "requires_resolve": false}'
        result = _extract_json(raw)
        assert result["intent"] == "UNSUPPORTED"

    def test_parses_fenced_json_block(self):
        """Model sometimes wraps output in ```json ... ``` despite instructions."""
        raw = '```json\n{"intent": "UNSUPPORTED", "operations": [], "requires_resolve": false}\n```'
        result = _extract_json(raw)
        assert result["intent"] == "UNSUPPORTED"

    def test_parses_fenced_block_without_language_tag(self):
        raw = '```\n{"intent": "UNSUPPORTED", "operations": [], "requires_resolve": false}\n```'
        result = _extract_json(raw)
        assert result["intent"] == "UNSUPPORTED"

    def test_extracts_json_with_surrounding_text(self):
        """Last-resort: JSON embedded in prose."""
        raw = 'Here is the result: {"intent": "UNSUPPORTED", "operations": [], "requires_resolve": false} done.'
        result = _extract_json(raw)
        assert result["intent"] == "UNSUPPORTED"

    def test_raises_on_pure_text(self):
        with pytest.raises(IntentParserError, match="did not return valid JSON"):
            _extract_json("No JSON here at all.")

    def test_raises_on_empty_string(self):
        with pytest.raises(IntentParserError, match="did not return valid JSON"):
            _extract_json("")

    def test_raises_on_json_array_without_inner_object(self):
        """A bare JSON array of scalars (no inner object) must not be accepted."""
        with pytest.raises(IntentParserError, match="did not return valid JSON"):
            _extract_json('["SET_PRIORITY", "SET_REQUIRED_DURATION"]')
