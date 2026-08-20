"""
backend/api/scenario.py

Loads the base mission scenario and applies what-if mutations to a
temporary copy before handing it to the solver.

load_scenario()                 reads data/mission_requests.json by scenario_id.
apply_operations_to_scenario()  applies all four contracted mutations.
"""

import copy
import json
from pathlib import Path
from typing import Any, Dict, List

from backend.api.schemas import IntentOperation

REPO_ROOT = Path(__file__).resolve().parents[2]
MISSION_REQUESTS_PATH = REPO_ROOT / "data" / "mission_requests.json"


def load_scenario(scenario_id: str) -> Dict[str, Any]:
<<<<<<< Updated upstream
    # TODO: In production, load from a database or shared file.
    # For now, return complete requests suitable for deterministic scheduling.
=======
    """
    Load the mission scenario for scenario_id from data/mission_requests.json.

    Falls back to a minimal in-memory stub only when the file is missing,
    so development can continue without the data file.  In both cases the
    returned dict is a deep copy, safe to mutate.

    Expected file shape (contract #4):
        { "scenario_id": "DEMO_001", "requests": [ { ... }, ... ] }
    """
    if MISSION_REQUESTS_PATH.exists():
        with open(MISSION_REQUESTS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("requests"):
            return copy.deepcopy(data)

    # Fallback — keeps /what-if alive on machines without the data file.
>>>>>>> Stashed changes
    return {
        "scenario_id": scenario_id,
        "requests": [
            {
                "request_id": "REQ_001",
                "satellite_id": "NORAD_25544",
                "required_contact_seconds": 300,
                "priority": 8,
<<<<<<< Updated upstream
                "eligible_station_ids": ["GS-SG", "GS-PERTH"],
=======
                "eligible_station_ids": ["GS_SG_01", "GS_PERTH_01"],
>>>>>>> Stashed changes
                "mandatory": False,
            },
            {
                "request_id": "REQ_002",
                "satellite_id": "NORAD_48274",
                "required_contact_seconds": 300,
                "priority": 5,
<<<<<<< Updated upstream
                "eligible_station_ids": ["GS-SG", "GS-PERTH"],
                "mandatory": False,
            },
        ]
=======
                "eligible_station_ids": ["GS_SG_01", "GS_PERTH_01"],
                "mandatory": False,
            },
        ],
>>>>>>> Stashed changes
    }


def apply_operations_to_scenario(
    base_scenario: Dict[str, Any],
    operations: List[IntentOperation],
) -> Dict[str, Any]:
    """
    Apply what-if mutations to a deep copy of base_scenario.

    Supported operations (contract #7):

    SET_PRIORITY
        Sets request["priority"] = op.value for the matching request_id.

    SET_REQUIRED_DURATION
        Sets request["required_contact_seconds"] = op.value (seconds) for
        the matching request_id.

    DISABLE_STATION
        Removes op.station_id from every request's eligible_station_ids list.
        Requests that end up with no eligible stations are left in place —
        the solver will classify them as unschedulable.

    SET_ELIGIBLE_STATIONS
        Replaces eligible_station_ids for the matching request_id with
        op.station_ids.

    Unknown operations are silently skipped (logged at WARNING level).
    """
    import logging
    log = logging.getLogger(__name__)

    temp = copy.deepcopy(base_scenario)

    for op in operations:
        if op.operation == "SET_PRIORITY":
            for req in temp["requests"]:
                if req["request_id"] == op.request_id:
                    req["priority"] = op.value
<<<<<<< Updated upstream
                    
        # Add more operations as Person 3 supports them (DISABLE_STATION, SET_ELIGIBLE_STATIONS, etc.)
        
    return temp_scenario
=======

        elif op.operation == "SET_REQUIRED_DURATION":
            for req in temp["requests"]:
                if req["request_id"] == op.request_id:
                    req["required_contact_seconds"] = op.value

        elif op.operation == "DISABLE_STATION":
            for req in temp["requests"]:
                req["eligible_station_ids"] = [
                    s for s in req.get("eligible_station_ids", [])
                    if s != op.station_id
                ]

        elif op.operation == "SET_ELIGIBLE_STATIONS":
            for req in temp["requests"]:
                if req["request_id"] == op.request_id:
                    req["eligible_station_ids"] = list(op.station_ids or [])

        else:
            log.warning("apply_operations_to_scenario: unknown operation %r — skipped.", op.operation)

    return temp
>>>>>>> Stashed changes
