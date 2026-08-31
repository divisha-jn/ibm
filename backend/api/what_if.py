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
parse_what_if()      → falls back to a narrow, validated local parser for
                       explicit request-priority changes when Granite is
                       unavailable or returns an invalid response.
solve_schedule()     → falls back to _MOCK_NEW_SCHEDULE when ortools is
                       unavailable (Python 3.13 dev machines).
explain_conflict()   → falls back to _build_explanation_from_ops() when
                       Granite credentials are absent or the live solver
                       pipeline is not running.
"""

import logging
import re
import uuid

from backend.api.schemas import (
    IntentInterpretation,
    IntentOperation,
    WhatIfRequest,
    WhatIfResponse,
    WhatIfResult,
)
from backend.api.scenario import (
    load_scenario,
    apply_operations_to_scenario,
)
from backend.api.comparison import compare_schedules
from backend.api.data_pipeline import (
    _enrich_unscheduled_requests,
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
    """
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
        clarification_question=wi.clarification_question,
    )


# ---------------------------------------------------------------------------
# Intent parsing  —  real P3 call with validated local fallback
# ---------------------------------------------------------------------------

# Explicit patterns — require REQ_XXX id AND a numeric value.
_LOCAL_PRIORITY_EXPLICIT_PATTERNS = (
    re.compile(
        r"^\s*(?:\[Context:[^\]]*\]\s*)?(?:what\s+if\s+)?(?:raise|set|bump)\s+"
        r"(?P<request_id>REQ_[A-Z0-9_]+)(?:'s)?\s+"
        r"(?:priority\s+)?(?:to|=|is)\s+"
        r"(?P<priority>[+-]?\d+)\s*\??\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:\[Context:[^\]]*\]\s*)?(?:what\s+if\s+)?"
        r"(?P<request_id>REQ_[A-Z0-9_]+)\s+"
        r"(?:becomes|is)\s+priority\s+"
        r"(?P<priority>[+-]?\d+)\s*\??\s*$",
        re.IGNORECASE,
    ),
)

# Vague priority change — direction word, no explicit id or value required.
_LOCAL_PRIORITY_VAGUE_PATTERN = re.compile(
    r"^\s*(?:\[Context:[^\]]*\]\s*)?"
    r"(?:what\s+(?:would\s+)?happen\s+if\s+(?:i\s+)?|what\s+if\s+(?:i\s+)?|if\s+(?:i\s+)?)"
    r"(?P<direction>raise[sd]?|increase[sd]?|bump(?:ed)?|change[sd]?|lower(?:ed)?|decrease[sd]?|reduce[sd]?)\s+"
    r"(?:the\s+)?(?:mission\s+|request\s+)?priority\??\s*$",
    re.IGNORECASE,
)

# Vague mandatory change.
_LOCAL_MANDATORY_VAGUE_PATTERN = re.compile(
    r"^\s*(?:\[Context:[^\]]*\]\s*)?"
    r"(?:what\s+(?:would\s+)?happen\s+if\s+(?:this\s+)?|what\s+if\s+(?:this\s+)?)"
    r"(?:becomes?\s+mandatory|is\s+mandatory|must\s+be\s+scheduled|has\s+to\s+run)\??\s*$",
    re.IGNORECASE,
)

# Vague disable station.
_LOCAL_DISABLE_VAGUE_PATTERN = re.compile(
    r"^\s*(?:\[Context:[^\]]*\]\s*)?"
    r"(?:what\s+(?:would\s+)?happen\s+if\s+|what\s+if\s+)"
    r"(?:a\s+)?(?:ground\s+)?station\s+(?:goes?\s+offline|is\s+disabled|fails?)\??\s*$",
    re.IGNORECASE,
)

# Extract [Context: selected request is REQ_XXX] prefix injected by frontend.
_CONTEXT_REQUEST_RE = re.compile(
    r"\[Context:\s*selected\s+request\s+is\s+(?P<request_id>REQ_[A-Z0-9_]+)\]",
    re.IGNORECASE,
)


def _needs_clarification(question: str) -> IntentInterpretation:
    return IntentInterpretation(
        intent="NEEDS_CLARIFICATION",
        operations=[],
        requires_resolve=False,
        clarification_question=question,
    )


def _unsupported_local_intent(error: str) -> IntentInterpretation:
    return IntentInterpretation(
        intent="UNSUPPORTED",
        operations=[],
        requires_resolve=False,
        error=error,
    )


def _resolve_request_id_from_context(query: str, scenario_context: dict) -> str | None:
    """Extract request_id from [Context:] prefix, or from scenario if only one request."""
    m = _CONTEXT_REQUEST_RE.search(query)
    if m:
        return m.group("request_id")
    requests = [r for r in scenario_context.get("requests", []) if isinstance(r, dict)]
    if len(requests) == 1:
        return requests[0].get("request_id")
    return None


