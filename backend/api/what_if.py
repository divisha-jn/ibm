import uuid
from backend.api.schemas import WhatIfRequest, WhatIfResponse, IntentInterpretation, IntentOperation, WhatIfResult
from backend.api.scenario import load_scenario, apply_operations_to_scenario
from backend.api.comparison import compare_schedules

# Mock functions to stand in for Person 2 (Solver) and Person 3 (AI)
def mock_parse_intent(query: str) -> IntentInterpretation:
    return IntentInterpretation(
        intent="MODIFY_SCENARIO",
        operations=[IntentOperation(operation="SET_PRIORITY", request_id="REQ_002", value=10)],
        requires_resolve=True
    )

def mock_call_solver(scenario_data: dict) -> dict:
    return {
        "scheduled_contacts": [{"request_id": "REQ_002"}],
        "unscheduled_requests": [{"request_id": "REQ_001"}]
    }

def process_what_if_query(request: WhatIfRequest) -> WhatIfResponse:
    # 1. Ask Granite (Person 3) to translate natural language into JSON operations
    intent = mock_parse_intent(request.user_query)
    
    # 2. Load base scenario and apply changes to a temporary copy
    base_scenario = load_scenario(request.base_scenario_id)
    temp_scenario = apply_operations_to_scenario(base_scenario, intent.operations)
    
    if intent.requires_resolve:
        # 3. Ask OR-Tools (Person 2) to solve the temporary scenario
        old_schedule = {"scheduled_contacts": [{"request_id": "REQ_001"}]} # Mock base
        new_schedule = mock_call_solver(temp_scenario)
        
        # 4. Compare results to generate impact
        impact = compare_schedules(old_schedule, new_schedule)
        
        # 5. Build final result
        result = WhatIfResult(
            solver_status="OPTIMAL",
            impact=impact,
            proposed_schedule=new_schedule,
            explanation=f"Increasing {intent.operations[0].request_id}'s priority changes the preferred allocation. It becomes scheduled while competing lower-priority missions are unscheduled.",
            can_apply=True
        )
    else:
        # Handle non-solving queries (e.g., just info lookups)
        result = None 

    return WhatIfResponse(
        what_if_id=f"WI_{uuid.uuid4().hex[:6].upper()}",
        base_scenario_id=request.base_scenario_id,
        user_query=request.user_query,
        interpretation=intent,
        result=result
    )