"""
backend/api/what_if.py

Orchestrates the POST /what-if flow:

    1. Parse user query → structured operations   via P3's parse_what_if()
    2. Load base scenario from data/mission_requests.json
    3. Apply operations to a temporary copy of the scenario
    4. Re-solve with the real OR-Tools solver      via P2's solve_schedule()
    5. Run conflict evidence on the new schedule   via P2's build_conflict_evidence()
    6. Explain the evidence in natural language    via P3's explain_conflict()
    7. Diff new vs baseline to produce WhatIfImpact
    8. Return WhatIfResponse (contract #7)

Fallback behaviour
------------------
parse_what_if()      → falls back to mock_parse_intent() when Granite
                       credentials are absent (GraniteConfigurationError) or
                       Granite returns an unparseable response (IntentParserError).
solve_schedule()     → falls back to _MOCK_NEW_SCHEDULE when ortools is
                       unavailable (Python 3.13 dev machines).
explain_conflict()   → falls back to _build_explanation_from_ops() when
                       Granite credentials are absent or the live solver
                       pipeline is not running.
"""

import logging
import uuid

from backend.api.schemas import (
    IntentInterpretation,
    IntentOperation,
    WhatIfRequest,
    WhatIfResponse,
    WhatIfResult,
)
from backend.api.scenario import load_scenario, apply_operations_to_scenario
from backend.api.comparison import compare_schedules
<<<<<<< Updated upstream
from backend.api.scheduling import obtain_visibility_data, run_scheduling

# Mock function standing in for Person 3's intent parsing.
def mock_parse_intent(query: str) -> IntentInterpretation:
=======
from backend.api.data_pipeline import (
    build_live_schedule,
    build_live_what_if_schedule,
    build_live_conflict_evidence,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Boundary converter  —  P3 model → P4 schema
# ---------------------------------------------------------------------------

def _interpretation_from_granite(wi) -> IntentInterpretation:
    """
    Convert a backend.ai.intent_parser.WhatIfInterpretation (P3's model)
    into an IntentInterpretation (P4's API schema).

    The fields are identical in name and meaning; this is purely a Pydantic
    model boundary crossing.  Written as an explicit converter (not .model_dump
    + re-validate) so any future divergence between the two models is a compile-
    time error here rather than a silent runtime mismatch.
    """
>>>>>>> Stashed changes
    return IntentInterpretation(
        intent=wi.intent,
        operations=[
            IntentOperation(
                operation=op.operation,
                request_id=op.request_id,
                station_id=op.station_id,
                station_ids=op.station_ids,
                value=op.value,
            )
            for op in wi.operations
        ],
        requires_resolve=wi.requires_resolve,
        error=wi.error,
    )

<<<<<<< Updated upstream
=======

# ---------------------------------------------------------------------------
# Intent parsing  —  real P3 call with mock fallback
# ---------------------------------------------------------------------------

def _parse_intent(
    query: str,
    scenario_context: dict,
) -> IntentInterpretation:
    """
    Call P3's parse_what_if() and convert the result to IntentInterpretation.

    Falls back to the hardcoded mock when:
      - Granite credentials are not configured (GraniteConfigurationError)
      - Granite returns an unparseable or invalid response (IntentParserError)
    Both are expected in dev/CI; logged at INFO level, not ERROR.
    """
    try:
        from backend.ai.intent_parser import parse_what_if, IntentParserError
        from backend.ai.granite import GraniteConfigurationError
        wi = parse_what_if(query, scenario_context)
        return _interpretation_from_granite(wi)
    except Exception as exc:  # noqa: BLE001
        # Narrow the log level: config missing is expected in dev, not a bug.
        logger.info(
            "parse_what_if unavailable (%s: %s) — using demo stub intent.",
            type(exc).__name__, exc,
        )

    # Fallback: always "boost REQ_002 to priority 10" for demo visibility.
    return IntentInterpretation(
        intent="MODIFY_SCENARIO",
        operations=[
            IntentOperation(operation="SET_PRIORITY", request_id="REQ_002", value=10)
        ],
        requires_resolve=True,
    )


# ---------------------------------------------------------------------------
# Fallback mock outputs  (served when ortools is unavailable)
# ---------------------------------------------------------------------------

_MOCK_NEW_SCHEDULE = {
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
        {
            "request_id": "REQ_001",
            "satellite_id": "NORAD_25544",
            "reason_codes": ["OPTIMIZATION_TRADEOFF"],
        }
    ],
}

_MOCK_BASE_SCHEDULE = {
    "scheduled_contacts": [{"request_id": "REQ_001"}],
    "unscheduled_requests":  [{"request_id": "REQ_002"}],
}


# ---------------------------------------------------------------------------
# Explanation  —  real P3 call with operation-based fallback
# ---------------------------------------------------------------------------

