"""P4 orchestration for P1 visibility and P2 deterministic scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from backend.api.visibility_adapter import adapt_visibility_for_scheduler
from backend.solver.conflicts import build_conflict_evidence
from backend.solver.scheduler import solve_schedule


@dataclass(frozen=True)
class SchedulingRun:
    schedule_result: dict
    conflict_evidence: dict


def obtain_visibility_data(horizon_hours: int = 48) -> dict:
    """Generate P1 windows and adapt them into P2's visibility structure."""
    # Keep Skyfield/CelesTrak dependencies out of API module import paths. They
    # are needed only when P4 actually requests fresh operational visibility.
    from backend.data.ground_stations import load_ground_stations
    from backend.data.passes import generate_all_visibility_windows

    planning_start = datetime.now(timezone.utc)
    planning_end = planning_start + timedelta(hours=horizon_hours)
    windows = generate_all_visibility_windows(horizon_hours=horizon_hours)
    stations = load_ground_stations()

    return adapt_visibility_for_scheduler(
        windows,
        planning_start=planning_start,
        planning_end=planning_end,
        minimum_elevation_deg=min(
            station.min_elevation_deg for station in stations
        ),
    )


def run_scheduling(visibility_data: dict, mission_data: dict) -> SchedulingRun:
    """Run P2 scheduling and conflict calculation for P4-owned inputs."""
    schedule_result = solve_schedule(visibility_data, mission_data)
    conflict_evidence = build_conflict_evidence(
        visibility_data,
        mission_data,
        schedule_result,
    )
    return SchedulingRun(
        schedule_result=schedule_result,
        conflict_evidence=conflict_evidence,
    )
