import uuid
from backend.api.schemas import WhatIfRequest, WhatIfResponse, IntentInterpretation, IntentOperation, WhatIfResult
from backend.api.scenario import load_scenario, apply_operations_to_scenario
from backend.api.comparison import compare_schedules
from backend.api.scheduling import obtain_visibility_data, run_scheduling

# Mock function standing in for Person 3's intent parsing.
def mock_parse_intent(query: str) -> IntentInterpretation:
    return IntentInterpretation(
        intent="MODIFY_SCENARIO",
        operations=[IntentOperation(operation="SET_PRIORITY", request_id="REQ_002", value=10)],
        requires_resolve=True
    )

def process_what_if_query(request: WhatIfRequest) -> WhatIfResponse:
    # 1. Ask Granite (Person 3) to translate natural language into JSON operations
    intent = mock_parse_intent(request.user_query)
    
    # 2. Load base scenario and apply changes to a temporary copy
    base_scenario = load_scenario(request.base_scenario_id)
    temp_scenario = apply_operations_to_scenario(base_scenario, intent.operations)
    
    if intent.requires_resolve:
        # 3. Ask OR-Tools (Person 2) to solve the base and temporary scenarios.
        visibility_data = obtain_visibility_data()
        old_run = run_scheduling(visibility_data, base_scenario)
        new_run = run_scheduling(visibility_data, temp_scenario)
        old_schedule = old_run.schedule_result
        new_schedule = new_run.schedule_result
        
        # 4. Compare results to generate impact
        impact = compare_schedules(old_schedule, new_schedule)
        
        # 5. Build final result
        result = WhatIfResult(
            solver_status=new_schedule["solver"]["status"],
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
