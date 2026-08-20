import copy
from typing import Dict, Any, List
from backend.api.schemas import IntentOperation

def load_scenario(scenario_id: str) -> Dict[str, Any]:
    # TODO: In production, load from a database or shared file.
    # For now, return complete requests suitable for deterministic scheduling.
    return {
        "scenario_id": scenario_id,
        "requests": [
            {
                "request_id": "REQ_001",
                "satellite_id": "NORAD_25544",
                "required_contact_seconds": 300,
                "priority": 8,
                "eligible_station_ids": ["GS-SG", "GS-PERTH"],
                "mandatory": False,
            },
            {
                "request_id": "REQ_002",
                "satellite_id": "NORAD_48274",
                "required_contact_seconds": 300,
                "priority": 5,
                "eligible_station_ids": ["GS-SG", "GS-PERTH"],
                "mandatory": False,
            },
        ]
    }

def apply_operations_to_scenario(base_scenario: Dict[str, Any], operations: List[IntentOperation]) -> Dict[str, Any]:
    """
    Creates a temporary sandbox scenario and applies the what-if modifications.
    """
    temp_scenario = copy.deepcopy(base_scenario)
    
    for op in operations:
        if op.operation == "SET_PRIORITY":
            for req in temp_scenario["requests"]:
                if req["request_id"] == op.request_id:
                    req["priority"] = op.value
                    
        # Add more operations as Person 3 supports them (DISABLE_STATION, SET_ELIGIBLE_STATIONS, etc.)
        
    return temp_scenario
