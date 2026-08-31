import json
import sys
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.ai import granite
from backend.ai.explain import explain_conflict as p3_explain_conflict
from backend.api import data_pipeline
from backend.api.visibility_adapter import adapt_visibility_for_scheduler
from backend.data import ground_stations, passes
from backend.data.ground_stations import GroundStation
from backend.data.passes import VisibilityWindow
from backend.main import app
from backend.solver.conflicts import build_conflict_evidence
from backend.solver.scheduler import solve_schedule


def _iso_z(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


class RecordingGraniteClient:
    def __init__(self, response: str):
        self.response = response
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return self.response


def test_live_explain_selects_target_from_real_p2_evidence(monkeypatch, tmp_path):
    window_start = (
        datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=1)
    )
    window_end = window_start + timedelta(minutes=15)
    station_id = "GS_E2E_EXPLAIN_SHARED"
    winner_request_id = "REQ_E2E_EXPLAIN_WINNER"
    target_request_id = "REQ_E2E_EXPLAIN_TARGET"
    unrelated_request_id = "REQ_E2E_EXPLAIN_OTHER"

    p1_windows = [
        VisibilityWindow(
            window_id="VW_E2E_EXPLAIN_WINNER",
            satellite_id="NORAD_91001",
            satellite="E2E EXPLAIN WINNER",
            station_id=station_id,
            aos=_iso_z(window_start),
            los=_iso_z(window_end),
            duration_seconds=900,
            max_elevation_deg=45.0,
            source={"orbit_provider": "E2E deterministic fixture"},
        ),
        VisibilityWindow(
            window_id="VW_E2E_EXPLAIN_TARGET",
            satellite_id="NORAD_91002",
            satellite="E2E EXPLAIN TARGET",
            station_id=station_id,
            aos=_iso_z(window_start),
            los=_iso_z(window_end),
            duration_seconds=900,
            max_elevation_deg=40.0,
            source={"orbit_provider": "E2E deterministic fixture"},
        ),
        VisibilityWindow(
            window_id="VW_E2E_EXPLAIN_OTHER",
            satellite_id="NORAD_91003",
            satellite="E2E EXPLAIN OTHER",
            station_id=station_id,
            aos=_iso_z(window_start),
            los=_iso_z(window_end),
            duration_seconds=900,
            max_elevation_deg=35.0,
            source={"orbit_provider": "E2E deterministic fixture"},
        ),
    ]
    mission_data = {
        "scenario_id": "E2E_LIVE_EXPLAIN_P1_P2_P3",
        "requests": [
            {
                "request_id": winner_request_id,
                "satellite_id": "NORAD_91001",
                "required_contact_seconds": 900,
                "priority": 9,
                "eligible_station_ids": [station_id],
                "mandatory": False,
            },
            {
                "request_id": target_request_id,
                "satellite_id": "NORAD_91002",
                "required_contact_seconds": 900,
                "priority": 5,
                "eligible_station_ids": [station_id],
                "mandatory": False,
            },
            {
                "request_id": unrelated_request_id,
                "satellite_id": "NORAD_91003",
                "required_contact_seconds": 900,
                "priority": 4,
                "eligible_station_ids": [station_id],
                "mandatory": False,
            },
        ],
    }
    station = GroundStation(
        id=station_id,
        name="E2E Explain Shared Ground Station",
        latitude=1.3521,
        longitude=103.8198,
        elevation_m=15.0,
        min_elevation_deg=10.0,
    )
    cache_path = tmp_path / "visibility_windows_scheduler.json"
    ai_response = (
        f"{target_request_id} lost the {station_id} contact to "
        f"{winner_request_id}."
    )
    external_client = RecordingGraniteClient(ai_response)

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
    monkeypatch.setattr(granite, "GraniteClient", lambda: external_client)

    observed_real_calls = Counter()
    target_code_objects = {
        adapt_visibility_for_scheduler.__code__: "adapt_visibility_for_scheduler",
        solve_schedule.__code__: "solve_schedule",
        build_conflict_evidence.__code__: "build_conflict_evidence",
        p3_explain_conflict.__code__: "p3_explain_conflict",
    }

    def record_real_calls(frame, event, arg):
        if event == "call" and frame.f_code in target_code_objects:
            observed_real_calls[target_code_objects[frame.f_code]] += 1

    previous_sys_profile = sys.getprofile()
    previous_thread_profile = threading.getprofile()
    sys.setprofile(record_real_calls)
    threading.setprofile(record_real_calls)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/explain",
                json={
                    "scenario_id": mission_data["scenario_id"],
                    "request_id": target_request_id,
                },
            )
    finally:
        sys.setprofile(previous_sys_profile)
        threading.setprofile(previous_thread_profile)

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "request_id": target_request_id,
        "explanation": ai_response,
        "clarification_question": None,
        "evidence": {
            "reason_codes": ["ANTENNA_RESOURCE_CONFLICT"],
            "conflicts": [
                {
                    "conflicting_request_id": winner_request_id,
                    "station_id": station_id,
                    "overlap_seconds": 900,
                    "request_priority": 5,
                    "conflicting_request_priority": 9,
                }
            ],
            "feasibility": {"requested_contact_seconds": 900},
            "alternative_window_ids": [],
        },
    }

    assert observed_real_calls["adapt_visibility_for_scheduler"] == 1
    assert observed_real_calls["solve_schedule"] == 1
    assert observed_real_calls["build_conflict_evidence"] == 2
    assert observed_real_calls["p3_explain_conflict"] == 1

    assert len(external_client.calls) == 1
    ai_call = external_client.calls[0]
    assert ai_call["kwargs"] == {
        "max_completion_tokens": 300,
        "temperature": 0.0,
    }
    user_content = ai_call["messages"][1]["content"]
    supplied_evidence = json.loads(
        user_content[user_content.index("{"):]
    )
    assert supplied_evidence["scenario_id"] == mission_data["scenario_id"]
    assert len(supplied_evidence["evidence"]) == 1
    record = supplied_evidence["evidence"][0]
    assert record == {
        "request_id": target_request_id,
        "status": "UNSCHEDULED",
        "reason_codes": ["ANTENNA_RESOURCE_CONFLICT"],
        "conflicts": [
            {
                "conflicting_request_id": winner_request_id,
                "station_id": station_id,
                "overlap_start": _iso_z(window_start),
                "overlap_end": _iso_z(window_end),
                "overlap_seconds": 900,
                "request_priority": 5,
                "conflicting_request_priority": 9,
            }
        ],
        "feasibility": {"requested_contact_seconds": 900},
        "alternative_window_ids": [],
    }
    assert unrelated_request_id not in json.dumps(supplied_evidence)
    assert "available_unconflicted_seconds" not in json.dumps(supplied_evidence)

    canonical_cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert {
        window["window_id"] for window in canonical_cache["visibility_windows"]
    } == {
        "VW_E2E_EXPLAIN_WINNER",
        "VW_E2E_EXPLAIN_TARGET",
        "VW_E2E_EXPLAIN_OTHER",
    }
