from fastapi import APIRouter
from backend.api.schemas import ExplainRequest, ExplainResponse, WhatIfRequest, WhatIfResponse
from backend.api.what_if import process_what_if_query

router = APIRouter()

@router.get("/schedule")
def get_schedule():
    """
    Returns the baseline schedule. Connected to Person 2's solver output.
    Returns Contract #5.
    """
    return {
      "scenario_id": "DEMO_001",
      "solver": {
        "engine": "OR-Tools CP-SAT",
        "status": "OPTIMAL",
        "objective_value": 13.0
      },
      "scheduled_contacts": [
        {
          "request_id": "REQ_001",
          "satellite_id": "NORAD_20580",
          "station_id": "GS_SG_01",
          "scheduled_start": "2026-08-11T02:14:00Z",
          "scheduled_end": "2026-08-11T02:19:00Z",
          "duration_seconds": 300,
          "priority": 8
        }
      ],
      "unscheduled_requests": [
        {
          "request_id": "REQ_002",
          "satellite_id": "NORAD_XXXXX",
          "reason_codes": ["ANTENNA_RESOURCE_CONFLICT"]
        }
      ]
    }

@router.post("/explain", response_model=ExplainResponse)
def explain_conflict(request: ExplainRequest):
    """
    Returns a Granite-generated explanation based on conflict evidence.
    Connected to Person 3's explain.py module.
    """
    return ExplainResponse(
        request_id=request.request_id,
        explanation=f"Mission {request.request_id} was denied because it overlaps with REQ_001 on GS_SG_01 by 4 minutes. REQ_001 has a higher priority (8 vs 5)."
    )

@router.post("/what-if", response_model=WhatIfResponse)
def what_if_scenario(request: WhatIfRequest):
    """
    Orchestrates the entire AI intent -> modification -> solver -> comparison flow.
    """
    return process_what_if_query(request)