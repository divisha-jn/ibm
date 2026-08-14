from typing import Dict, Any
from backend.api.schemas import WhatIfImpact

def compare_schedules(old_schedule: Dict[str, Any], new_schedule: Dict[str, Any]) -> WhatIfImpact:
    """
    Compares two schedule outputs to determine the impact of a What-If change.
    """
    # Extract sets of scheduled request IDs
    old_scheduled = {contact["request_id"] for contact in old_schedule.get("scheduled_contacts", [])}
    new_scheduled = {contact["request_id"] for contact in new_schedule.get("scheduled_contacts", [])}
    
    # Calculate the diff
    newly_scheduled = list(new_scheduled - old_scheduled)
    newly_unscheduled = list(old_scheduled - new_scheduled)
    unchanged = list(old_scheduled.intersection(new_scheduled))
    
    return WhatIfImpact(
        newly_scheduled=newly_scheduled,
        newly_unscheduled=newly_unscheduled,
        unchanged=unchanged
    )