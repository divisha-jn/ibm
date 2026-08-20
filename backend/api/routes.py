import logging

from fastapi import APIRouter, HTTPException
from backend.api.schemas import (
    ExplainRequest,
    ExplainResponse,
    WhatIfRequest,
    WhatIfResponse,
    ApplyWhatIfRequest,
    ApplyWhatIfResponse,
    ScheduleResult,
)
from backend.api.what_if import (
    process_what_if_query,
    apply_what_if,
    WhatIfNotApplicableError,
)
from backend.api.data_pipeline import build_live_schedule, build_live_conflict_evidence

logger = logging.getLogger(__name__)

router = APIRouter()

# Hardcoded fallback — served when ortools is unavailable or the live
# pipeline fails.  Shape is intentionally kept in sync with ScheduleResult.
_STUB_SCHEDULE = {
    "scenario_id": "DEMO_001",
    "solver": {
        "engine": "OR-Tools CP-SAT",
        "status": "OPTIMAL",
        "objective_value": 13.0,
    },
    "scheduled_contacts": [
        {
            "request_id": "REQ_001",
            "satellite_id": "NORAD_25544",
            "station_id": "GS_SG_01",
            "antenna_id": "GS_SG_01_A1",
            "window_id": "VW_0001",
            "scheduled_start": "2026-08-11T02:14:00Z",
            "scheduled_end": "2026-08-11T02:19:00Z",
            "duration_seconds": 300,
            "priority": 8,
        }
    ],
    "unscheduled_requests": [
        {
            "request_id": "REQ_002",
            "satellite_id": "NORAD_48274",
            "reason_codes": ["ANTENNA_RESOURCE_CONFLICT"],
        }
    ],
}


@router.get("/schedule", response_model=ScheduleResult)
def get_schedule():
    """
    Returns the baseline schedule — contract #5 (P2 → P4/P5).

    Attempts the live pipeline:
        P1: generate_all_visibility_windows()  (CelesTrak → Skyfield → passes)
        P2: solve_schedule()                   (OR-Tools CP-SAT)

    Falls back to the hardcoded stub when ortools is not installed (Python 3.13
    dev environment) or when any pipeline step fails.  The response shape is
    identical in both cases and is validated by ScheduleResult on every request.
    """
    result = build_live_schedule()
    if result is None:
        logger.info("Live pipeline unavailable — serving stub schedule.")
        return _STUB_SCHEDULE
    return result


@router.post("/explain", response_model=ExplainResponse)
def explain_conflict(request: ExplainRequest):
    """
    Returns a natural-language explanation for why a request was unscheduled.

    Flow (contract #6 → Granite → contract #3 response):
        1. Fetch the current baseline schedule via build_live_schedule().
        2. Run build_conflict_evidence() on that schedule to get grounded
           evidence for the requested request_id.
        3. Pass evidence to backend/ai/explain.py explain_conflict() which
           calls Granite (P3).  Falls back to a factual stub string when
           Granite credentials are absent or ortools is unavailable.
    """
    # Step 1: get the live schedule (needed to build evidence)
    schedule = build_live_schedule()

    # Step 2: build conflict evidence from the real schedule
    evidence_envelope = None
    if schedule is not None:
        evidence_envelope = build_live_conflict_evidence(schedule)

    # Step 3: find the evidence record for this request_id
    explanation = _explain_from_evidence(request.request_id, evidence_envelope)

    return ExplainResponse(
        request_id=request.request_id,
        explanation=explanation,
    )


def _explain_from_evidence(request_id: str, evidence_envelope: dict | None) -> str:
    """
    Extract the explanation for request_id from a contract #6 evidence envelope.

    When Granite credentials are available, calls backend/ai/explain.py.
    Falls back to a factual string built from the solver evidence when
    Granite is not configured (common during development).
    """
    if not evidence_envelope:
        return (
            f"Conflict evidence for {request_id} is not available "
            "(live solver pipeline inactive — check ortools installation)."
        )

    # Find the evidence record for this request
    record = next(
        (r for r in evidence_envelope.get("evidence", [])
         if r["request_id"] == request_id),
        None,
    )

    if record is None:
        return (
            f"{request_id} was scheduled successfully — no conflict evidence found."
        )

    # Try real Granite explanation (P3)
    try:
        from backend.ai.explain import explain_conflict as granite_explain
        return granite_explain(evidence_envelope)
    except Exception as exc:  # noqa: BLE001
        logger.info(
            "Granite explain_conflict unavailable (%s) — using factual fallback.", exc
        )

    # Factual fallback built from solver evidence
    reason_codes = record.get("reason_codes", [])
    conflicts = record.get("conflicts", [])

    if not conflicts:
        return (
            f"{request_id} could not be scheduled. "
            f"Reason: {', '.join(reason_codes) or 'unknown'}."
        )

    c = conflicts[0]
    return (
        f"{request_id} (priority {c['request_priority']}) could not be scheduled "
        f"because it conflicts with {c['conflicting_request_id']} "
        f"(priority {c['conflicting_request_priority']}) "
        f"at {c['station_id']} with {c['overlap_seconds']}s overlap. "
        f"Reason: {', '.join(reason_codes)}."
    )



@router.post("/what-if", response_model=WhatIfResponse)
def what_if_scenario(request: WhatIfRequest):
    """
    Orchestrates the full AI intent → scenario mutation → solver → comparison
    flow.  Returns contract #7.
    """
    return process_what_if_query(request)


@router.post("/what-if/apply", response_model=ApplyWhatIfResponse)
def apply_what_if_route(request: ApplyWhatIfRequest):
    """
    Commit a previously computed /what-if result as the new scenario
    baseline. Overwrites data/mission_requests.json so subsequent /schedule
    and /what-if calls start from the applied state.

    Only what-if results computed against the live solver (can_apply=True
    in the original /what-if response) are applicable — mock-fallback
    results, unknown ids, and already-applied ids all 404.
    """
    try:
        schedule = apply_what_if(request.what_if_id)
    except WhatIfNotApplicableError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return ApplyWhatIfResponse(
        applied=True,
        what_if_id=request.what_if_id,
        scenario_id=schedule["scenario_id"],
        schedule=schedule,
    )
