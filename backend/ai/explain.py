"""Solver-evidence -> natural-language explanation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .prompts import (
    build_explain_messages,
    build_what_if_outcome_messages,
    build_risk_explain_messages,
    build_alternatives_explain_messages,
)

if TYPE_CHECKING:
    from .granite import GraniteClient


def explain_conflict(
    evidence: dict[str, Any],
    *,
    request_id: str | None = None,
    user_question: str | None = None,
    client: GraniteClient | None = None,
) -> str:
    """Generate a grounded explanation from P2 conflict evidence.

    Granite is not allowed to create the evidence. The evidence passed here
    must come from the deterministic solver/conflict engine.

    Args:
        evidence:      Contract #6 envelope — { "scenario_id": ..., "evidence": [...] }.
        request_id:    When supplied, only the matching record is sent to Granite.
        user_question: Optional free-text question from the operator to focus the answer.
        client:        Optional pre-built GraniteClient (useful in tests).
    """
    if not isinstance(evidence, dict):
        raise TypeError("evidence must be a dictionary")

    if not evidence.get("evidence"):
        raise ValueError("No conflict evidence was supplied.")

    # Narrow the envelope to just the one record being asked about so Granite
    # doesn't have to guess which request to explain.
    if request_id is not None:
        matching = [
            r for r in evidence["evidence"]
            if r.get("request_id") == request_id
        ]
        if not matching:
            raise ValueError(f"No evidence record found for request_id={request_id!r}.")
        evidence = {"scenario_id": evidence.get("scenario_id"), "evidence": matching}

    if client is None:
        from .granite import GraniteClient

        client = GraniteClient()

    return client.chat(
        build_explain_messages(evidence, user_question=user_question),
        max_completion_tokens=300,
        temperature=0.0,
    )


def explain_outcome(
    operations: list[dict[str, Any]],
    base_schedule: dict[str, Any],
    new_schedule: dict[str, Any],
    *,
    client: "GraniteClient | None" = None,
) -> str:
    """Generate a natural-language explanation for a successful what-if outcome.

    Called when the re-solve produced a valid schedule (possibly with no new
    rejections), so there is no conflict evidence to pass to explain_conflict().

    Args:
        operations:   The list of operations that were applied (from intent).
        base_schedule: The original contract #5 schedule before the change.
        new_schedule:  The new contract #5 schedule after the re-solve.
        client:        Optional pre-built GraniteClient (useful in tests).
    """
    if client is None:
        from .granite import GraniteClient
        client = GraniteClient()

    return client.chat(
        build_what_if_outcome_messages(operations, base_schedule, new_schedule),
        max_completion_tokens=350,
        temperature=0.0,
    )


def explain_risk(
    risk_result: dict,
    *,
    client: "GraniteClient | None" = None,
) -> str:
    """Generate a natural-language narrative for a completed risk assessment.

    Granite receives only the already-computed score, level, factor breakdown,
    and reason codes — it never performs or influences the calculation itself.

    Args:
        risk_result: The dict returned by assess_operational_risk().
        client:      Optional pre-built GraniteClient (useful in tests).
    """
    if not isinstance(risk_result, dict):
        raise TypeError("risk_result must be a dictionary")
    if risk_result.get("assessment_status") not in ("ASSESSED", "UNRESOLVED"):
        raise ValueError(
            "risk_result must have assessment_status ASSESSED or UNRESOLVED."
        )

    if client is None:
        from .granite import GraniteClient
        client = GraniteClient()

    return client.chat(
        build_risk_explain_messages(risk_result),
        max_completion_tokens=350,
        temperature=0.0,
    )


def explain_alternatives(
    alternatives_result: dict,
    *,
    client: "GraniteClient | None" = None,
) -> str:
    """Generate a natural-language explanation for ranked alternative windows.

    Granite explains what the alternatives cost operationally and which one
    the operator should consider — grounded entirely in the solver output.

    Args:
        alternatives_result: The dict returned by rank_alternatives().
        client:              Optional pre-built GraniteClient (useful in tests).
    """
    if not isinstance(alternatives_result, dict):
        raise TypeError("alternatives_result must be a dictionary")
    if "status" not in alternatives_result:
        raise ValueError("alternatives_result must contain a 'status' field.")

    if client is None:
        from .granite import GraniteClient
        client = GraniteClient()

    return client.chat(
        build_alternatives_explain_messages(alternatives_result),
        max_completion_tokens=350,
        temperature=0.0,
    )


if __name__ == "__main__":
    # Local smoke test. Requires valid .env credentials.
    fake_evidence = {
        "scenario_id": "DEMO_001",
        "evidence": [
            {
                "request_id": "REQ_002",
                "status": "UNSCHEDULED",
                "reason_codes": ["ANTENNA_RESOURCE_CONFLICT"],
                "conflicts": [
                    {
                        "conflicting_request_id": "REQ_001",
                        "station_id": "GS_SG_01",
                        "antenna_id": "GS_SG_01_A1",
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

    print(explain_conflict(fake_evidence))
