import json
from types import SimpleNamespace
from unittest.mock import patch

from backend.api import data_pipeline, routes
from backend.api.routes import get_schedule
from backend.api.schemas import ScheduleResult
from backend.data import ground_stations, passes
from backend.data.demo_scenarios import antenna_conflict_scenario
from backend.data.passes import VisibilityWindow
from backend.solver.conflicts import build_conflict_evidence
from backend.solver.scheduler import solve_schedule


def _p1_window() -> VisibilityWindow:
    return VisibilityWindow(
        window_id="VW_LIVE_0001",
        satellite_id="NORAD_25544",
        satellite="ISS (ZARYA)",
        station_id="GS_SG_01",
        aos="2026-08-24T10:12:00Z",
        los="2026-08-24T10:22:00Z",
        duration_seconds=600,
        max_elevation_deg=37.0,
        source={"orbit_provider": "CelesTrak"},
    )


def _configure_live_visibility(monkeypatch, tmp_path):
    monkeypatch.setattr(
        data_pipeline,
        "VISIBILITY_CACHE_PATH",
        tmp_path / "visibility_windows_scheduler.json",
    )
    monkeypatch.setattr(
        passes,
        "generate_all_visibility_windows",
        lambda horizon_hours: [_p1_window()],
    )
    monkeypatch.setattr(
        ground_stations,
        "load_ground_stations",
        lambda: [SimpleNamespace(min_elevation_deg=10.0)],
    )


def _station_conflict_inputs():
    # Single source of truth: backend/data/demo_scenarios.py. The live-API
    # seed script (`python -m backend.data.demo_scenarios`) reuses the exact
    # same data so the two can't drift apart.
    return antenna_conflict_scenario()


def test_incompatible_legacy_cache_is_regenerated_as_canonical(monkeypatch, tmp_path):
    _configure_live_visibility(monkeypatch, tmp_path)
    legacy_cache = {
        "planning_horizon": {
            "start": "2026-08-24T00:00:00Z",
            "end": "2026-08-26T00:00:00Z",
        },
        "minimum_elevation_deg": 10.0,
        "visibility_windows": [
            {
                "satellite": "ISS (ZARYA)",
                "station": "GS_SG_01",
                "visibility_start": "2026-08-24T10:12:00Z",
                "visibility_end": "2026-08-24T10:22:00Z",
                "duration_seconds": 600,
                "max_elevation_deg": 37.0,
            }
        ],
    }
    data_pipeline.VISIBILITY_CACHE_PATH.write_text(
        json.dumps(legacy_cache), encoding="utf-8"
    )

    visibility_data = data_pipeline._get_visibility_data()

    adapted_window = visibility_data["visibility_windows"][0]
    assert adapted_window == {
        "window_id": "VW_LIVE_0001",
        "satellite_id": "NORAD_25544",
        "station_id": "GS_SG_01",
        "aos": "2026-08-24T10:12:00Z",
        "los": "2026-08-24T10:22:00Z",
        "duration_seconds": 600,
        "max_elevation_deg": 37.0,
    }
    assert json.loads(
        data_pipeline.VISIBILITY_CACHE_PATH.read_text(encoding="utf-8")
    ) == visibility_data


def test_fresh_canonical_cache_is_reused(monkeypatch, tmp_path):
    cache_path = tmp_path / "visibility_windows_scheduler.json"
    canonical_cache = {
        "planning_horizon": {
            "start": "2026-08-24T00:00:00Z",
            "end": "2026-08-26T00:00:00Z",
        },
        "minimum_elevation_deg": 10.0,
        "visibility_windows": [
            {
                "window_id": "VW_CACHED_0001",
                "satellite_id": "NORAD_25544",
                "station_id": "GS_SG_01",
                "aos": "2026-08-24T10:12:00Z",
                "los": "2026-08-24T10:22:00Z",
                "duration_seconds": 600,
                "max_elevation_deg": 37.0,
            }
        ],
    }
    cache_path.write_text(json.dumps(canonical_cache), encoding="utf-8")
    monkeypatch.setattr(data_pipeline, "VISIBILITY_CACHE_PATH", cache_path)

    def fail_if_generated(*args, **kwargs):
        raise AssertionError("fresh canonical cache should be reused")

    monkeypatch.setattr(
        passes, "generate_all_visibility_windows", fail_if_generated
    )

    assert data_pipeline._get_visibility_data() == canonical_cache


