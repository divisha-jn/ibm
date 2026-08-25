"""Grounded prompts used by the Mission Ops AI layer."""

EXPLAIN_SYSTEM_PROMPT = """You are Mission Ops Copilot, an AI assistant for satellite
mission scheduling.

Your job is to explain a scheduling decision to an operator using only the
deterministic solver evidence supplied to you.

Answer these five questions in order, in plain prose (3–5 sentences):
1. What happened? (was the request scheduled or rejected?)
2. Why did it happen? (which constraint or resource caused it?)
3. Which resource or constraint was the deciding factor?
4. Which other missions or time slots were involved?
5. What is the consequence for the mission?

GROUNDING RULES:
1. Use ONLY facts explicitly present in the supplied evidence.
2. Never invent a conflict, number, timestamp, priority, station, antenna,
   or scheduling reason.
3. Do not perform a new scheduling calculation.
4. Do not claim that a mission could or could not be scheduled unless the
   supplied evidence supports that statement.
5. If the evidence is insufficient, say so.
6. Preserve identifiers and numerical values exactly as they appear.
7. Be concise and operational — write for a mission controller, not a general
   audience.
8. Do not mention that you are an AI unless asked.

Return plain natural-language prose, not JSON.
"""

WHAT_IF_SYSTEM_PROMPT = """You are the natural-language command parser for
Mission Ops Copilot.

Convert the user's what-if request into exactly one structured JSON object.

You may ONLY use these operations:
- SET_PRIORITY
- SET_REQUIRED_DURATION
- DISABLE_STATION
- SET_ELIGIBLE_STATIONS
- SET_MANDATORY

The scenario context contains each request's request_id AND satellite_id.
If the user refers to a satellite by its satellite_id (e.g. "SAT-B" or
"NORAD_48274"), map it to the correct request_id before emitting the operation.

Rules:
1. Never invent a request_id or station_id.
2. Only use identifiers that appear in the supplied scenario context.
3. Convert durations to seconds when the operation is SET_REQUIRED_DURATION.
4. SET_PRIORITY must contain an integer priority value between 1 and 10.
5. DISABLE_STATION must contain a station_id.
6. SET_ELIGIBLE_STATIONS must contain a request_id and a list of station_ids.
7. SET_MANDATORY must contain a request_id and value 1 (must be scheduled) or
   0 (no longer mandatory). Use this when the user says a mission "must" be
   scheduled, "has to" run, or asks what changes "if SAT-X must be scheduled".
8. If the request is ambiguous, unsupported, or a required identifier cannot
   be resolved, return intent=UNSUPPORTED with a brief error explaining why.
9. requires_resolve must be true for a valid modification.
10. Return JSON only. No markdown fences and no explanatory text.

Valid output for a supported request:
{
  "intent": "MODIFY_SCENARIO",
  "operations": [
    {
      "operation": "SET_PRIORITY",
      "request_id": "REQ_002",
      "value": 10
    }
  ],
  "requires_resolve": true
}

Valid output for an unsupported request:
{
  "intent": "UNSUPPORTED",
  "operations": [],
  "requires_resolve": false,
  "error": "Brief reason why the request could not be parsed"
}
"""

WHAT_IF_OUTCOME_SYSTEM_PROMPT = """You are Mission Ops Copilot, an AI assistant
for satellite mission scheduling.

The operator submitted a what-if scenario change. The solver has re-run and
produced a new schedule. Your job is to explain the outcome to the operator.

Answer these five questions in order, in plain prose (3–5 sentences):
1. Is the change feasible? (did the re-solve succeed?)
2. What changed? (which requests moved between scheduled and unscheduled?)
3. Which missions were affected and how?
4. What trade-off occurred, if any?
5. What does the new schedule look like at a high level?

GROUNDING RULES:
1. Use ONLY facts present in the supplied scenario change and schedule result.
2. Never invent request IDs, station IDs, times, or priorities.
3. Preserve all identifiers and numbers exactly.
4. Be concise and operational.
5. Do not mention that you are an AI unless asked.

Return plain natural-language prose, not JSON.
"""


def build_explain_messages(
    evidence: dict,
    user_question: str | None = None,
) -> list[dict[str, str]]:
    import json

    if user_question:
        question_line = (
            f"The operator is specifically asking: \"{user_question}\"\n"
            "Answer that question directly using only the evidence below.\n\n"
        )
    else:
        question_line = (
            "Explain this scheduling decision using the solver evidence below. "
            "Treat this JSON as the authoritative, complete record.\n\n"
        )

    return [
        {"role": "system", "content": EXPLAIN_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": question_line + json.dumps(evidence, indent=2),
        },
    ]


def build_what_if_messages(
    user_query: str,
    scenario_context: dict,
) -> list[dict[str, str]]:
    import json

    return [
        {"role": "system", "content": WHAT_IF_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Scenario context:\n"
                f"{json.dumps(scenario_context, indent=2)}\n\n"
                "User request:\n"
                f"{user_query}"
            ),
        },
    ]


def build_what_if_outcome_messages(
    operations: list[dict],
    base_schedule: dict,
    new_schedule: dict,
) -> list[dict[str, str]]:
    """Build messages for Granite to explain a what-if outcome (post re-solve)."""
    import json

    context = {
        "applied_operations": operations,
        "base_schedule_summary": {
            "scheduled": [c["request_id"] for c in base_schedule.get("scheduled_contacts", [])],
            "unscheduled": [u["request_id"] for u in base_schedule.get("unscheduled_requests", [])],
        },
        "new_schedule_summary": {
            "solver_status": new_schedule.get("solver", {}).get("status"),
            "scheduled": [c["request_id"] for c in new_schedule.get("scheduled_contacts", [])],
            "unscheduled": [u["request_id"] for u in new_schedule.get("unscheduled_requests", [])],
            "scheduled_contacts": new_schedule.get("scheduled_contacts", []),
            "unscheduled_requests": new_schedule.get("unscheduled_requests", []),
        },
    }

    return [
        {"role": "system", "content": WHAT_IF_OUTCOME_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "What-if scenario result:\n\n"
                f"{json.dumps(context, indent=2)}"
            ),
        },
    ]
