from pydantic import BaseModel
from typing import List, Dict, Any, Optional

# ---------------------------------------------------------------------------
# Contract #5 — schedule_result  (P2 → P4/P5)
# ---------------------------------------------------------------------------

class ScheduledContact(BaseModel):
    request_id: str
    satellite_id: str
    station_id: str
    antenna_id: str
    window_id: str
    scheduled_start: str
    scheduled_end: str
    duration_seconds: int
    priority: int

class UnscheduledRequest(BaseModel):
    request_id: str
    satellite_id: str
    reason_codes: List[str]

class SolverMeta(BaseModel):
    engine: str
    status: str
    objective_value: Optional[float]

class ScheduleResult(BaseModel):
    scenario_id: str
    solver: SolverMeta
    scheduled_contacts: List[ScheduledContact]
    unscheduled_requests: List[UnscheduledRequest]

# ---------------------------------------------------------------------------
# Contract #3 (explain endpoint) — driven by conflict_evidence (#6)
# ---------------------------------------------------------------------------

class ExplainRequest(BaseModel):
    scenario_id: str
    request_id: str

class ExplainResponse(BaseModel):
    request_id: str
    explanation: str

# ---------------------------------------------------------------------------
# Contract #7 — what_if
# ---------------------------------------------------------------------------

class WhatIfRequest(BaseModel):
    base_scenario_id: str
    user_query: str

class IntentOperation(BaseModel):
    """
    One mutation to apply to a scenario before re-solving.

    Supported operations and their required fields:
      SET_PRIORITY           → request_id + value (int)
      SET_REQUIRED_DURATION  → request_id + value (seconds, int)
      DISABLE_STATION        → station_id
      SET_ELIGIBLE_STATIONS  → request_id + station_ids
    """
    operation: str
    request_id: Optional[str] = None
    station_id: Optional[str] = None
    station_ids: Optional[List[str]] = None
    value: Optional[int] = None

class IntentInterpretation(BaseModel):
    intent: str                        # "MODIFY_SCENARIO" | "UNSUPPORTED"
    operations: List[IntentOperation]
    requires_resolve: bool
    error: Optional[str] = None        # populated when intent == "UNSUPPORTED"

class WhatIfImpact(BaseModel):
    newly_scheduled: List[str]
    newly_unscheduled: List[str]
    unchanged: List[str]

class WhatIfResult(BaseModel):
    solver_status: str
    impact: WhatIfImpact
    proposed_schedule: Dict[str, Any]  # full contract #5 shape at runtime
    explanation: str
    can_apply: bool

class WhatIfResponse(BaseModel):
    what_if_id: str
    base_scenario_id: str
    user_query: str
    interpretation: IntentInterpretation
    result: Optional[WhatIfResult]     # None when intent == "UNSUPPORTED"
