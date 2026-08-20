from fastapi import APIRouter, HTTPException
from backend.api.explanations import explain_request_conflict
from backend.api.schemas import ExplainRequest, ExplainResponse, WhatIfRequest, WhatIfResponse
from backend.api.scenario import load_scenario
from backend.api.scheduling import obtain_visibility_data, run_scheduling
from backend.api.what_if import process_what_if_query

router = APIRouter()

@router.get("/schedule")
def get_schedule():
    """
    Returns the baseline schedule. Connected to Person 2's solver output.
    Returns Contract #5.
    """
    visibility_data = obtain_visibility_data()
    mission_data = load_scenario("DEMO_001")
    return run_scheduling(visibility_data, mission_data).schedule_result

@router.post("/explain", response_model=ExplainResponse)
def explain_conflict(request: ExplainRequest):
    """
    Returns a Granite-generated explanation based on conflict evidence.
    Connected to Person 3's explain.py module.
    """
    visibility_data = obtain_visibility_data()
    mission_data = load_scenario(request.scenario_id)
    scheduling_run = run_scheduling(visibility_data, mission_data)

    try:
        explanation = explain_request_conflict(
            scheduling_run.conflict_evidence,
            request.request_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return ExplainResponse(
        request_id=request.request_id,
        explanation=explanation,
    )

@router.post("/what-if", response_model=WhatIfResponse)
def what_if_scenario(request: WhatIfRequest):
    """
    Orchestrates the entire AI intent -> modification -> solver -> comparison flow.
    """
    return process_what_if_query(request)