def _parse_local_priority_intent(
    query: str,
    scenario_context: dict,
) -> IntentInterpretation:
    """Local fallback parser when Granite is unavailable.

    Handles explicit commands, vague commands with ±2 default, and returns
    NEEDS_CLARIFICATION when required information is missing but the intent is clear.
    """
    known_requests = {
        r.get("request_id", "").upper(): r
        for r in scenario_context.get("requests", [])
        if isinstance(r, dict) and isinstance(r.get("request_id"), str)
    }
    station_ids = scenario_context.get("station_ids", [])

    # --- Explicit priority patterns ---
    for pattern in _LOCAL_PRIORITY_EXPLICIT_PATTERNS:
        m = pattern.fullmatch(query)
        if m:
            req = known_requests.get(m.group("request_id").upper())
            if req is None:
                return _unsupported_local_intent(f"Unknown request_id {m.group('request_id')!r}.")
            priority = int(m.group("priority"))
            if not 1 <= priority <= 10:
                return _unsupported_local_intent("Priority must be between 1 and 10.")
            return IntentInterpretation(
                intent="MODIFY_SCENARIO",
                operations=[IntentOperation(operation="SET_PRIORITY", request_id=req["request_id"], value=priority)],
                requires_resolve=True,
            )

    # --- Vague priority change (±2 from current, or ask which request) ---
    if _LOCAL_PRIORITY_VAGUE_PATTERN.fullmatch(query):
        request_id = _resolve_request_id_from_context(query, scenario_context)
        if request_id is None:
            return _needs_clarification(
                "Which request would you like to change the priority for? "
                f"Available: {', '.join(r.get('request_id','') for r in scenario_context.get('requests',[]))}"
            )
        req = known_requests.get(request_id.upper(), {})
        current = int(req.get("current_priority", req.get("priority", 5)))
        direction = _LOCAL_PRIORITY_VAGUE_PATTERN.fullmatch(query).group("direction").lower()
        if any(w in direction for w in ("raise", "increase", "bump", "change")):
            new_priority = min(current + 2, 10)
            note = f"Assumed priority {new_priority} (raised from {current}) — confirm or specify a value."
        else:
            new_priority = max(current - 2, 1)
            note = f"Assumed priority {new_priority} (lowered from {current}) — confirm or specify a value."
        return IntentInterpretation(
            intent="MODIFY_SCENARIO",
            operations=[IntentOperation(operation="SET_PRIORITY", request_id=request_id, value=new_priority)],
            requires_resolve=True,
            error=note,
        )

    # --- Vague mandatory change ---
    if _LOCAL_MANDATORY_VAGUE_PATTERN.fullmatch(query):
        request_id = _resolve_request_id_from_context(query, scenario_context)
        if request_id is None:
            return _needs_clarification(
                "Which request should become mandatory? "
                f"Available: {', '.join(r.get('request_id','') for r in scenario_context.get('requests',[]))}"
            )
        return IntentInterpretation(
            intent="MODIFY_SCENARIO",
            operations=[IntentOperation(operation="SET_MANDATORY", request_id=request_id, value=1)],
            requires_resolve=True,
        )

    # --- Vague disable station ---
    if _LOCAL_DISABLE_VAGUE_PATTERN.fullmatch(query):
        if not station_ids:
            return _unsupported_local_intent("No stations found in scenario context.")
        if len(station_ids) == 1:
            return IntentInterpretation(
                intent="MODIFY_SCENARIO",
                operations=[IntentOperation(operation="DISABLE_STATION", station_id=station_ids[0])],
                requires_resolve=True,
            )
        return _needs_clarification(
            f"Which station should go offline? Available: {', '.join(station_ids)}"
        )

    # --- No match: ask for clarification instead of hard UNSUPPORTED ---
    lower = query.lower()
    if any(kw in lower for kw in ("priority", "mandatory", "station", "duration", "schedule", "disable", "change", "what if", "what would")):
        return _needs_clarification(
            "I couldn't parse that request. Could you be more specific? For example: "
            "'What if REQ_002 becomes priority 8?' or 'What if this becomes mandatory?'"
        )

    return _unsupported_local_intent(
        "This type of change is not supported. Supported operations: "
        "SET_PRIORITY, SET_REQUIRED_DURATION, DISABLE_STATION, SET_ELIGIBLE_STATIONS, SET_MANDATORY."
    )


