"""Solver-evidence -> natural-language explanation."""

from __future__ import annotations

from typing import Any

from .granite import GraniteClient
from .prompts import build_explain_messages


def explain_conflict(
    evidence: dict[str, Any],
    *,
    client: GraniteClient | None = None,
) -> str:
    """Generate a grounded explanation from P2 conflict evidence.

    Granite is not allowed to create the evidence. The evidence passed here
    must come from the deterministic solver/conflict engine.
    """
    if not isinstance(evidence, dict):
        raise TypeError("evidence must be a dictionary")

    if not evidence.get("evidence"):
        raise ValueError("No conflict evidence was supplied.")

    granite = client or GraniteClient()
    return granite.chat(
        build_explain_messages(evidence),
        max_completion_tokens=300,
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