def _get_explanation(
    intent: IntentInterpretation,
    new_schedule: dict,
    evidence_envelope: dict | None,
) -> str:
    """
    Produce a natural-language explanation for the what-if result.

    Priority order:
      1. P3's explain_conflict(evidence_envelope) when evidence is available
         and Granite is configured.
      2. Factual string derived from the operation list (always available).
    """
    if evidence_envelope:
        try:
            from backend.ai.explain import explain_conflict
            from backend.ai.granite import GraniteConfigurationError
            return explain_conflict(evidence_envelope)
        except Exception as exc:  # noqa: BLE001
            logger.info(
                "explain_conflict unavailable (%s: %s) — using operation fallback.",
                type(exc).__name__, exc,
            )

    return _build_explanation_from_ops(intent, new_schedule)


def _build_explanation_from_ops(
    intent: IntentInterpretation,
    new_schedule: dict,
) -> str:
    """Factual fallback explanation derived solely from the operation list."""
    if not intent.operations:
        return "The scenario was re-solved with the requested modifications."

    op = intent.operations[0]
    scheduled_ids = {c["request_id"] for c in new_schedule.get("scheduled_contacts", [])}

    if op.operation == "SET_PRIORITY":
        if op.request_id in scheduled_ids:
            return (
                f"Raising {op.request_id}'s priority to {op.value} caused it to "
                "displace lower-priority competing requests. It is now scheduled."
            )
        return (
            f"Despite raising {op.request_id}'s priority to {op.value}, it "
            "could not be scheduled — no feasible visibility window is available."
        )

    if op.operation == "SET_REQUIRED_DURATION":
        return (
            f"Changing {op.request_id}'s required contact duration to "
            f"{op.value} seconds was applied and the schedule was re-solved."
        )

    if op.operation == "DISABLE_STATION":
        return (
            f"Ground station {op.station_id} was removed from all eligible "
            "station lists and the schedule was re-solved."
        )

    if op.operation == "SET_ELIGIBLE_STATIONS":
        return (
            f"{op.request_id}'s eligible stations were restricted to "
            f"{op.station_ids} and the schedule was re-solved."
        )

    return "The scenario was re-solved with the requested modifications."


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

>>>>>>> Stashed changes
def process_what_if_query(request: WhatIfRequest) -> WhatIfResponse:
    what_if_id = f"WI_{uuid.uuid4().hex[:6].upper()}"

    # 1. Load base scenario — full mission_requests.json so the solver gets
    #    all fields (satellite_id, required_contact_seconds, eligible_station_ids)
    base_scenario = load_scenario(request.base_scenario_id)

    # Build scenario_context for P3's intent parser — only valid identifiers
    # so Granite cannot invent a request_id or station_id.
    scenario_context = {
        "scenario_id": base_scenario.get("scenario_id"),
        "requests": [
            {"request_id": r["request_id"]}
            for r in base_scenario.get("requests", [])
        ],
        "station_ids": list({
            s
            for r in base_scenario.get("requests", [])
            for s in r.get("eligible_station_ids", [])
        }),
    }

    # 2. Parse user query → structured operations  (P3, with fallback)
    intent = _parse_intent(request.user_query, scenario_context)

    result = None

    if intent.requires_resolve:
<<<<<<< Updated upstream
        # 3. Ask OR-Tools (Person 2) to solve the base and temporary scenarios.
        visibility_data = obtain_visibility_data()
        old_run = run_scheduling(visibility_data, base_scenario)
        new_run = run_scheduling(visibility_data, temp_scenario)
        old_schedule = old_run.schedule_result
        new_schedule = new_run.schedule_result
        
        # 4. Compare results to generate impact
        impact = compare_schedules(old_schedule, new_schedule)
        
        # 5. Build final result
=======
        # 3. Apply mutations to a sandbox copy of the scenario
        temp_scenario = apply_operations_to_scenario(base_scenario, intent.operations)

        # 4. Re-solve  (P2, with mock fallback when ortools unavailable)
        new_schedule = build_live_what_if_schedule(temp_scenario)
        using_live = new_schedule is not None
        if not using_live:
            logger.info("what-if: ortools unavailable — using mock schedule.")
            new_schedule = _MOCK_NEW_SCHEDULE

        # 5. Get baseline for impact diffing
        base_schedule = build_live_schedule()
        if base_schedule is None:
            base_schedule = _MOCK_BASE_SCHEDULE

        # 6. Compute impact diff
        impact = compare_schedules(base_schedule, new_schedule)

        # 7. Build conflict evidence for the explanation  (P2)
        evidence_envelope = None
        if using_live:
            evidence_envelope = build_live_conflict_evidence(new_schedule)

        # 8. Natural-language explanation  (P3, with op-based fallback)
        explanation = _get_explanation(intent, new_schedule, evidence_envelope)

>>>>>>> Stashed changes
        result = WhatIfResult(
            solver_status=new_schedule["solver"]["status"],
            impact=impact,
            proposed_schedule=new_schedule,
            explanation=explanation,
            can_apply=using_live,
        )

    # intent == "UNSUPPORTED": result stays None (valid per Optional[WhatIfResult])
    return WhatIfResponse(
        what_if_id=what_if_id,
        base_scenario_id=request.base_scenario_id,
        user_query=request.user_query,
        interpretation=intent,
<<<<<<< Updated upstream
        result=result
=======
        result=result,
>>>>>>> Stashed changes
    )
