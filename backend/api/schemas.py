from pydantic import BaseModel
from typing import List, Dict, Any, Optional

class ExplainRequest(BaseModel):
    scenario_id: str
    request_id: str

class ExplainResponse(BaseModel):
    request_id: str
    explanation: str

class WhatIfRequest(BaseModel):
    base_scenario_id: str
    user_query: str

class IntentOperation(BaseModel):
    operation: str
    request_id: str
    value: Any

class IntentInterpretation(BaseModel):
    intent: str
    operations: List[IntentOperation]
    requires_resolve: bool

class WhatIfImpact(BaseModel):
    newly_scheduled: List[str]
    newly_unscheduled: List[str]
    unchanged: List[str]

class WhatIfResult(BaseModel):
    solver_status: str
    impact: WhatIfImpact
    proposed_schedule: Dict[str, Any]
    explanation: str
    can_apply: bool

class WhatIfResponse(BaseModel):
    what_if_id: str
    base_scenario_id: str
    user_query: str
    interpretation: IntentInterpretation
    result: WhatIfResult