def test_schedule_route_reaches_real_solver_with_adapted_p1_windows(
    monkeypatch, tmp_path
):
    _configure_live_visibility(monkeypatch, tmp_path)
    monkeypatch.setattr(data_pipeline, "_ortools_available", lambda: True)
    monkeypatch.setattr(
        data_pipeline,
        "_load_mission_requests",
        lambda: {
            "scenario_id": "LIVE_P1_P2_P4",
            "requests": [
                {
                    "request_id": "REQ_LIVE_PIPELINE",
                    "satellite_id": "NORAD_25544",
                    "required_contact_seconds": 600,
                    "priority": 9,
                    "eligible_station_ids": ["GS_SG_01"],
                    "mandatory": False,
                }
            ],
        },
    )

    with patch(
        "backend.solver.scheduler.solve_schedule", wraps=solve_schedule
    ) as real_solver:
        result = get_schedule()

    real_solver.assert_called_once()
    assert result["scenario_id"] == "LIVE_P1_P2_P4"
    assert result["unscheduled_requests"] == []
    assert result["scheduled_contacts"] == [
        {
            "request_id": "REQ_LIVE_PIPELINE",
            "satellite_id": "NORAD_25544",
            "station_id": "GS_SG_01",
            "antenna_id": "GS_SG_01_A1",
            "window_id": "VW_LIVE_0001",
            "scheduled_start": "2026-08-24T10:12:00Z",
            "scheduled_end": "2026-08-24T10:22:00Z",
            "duration_seconds": 600,
            "priority": 9,
        }
    ]


def test_schedule_enriches_station_conflict_from_same_p2_inputs(monkeypatch):
    visibility_data, mission_data = _station_conflict_inputs()
    captured = {}

    monkeypatch.setattr(data_pipeline, "_ortools_available", lambda: True)
    monkeypatch.setattr(
        data_pipeline, "_get_visibility_data", lambda: visibility_data
    )
    monkeypatch.setattr(
        data_pipeline, "_load_mission_requests", lambda: mission_data
    )

    def capture_evidence(supplied_visibility, supplied_missions, schedule_result):
        captured["visibility_data"] = supplied_visibility
        captured["mission_data"] = supplied_missions
        captured["schedule_result"] = schedule_result
        captured["evidence"] = build_conflict_evidence(
            supplied_visibility,
            supplied_missions,
            schedule_result,
        )
        return captured["evidence"]

    with patch(
        "backend.solver.scheduler.solve_schedule", wraps=solve_schedule
    ) as real_solver, patch(
        "backend.solver.conflicts.build_conflict_evidence",
        side_effect=capture_evidence,
    ) as real_evidence:
        result = get_schedule()

    real_solver.assert_called_once_with(visibility_data, mission_data)
    real_evidence.assert_called_once()
    assert captured["visibility_data"] is visibility_data
    assert captured["mission_data"] is mission_data
    assert captured["schedule_result"] is result

    public_result = ScheduleResult.model_validate(result).model_dump()
    assert public_result["unscheduled_requests"] == [
        {
            "request_id": "REQ_LOW_PRIORITY",
            "satellite_id": "NORAD_48274",
            "reason_codes": ["ANTENNA_RESOURCE_CONFLICT"],
            "conflicts": [
                {
                    "conflicting_request_id": "REQ_HIGH_PRIORITY",
                    "station_id": "GS_SG_01",
                    "overlap_seconds": 900,
                    "request_priority": 5,
                    "conflicting_request_priority": 9,
                }
            ],
        }
    ]
    assert public_result["unscheduled_requests"][0]["reason_codes"] != [
        "UNSCHEDULED"
    ]

    evidence_record = captured["evidence"]["evidence"][0]
    assert evidence_record["request_id"] == "REQ_LOW_PRIORITY"
    assert evidence_record["conflicts"][0]["conflicting_request_id"] == (
        "REQ_HIGH_PRIORITY"
    )
    assert evidence_record["conflicts"][0]["station_id"] == "GS_SG_01"
    assert evidence_record["conflicts"][0]["overlap_seconds"] == 900
    assert evidence_record["conflicts"][0]["request_priority"] == 5
    assert evidence_record["conflicts"][0]["conflicting_request_priority"] == 9


def test_missing_p2_evidence_does_not_return_generic_live_result(monkeypatch):
    visibility_data, mission_data = _station_conflict_inputs()
    monkeypatch.setattr(data_pipeline, "_ortools_available", lambda: True)
    monkeypatch.setattr(
        data_pipeline, "_get_visibility_data", lambda: visibility_data
    )
    monkeypatch.setattr(
        data_pipeline, "_load_mission_requests", lambda: mission_data
    )

    with patch(
        "backend.solver.conflicts.build_conflict_evidence",
        return_value={
            "scenario_id": mission_data["scenario_id"],
            "evidence": [],
        },
    ):
        assert data_pipeline.build_live_schedule() is None

    monkeypatch.setattr(routes, "build_live_schedule", lambda: None)
    assert get_schedule() is routes._STUB_SCHEDULE