def _parse_intent(
    query: str,
    scenario_context: dict,
    conversation_history: list | None = None,
) -> IntentInterpretation:
    """
    Call P3's parse_what_if() and convert the result to IntentInterpretation.

    Falls back to the narrow local priority parser when:
      - Granite credentials are not configured (GraniteConfigurationError)
      - Granite returns an unparseable or invalid response (IntentParserError)
    Both are expected in dev/CI; logged at INFO level, not ERROR.
    """
    try:
        from backend.ai.intent_parser import parse_what_if, IntentParserError
        from backend.ai.granite import GraniteConfigurationError
        wi = parse_what_if(query, scenario_context, conversation_history=conversation_history)
        return _interpretation_from_granite(wi)
    except Exception as exc:  # noqa: BLE001
        # Narrow the log level: config missing is expected in dev, not a bug.
        logger.info(
            "parse_what_if unavailable (%s: %s) — using local priority parser.",
            type(exc).__name__, exc,
        )

    return _parse_local_priority_intent(query, scenario_context)


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
    base_schedule: dict,
    new_schedule: dict,
    evidence_envelope: dict | None,
    user_query: str | None = None,
) -> str:
    """
    Produce a natural-language explanation for the what-if result.

    Always uses explain_outcome() so the narrative is framed as "what did your
    change accomplish?" rather than "why was this rejected?". Conflict evidence
    (when present) is passed as a condensed summary so Granite can mention
    which requests are still blocked — without hijacking the frame.

    Falls back to a factual string when Granite is unavailable.
    """
    # Condense conflict evidence into a compact summary for the outcome prompt.
    # Only include reason_codes + conflicts — not the full feasibility dump.
    conflict_summary = None
    if evidence_envelope and evidence_envelope.get("evidence"):
        conflict_summary = [
            {
                "request_id": r["request_id"],
                "reason_codes": r.get("reason_codes", []),
                "conflicts": [
                    {
                        "conflicting_request_id": c["conflicting_request_id"],
                        "station_id": c["station_id"],
                        "overlap_seconds": c["overlap_seconds"],
                    }
                    for c in r.get("conflicts", [])
                ],
            }
            for r in evidence_envelope["evidence"]
        ]

    try:
        from backend.ai.explain import explain_outcome
        ops_dicts = [op.model_dump(exclude_none=True) for op in intent.operations]
        return explain_outcome(
            ops_dicts, base_schedule, new_schedule,
            user_query=user_query,
            conflict_summary=conflict_summary,
        )
    except Exception as exc:  # noqa: BLE001
        logger.info(
            "explain_outcome unavailable (%s: %s) — using operation fallback.",
            type(exc).__name__, exc,
        )

    return _build_explanation_from_ops(intent, new_schedule)


def _first_unscheduled_id(intent, new_schedule: dict) -> str | None:
    """Return the first newly-affected request_id for focused Granite explanation."""
    for op in intent.operations:
        if op.request_id:
            return op.request_id
    unscheduled = new_schedule.get("unscheduled_requests", [])
    return unscheduled[0]["request_id"] if unscheduled else None


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

    if op.operation == "SET_MANDATORY":
        mandatory = bool(op.value)
        if mandatory:
            return (
                f"{op.request_id} was marked mandatory. The solver must now "
                "find a slot for it; other requests may be displaced."
            )
        return (
            f"{op.request_id} was marked non-mandatory and the schedule was re-solved."
        )

    return "The scenario was re-solved with the requested modifications."


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def process_what_if_query(request: WhatIfRequest) -> WhatIfResponse:
    what_if_id = f"WI_{uuid.uuid4().hex[:6].upper()}"

    # 1. Load base scenario — full mission_requests.json so the solver gets
    #    all fields (satellite_id, required_contact_seconds, eligible_station_ids)
    base_scenario = load_scenario(request.base_scenario_id)

    # Build scenario_context for P3's intent parser — include satellite_id so
    # Granite can map friendly names like "SAT-B" or "NORAD_48274" to request_ids.
    scenario_context = {
        "scenario_id": base_scenario.get("scenario_id"),
        "requests": [
            {
                "request_id": r["request_id"],
                "satellite_id": r.get("satellite_id", ""),
                "current_priority": r.get("priority", 5),
            }
            for r in base_scenario.get("requests", [])
        ],
        "station_ids": list({
            s
            for r in base_scenario.get("requests", [])
            for s in r.get("eligible_station_ids", [])
        }),
    }

    # 2. Parse user query → structured operations  (P3, with fallback)
    intent = _parse_intent(request.user_query, scenario_context, conversation_history=request.conversation_history)

    # Short-circuit: return clarification question without running the solver.
    if intent.intent == "NEEDS_CLARIFICATION":
        return WhatIfResponse(
            what_if_id=what_if_id,
            base_scenario_id=request.base_scenario_id,
            user_query=request.user_query,
            interpretation=intent,
            result=None,
        )

    result = None

    if intent.requires_resolve:
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
            evidence_envelope = build_live_conflict_evidence(
                new_schedule,
                mission_data=temp_scenario,
            )
            if evidence_envelope is not None:
                _enrich_unscheduled_requests(new_schedule, evidence_envelope)

        # 8. Natural-language explanation  (P3, with op-based fallback)
        explanation = _get_explanation(
            intent, base_schedule, new_schedule, evidence_envelope,
            user_query=request.user_query,
        )

        result = WhatIfResult(
            solver_status=new_schedule["solver"]["status"],
            impact=impact,
            proposed_schedule=new_schedule,
            explanation=explanation,
            conflict_evidence=evidence_envelope,
        )

    # intent == "UNSUPPORTED": result stays None (valid per Optional[WhatIfResult])
    return WhatIfResponse(
        what_if_id=what_if_id,
        base_scenario_id=request.base_scenario_id,
        user_query=request.user_query,
        interpretation=intent,
        result=result,
    )


