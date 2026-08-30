from pydantic import BaseModel
from typing import List, Dict, Any, Optional

# ---------------------------------------------------------------------------
# Shared — one conflicting-contact detail. Used by both /schedule
# (unscheduled_requests[].conflicts) and /explain (evidence.conflicts).
# ---------------------------------------------------------------------------

class ConflictRecord(BaseModel):
    conflicting_request_id: str
    station_id: str
    overlap_seconds: int
    request_priority: int
    conflicting_request_priority: Optional[int]

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
    conflicts: List[ConflictRecord] = []

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
    user_question: Optional[str] = None  # free-text question to focus Granite's answer

class ExplainEvidence(BaseModel):
    reason_codes: List[str]
    conflicts: List[ConflictRecord]
    feasibility: Dict[str, Any]
    alternative_window_ids: List[str]

class ExplainResponse(BaseModel):
    request_id: str
    explanation: str
    evidence: Optional[ExplainEvidence] = None  # None when pipeline is down or request was scheduled

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
    conflict_evidence: Optional[Dict[str, Any]] = None

class WhatIfResponse(BaseModel):
    what_if_id: str
    base_scenario_id: str
    user_query: str
    interpretation: IntentInterpretation
    result: Optional[WhatIfResult]     # None when intent == "UNSUPPORTED"

# ---------------------------------------------------------------------------
# What-if apply — commits a previously computed what-if result as the new
# scenario baseline (persisted to data/mission_requests.json).
# ---------------------------------------------------------------------------

class ApplyWhatIfRequest(BaseModel):
    what_if_id: str

class ApplyWhatIfResponse(BaseModel):
    applied: bool
    what_if_id: str
    scenario_id: str
    schedule: Dict[str, Any]  # full contract #5 shape — the newly-committed baseline

# ---------------------------------------------------------------------------
# Contract #8 — ranked alternatives (contracts/alternatives.example.json).
# Real, solver-validated alternative windows for one unscheduled request
# (P2's rank_alternatives(), not an LLM suggestion).
# ---------------------------------------------------------------------------

class AlternativesRequest(BaseModel):
    scenario_id: str
    request_id: str
    limit: int = 3

class RankingMetrics(BaseModel):
    displaced_count: int
    displaced_priority_total: int
    rescheduled_count: int
    rescheduled_priority_total: int

class AlternativeWindow(BaseModel):
    rank: int
    alternative_type: str
    window_id: str
    station_id: str
    scheduled_start: str
    scheduled_end: str
    duration_seconds: int
    displaced_request_ids: List[str]
    rescheduled_request_ids: List[str]
    ranking_metrics: RankingMetrics

class AlternativesResponse(BaseModel):
    scenario_id: str
    request_id: str
    satellite_id: Optional[str] = None
    # ALTERNATIVES_FOUND | NO_FEASIBLE_ALTERNATIVES | REQUEST_ALREADY_SCHEDULED
    # | PIPELINE_UNAVAILABLE (P4 app-level status — ortools down, unknown
    # request_id, or any other solver-side failure; matches /schedule and
    # /explain's fail-inward-with-200 convention rather than a 5xx)
    status: str
    reason_codes: List[str] = []
    alternatives: List[AlternativeWindow] = []

# ---------------------------------------------------------------------------
# Contract #9 — operational risk index (contracts/risk_assessment.example.json).
# P2's assess_operational_risk(): a deterministic, policy-defined 0-100 index
# (see docs/risk_methodolgy.md) — NOT AI-generated, NOT a failure probability.
#
# `factors`, `data_quality`, `contact`, and `conflict_evidence` are typed
# loosely (Dict[str, Any]) rather than as nested models: their per-factor
# `metrics` shape differs (scheduling_flexibility vs conflict_pressure vs
# space_weather, etc.) and assess_operational_risk() is the single source of
# truth for that shape — see contracts/risk_assessment.example.json for a
# full worked example. Same pattern already used for WhatIfResult.proposed_schedule.
# ---------------------------------------------------------------------------

class RiskRequest(BaseModel):
    scenario_id: str
    request_id: str
    include_alternatives: bool = True  # compute recovery-factor alternatives for unscheduled requests

class RiskResponse(BaseModel):
    scenario_id: str
    request_id: str
    satellite_id: Optional[str] = None
    schedule_status: str    # "SCHEDULED" | "UNSCHEDULED" | "UNKNOWN" (P4 fallback)
    # ASSESSED | UNRESOLVED | RISK_UNAVAILABLE (P4 app-level fallback — ortools
    # down, unknown request_id, or any step failed; same fail-inward-with-200
    # convention as /schedule, /explain, /alternatives)
    assessment_status: str
    contact: Optional[Dict[str, Any]] = None
    risk_score: Optional[int] = None       # 0-100, only when schedule_status == SCHEDULED
    risk_level: Optional[str] = None       # LOW | MEDIUM | HIGH, only when scored
    reason_codes: List[str] = []
    factors: Dict[str, Any] = {}
    data_quality: Dict[str, Any] = {}
    conflict_evidence: Optional[Dict[str, Any]] = None  # only present when UNSCHEDULED
