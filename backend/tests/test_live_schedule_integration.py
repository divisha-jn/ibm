import json
import sys
import threading
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.api import data_pipeline
from backend.api.visibility_adapter import adapt_visibility_for_scheduler
from backend.data import ground_stations, passes
from backend.data.ground_stations import GroundStation
from backend.data.passes import VisibilityWindow
from backend.main import app
from backend.solver.conflicts import build_conflict_evidence
from backend.solver.scheduler import solve_schedule


REQUIRED_SCHEDULER_WINDOW_FIELDS = {
    "window_id",
    "satellite_id",
    "station_id",
    "aos",
    "los",
    "duration_seconds",
    "max_elevation_deg",
}


def _iso_z(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def test_live_p1_p2_p4_schedule_endpoint(monkeypatch, tmp_path):
    window_start = (
        datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=1)
    )
    window_end = window_start + timedelta(minutes=15)
    station_id = "GS_E2E_SHARED_RESOURCE"
    high_window_id = "VW_E2E_HIGH_PRIORITY"
    low_window_id = "VW_E2E_LOW_PRIORITY"
    high_request_id = "REQ_E2E_HIGH_PRIORITY"
    low_request_id = "REQ_E2E_LOW_PRIORITY"

    p1_windows = [
        VisibilityWindow(
            window_id=high_window_id,
            satellite_id="NORAD_90001",
            satellite="E2E HIGH PRIORITY SATELLITE",
            station_id=station_id,
            aos=_iso_z(window_start),
            los=_iso_z(window_end),
            duration_seconds=900,
            max_elevation_deg=42.0,
            source={"orbit_provider": "E2E deterministic fixture"},
        ),
        VisibilityWindow(
            window_id=low_window_id,
            satellite_id="NORAD_90002",
            satellite="E2E LOW PRIORITY SATELLITE",
            station_id=station_id,
            aos=_iso_z(window_start),
            los=_iso_z(window_end),
            duration_seconds=900,
            max_elevation_deg=38.0,
            source={"orbit_provider": "E2E deterministic fixture"},
        ),
    ]
    mission_data = {
        "scenario_id": "E2E_LIVE_P1_P2",
        "requests": [
            {
                "request_id": high_request_id,
                "satellite_id": "NORAD_90001",
                "required_contact_seconds": 900,
                "priority": 9,
                "eligible_station_ids": [station_id],
                "mandatory": False,
            },
            {
                "request_id": low_request_id,
                "satellite_id": "NORAD_90002",
                "required_contact_seconds": 900,
                "priority": 5,
                "eligible_station_ids": [station_id],
                "mandatory": False,
            },
        ],
    }
    station = GroundStation(
        id=station_id,
        name="E2E Shared Ground Station",
        latitude=1.3521,
        longitude=103.8198,
        elevation_m=15.0,
        min_elevation_deg=10.0,
    )
    cache_path = tmp_path / "visibility_windows_scheduler.json"

    monkeypatch.setattr(data_pipeline, "VISIBILITY_CACHE_PATH", cache_path)
    monkeypatch.setattr(
        data_pipeline, "_load_mission_requests", lambda: mission_data
    )
    monkeypatch.setattr(
        passes,
        "generate_all_visibility_windows",
        lambda horizon_hours: p1_windows,
    )
    monkeypatch.setattr(
        ground_stations, "load_ground_stations", lambda: [station]
    )

    observed_real_calls = set()
    target_code_objects = {
        adapt_visibility_for_scheduler.__code__: "adapt_visibility_for_scheduler",
        solve_schedule.__code__: "solve_schedule",
        build_conflict_evidence.__code__: "build_conflict_evidence",
    }

    def record_real_calls(frame, event, arg):
        if event == "call" and frame.f_code in target_code_objects:
            observed_real_calls.add(target_code_objects[frame.f_code])

    previous_sys_profile = sys.getprofile()
    previous_thread_profile = threading.getprofile()
    sys.setprofile(record_real_calls)
    threading.setprofile(record_real_calls)
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/schedule")
    finally:
        sys.setprofile(previous_sys_profile)
        threading.setprofile(previous_thread_profile)

    assert response.status_code == 200
    payload = response.json()
    assert payload["scenario_id"] == "E2E_LIVE_P1_P2"
    assert payload["scenario_id"] != "DEMO_001"

    assert payload["scheduled_contacts"] == [
        {
            "request_id": high_request_id,
            "satellite_id": "NORAD_90001",
            "station_id": station_id,
            "antenna_id": f"{station_id}_A1",
            "window_id": high_window_id,
            "scheduled_start": _iso_z(window_start),
            "scheduled_end": _iso_z(window_end),
            "duration_seconds": 900,
            "priority": 9,
        }
    ]
    assert payload["unscheduled_requests"] == [
        {
            "request_id": low_request_id,
            "satellite_id": "NORAD_90002",
            "reason_codes": ["ANTENNA_RESOURCE_CONFLICT"],
            "conflicts": [
                {
                    "conflicting_request_id": high_request_id,
                    "station_id": station_id,
                    "overlap_seconds": 900,
                    "request_priority": 5,
                    "conflicting_request_priority": 9,
                }
            ],
        }
    ]
    assert payload["unscheduled_requests"][0]["reason_codes"] != ["UNSCHEDULED"]

    assert observed_real_calls == {
        "adapt_visibility_for_scheduler",
        "solve_schedule",
        "build_conflict_evidence",
    }

    canonical_cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert len(canonical_cache["visibility_windows"]) == 2
    assert all(
        set(window) == REQUIRED_SCHEDULER_WINDOW_FIELDS
        for window in canonical_cache["visibility_windows"]
    )
    assert {
        window["window_id"] for window in canonical_cache["visibility_windows"]
    } == {high_window_id, low_window_id}
    assert {
        window["satellite_id"] for window in canonical_cache["visibility_windows"]
    } == {"NORAD_90001", "NORAD_90002"}
