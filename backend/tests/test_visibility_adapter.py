from types import SimpleNamespace

from backend.api.visibility_adapter import adapt_visibility_for_scheduler
from backend.solver.scheduler import solve_schedule


def test_p1_visibility_adapts_and_schedules_matching_mission():
    p1_window = SimpleNamespace(
        satellite_id="NORAD_25544",
        satellite="ISS (ZARYA)",
        station="GS-SG",
        visibility_start="2026-08-20T10:12:00Z",
        visibility_end="2026-08-20T10:22:00Z",
        max_elevation_deg=37.0,
        duration_seconds=600,
    )

    visibility_data = adapt_visibility_for_scheduler(
        [p1_window],
        planning_start="2026-08-20T00:00:00Z",
        planning_end="2026-08-21T00:00:00Z",
        minimum_elevation_deg=10.0,
    )
    repeated = adapt_visibility_for_scheduler(
        [p1_window],
        planning_start="2026-08-20T00:00:00Z",
        planning_end="2026-08-21T00:00:00Z",
        minimum_elevation_deg=10.0,
    )

    assert (
        visibility_data["visibility_windows"][0]["window_id"]
        == repeated["visibility_windows"][0]["window_id"]
    )

    mission_data = {
        "scenario_id": "P1_TO_P2_INTEGRATION",
        "requests": [
            {
                "request_id": "REQ_ISS_DOWNLINK",
                "satellite_id": "NORAD_25544",
                "required_contact_seconds": 600,
                "priority": 9,
                "eligible_station_ids": ["GS-SG"],
                "mandatory": False,
            }
        ],
    }

    result = solve_schedule(visibility_data, mission_data)

    assert result["unscheduled_requests"] == []
    assert result["scheduled_contacts"][0]["request_id"] == "REQ_ISS_DOWNLINK"
    assert result["scheduled_contacts"][0]["satellite_id"] == "NORAD_25544"
    assert result["scheduled_contacts"][0]["station_id"] == "GS-SG"
