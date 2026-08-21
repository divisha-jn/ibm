"""P4 orchestration between deterministic P2 evidence and P3 explanations."""

from __future__ import annotations

from typing import Any

from backend.ai.explain import explain_conflict


def explain_request_conflict(
    conflict_evidence: dict,
    request_id: str,
    *,
    client: Any = None,
) -> str:
    """Select one P2 evidence record, preserve its wrapper, and ask P3 to explain."""
    matching_evidence = [
        record
        for record in conflict_evidence.get("evidence", [])
        if record.get("request_id") == request_id
    ]
    if not matching_evidence:
        raise LookupError(f"No conflict evidence found for request_id={request_id}")

    selected_wrapper = {
        "scenario_id": conflict_evidence["scenario_id"],
        "evidence": matching_evidence,
    }
    return explain_conflict(selected_wrapper, client=client)
