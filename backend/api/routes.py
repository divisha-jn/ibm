import logging

from fastapi import APIRouter, HTTPException
from backend.api.schemas import (
    ExplainRequest,
    ExplainResponse,
    ExplainEvidence,
    ConflictRecord,
    WhatIfRequest,
    WhatIfResponse,
    ApplyWhatIfRequest,
    ApplyWhatIfResponse,
    AlternativesRequest,
    AlternativesResponse,
    RiskRequest,
    RiskResponse,
    ScheduleResult,
)
from backend.api.what_if import (
    process_what_if_query,
    apply_what_if,
    WhatIfNotApplicableError,
)
from backend.api.data_pipeline import (
    build_live_schedule,
    build_live_conflict_evidence,
    build_live_alternatives,
    build_live_risk,
)

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
    Returns a natural-language explanation for a scheduling decision.

    Works for both scheduled and unscheduled requests:
    - Unscheduled: passes conflict evidence to Granite to explain why it failed.
    - Scheduled:   passes the contact record to Granite to explain the decision.

    Falls back to a factual stub string when Granite or ortools is unavailable.
    """
    # Step 1: get the live schedule
    schedule = build_live_schedule()

    # Step 2: build conflict evidence (only populated for unscheduled requests)
    evidence_envelope = None
    if schedule is not None:
        evidence_envelope = build_live_conflict_evidence(schedule)

    # Step 3: check whether this request was scheduled or unscheduled
    scheduled_contact = None
    if schedule is not None:
        scheduled_contact = next(
            (c for c in schedule.get("scheduled_contacts", [])
             if c["request_id"] == request.request_id),
            None,
        )

    # Step 4: produce the explanation
    explanation = _explain_from_evidence(
        request.request_id, evidence_envelope, scheduled_contact,
        user_question=request.user_question,
        conversation_history=request.conversation_history,
    )

    # Step 5: extract structured evidence (only for unscheduled)
    evidence = _extract_evidence(request.request_id, evidence_envelope)

    # Step 6: detect clarification response from Granite
    clarification_question: str | None = None
    if explanation.startswith("Could you clarify"):
        clarification_question = explanation
        explanation = ""

    return ExplainResponse(
        request_id=request.request_id,
        explanation=explanation,
        evidence=evidence,
        clarification_question=clarification_question,
    )


def _extract_evidence(request_id: str, evidence_envelope: dict | None) -> ExplainEvidence | None:
    """
    Pull the structured evidence record for request_id out of the contract #6
    envelope and return it as an ExplainEvidence model for P5 to render.
    Returns None when the pipeline is down or the request was scheduled successfully.
    """
    if not evidence_envelope:
        return None

    record = next(
        (r for r in evidence_envelope.get("evidence", [])
         if r["request_id"] == request_id),
        None,
    )
    if record is None:
        return None

    return ExplainEvidence(
        reason_codes=record.get("reason_codes", []),
        conflicts=[
            ConflictRecord(
                conflicting_request_id=c["conflicting_request_id"],
                station_id=c["station_id"],
                overlap_seconds=c["overlap_seconds"],
                request_priority=c["request_priority"],
                conflicting_request_priority=c.get("conflicting_request_priority"),
            )
            for c in record.get("conflicts", [])
        ],
        feasibility=record.get("feasibility", {}),
        alternative_window_ids=record.get("alternative_window_ids", []),
    )


def _explain_from_evidence(
    request_id: str,
    evidence_envelope: dict | None,
    scheduled_contact: dict | None,
    *,
    user_question: str | None = None,
    conversation_history: list | None = None,
) -> str:
    """
    Produce a Granite explanation for a scheduling decision.

    - If the request is scheduled: explain what the scheduler decided and why.
    - If the request is unscheduled: explain why it failed using conflict evidence.
    - Falls back to a factual string when Granite or the pipeline is unavailable.
    """
    # --- Scheduled request: explain the positive decision ---
    if scheduled_contact is not None:
        scheduled_evidence = {
            "request_id": request_id,
            "status": "SCHEDULED",
            "station_id": scheduled_contact.get("station_id"),
            "antenna_id": scheduled_contact.get("antenna_id"),
            "scheduled_start": scheduled_contact.get("scheduled_start"),
            "scheduled_end": scheduled_contact.get("scheduled_end"),
            "duration_seconds": scheduled_contact.get("duration_seconds"),
            "priority": scheduled_contact.get("priority"),
        }
        try:
            from backend.ai.explain import explain_conflict as granite_explain
            return granite_explain(
                {"scenario_id": evidence_envelope.get("scenario_id") if evidence_envelope else None,
                 "evidence": [scheduled_evidence]},
                request_id=request_id,
                user_question=user_question,
                conversation_history=conversation_history,
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("Granite explain unavailable for scheduled request (%s) — using factual fallback.", exc)
        return (
            f"{request_id} (priority {scheduled_contact.get('priority')}) was scheduled at "
            f"{scheduled_contact.get('station_id')} from {scheduled_contact.get('scheduled_start')} "
            f"to {scheduled_contact.get('scheduled_end')} "
            f"({scheduled_contact.get('duration_seconds')}s)."
        )

    # --- Pipeline unavailable ---
    if not evidence_envelope:
        return (
            f"Explanation for {request_id} is not available "
            "(live solver pipeline inactive — check ortools installation)."
        )

    # --- Unscheduled request: explain the failure ---
    record = next(
        (r for r in evidence_envelope.get("evidence", [])
         if r["request_id"] == request_id),
        None,
    )

    if record is None:
        return f"No scheduling record found for {request_id}."

    # Try Granite explanation
    try:
        from backend.ai.explain import explain_conflict as granite_explain
        return granite_explain(
            evidence_envelope,
            request_id=request_id,
            user_question=user_question,
            conversation_history=conversation_history,
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("Granite explain_conflict unavailable (%s) — using factual fallback.", exc)

    # Factual fallback
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



@router.post("/alternatives", response_model=AlternativesResponse)
def get_alternatives(request: AlternativesRequest):
    """
    Returns solver-validated ranked alternative resolutions for one
    unscheduled request — contract #8 (contracts/alternatives.example.json).
    Real re-solves against candidate windows, ranked by operational
    disruption (fewest and lowest-priority displaced/rescheduled requests
    first). Not an LLM suggestion.

    Falls back to a PIPELINE_UNAVAILABLE status (still HTTP 200, matching
    /schedule and /explain's fail-inward convention) when ortools is
    unavailable, request_id is unknown, or any solver step fails — check
    `status` rather than the HTTP status code.
    """
    schedule = build_live_schedule()
    evidence = build_live_conflict_evidence(schedule) if schedule is not None else None
    result = (
        build_live_alternatives(
            schedule, evidence, request.request_id, limit=request.limit
        )
        if schedule is not None and evidence is not None
        else None
    )

    if result is None:
        return AlternativesResponse(
            scenario_id=request.scenario_id,
            request_id=request.request_id,
            status="PIPELINE_UNAVAILABLE",
        )

    # Ask Granite to narrate the alternatives — falls back gracefully if unavailable
    explanation: str | None = None
    try:
        from backend.ai.explain import explain_alternatives
        explanation = explain_alternatives(result)
    except Exception as exc:  # noqa: BLE001
        logger.info("Granite explain_alternatives unavailable (%s) — omitting narrative.", exc)

    return AlternativesResponse(**result, explanation=explanation)


@router.post("/risk", response_model=RiskResponse)
def get_risk(request: RiskRequest):
    """
    Returns the Operational Risk Index (0–100) for one request plus a
    Granite narrative explaining the score in plain language.

    Score and level are computed entirely by the deterministic solver
    (assess_operational_risk). Granite only narrates — it never influences
    the calculation.

    Falls back to PIPELINE_UNAVAILABLE (HTTP 200) when ortools is unavailable
    or any pipeline step fails.
    """
    schedule = build_live_schedule()
    evidence = build_live_conflict_evidence(schedule) if schedule is not None else None

    if schedule is None or evidence is None:
        return RiskResponse(
            scenario_id=request.scenario_id,
            request_id=request.request_id,
            satellite_id="UNKNOWN",
            schedule_status="UNKNOWN",
            assessment_status="PIPELINE_UNAVAILABLE",
        )

    risk_result = build_live_risk(
        schedule,
        evidence,
        request.request_id,
        include_weather=request.include_weather,
    )

    if risk_result is None:
        return RiskResponse(
            scenario_id=request.scenario_id,
            request_id=request.request_id,
            satellite_id="UNKNOWN",
            schedule_status="UNKNOWN",
            assessment_status="PIPELINE_UNAVAILABLE",
        )

    # Ask Granite to narrate the risk assessment — falls back gracefully
    narrative: str | None = None
    try:
        from backend.ai.explain import explain_risk
        narrative = explain_risk(risk_result, conversation_history=request.conversation_history)
    except Exception as exc:  # noqa: BLE001
        logger.info("Granite explain_risk unavailable (%s) — omitting narrative.", exc)

    return RiskResponse(**risk_result, narrative=narrative)


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
