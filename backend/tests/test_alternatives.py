import copy
from datetime import datetime

import pytest

from backend.data.demo_scenarios import ranked_alternatives_scenario
from backend.solver.alternatives import (
    ALTERNATIVES_FOUND,
    NO_FEASIBLE_ALTERNATIVES,
    REQUEST_ALREADY_SCHEDULED,
    AlternativesValidationError,
    rank_alternatives,
)
from backend.solver.conflicts import build_conflict_evidence
from backend.solver.scheduler import solve_schedule


SCENARIO_ID = "P2_ALTERNATIVES_TEST"
TARGET_ID = "REQ_ALT_TARGET"
TARGET_SATELLITE_ID = "NORAD_20002"


def _window(
    window_id,
    satellite_id,
    station_id,
    aos,
    los,
    *,
    max_elevation_deg=40.0,
):
    start = datetime.fromisoformat(aos.replace("Z", "+00:00"))
    end = datetime.fromisoformat(los.replace("Z", "+00:00"))
    return {
        "window_id": window_id,
        "satellite_id": satellite_id,
        "station_id": station_id,
        "aos": aos,
        "los": los,
        "duration_seconds": int((end - start).total_seconds()),
        "max_elevation_deg": max_elevation_deg,
    }


def _request(
    request_id,
    satellite_id,
    priority,
    eligible_station_ids,
    *,
    required_contact_seconds=900,
):
    return {
        "request_id": request_id,
        "satellite_id": satellite_id,
        "required_contact_seconds": required_contact_seconds,
        "priority": priority,
        "eligible_station_ids": eligible_station_ids,
        "mandatory": False,
    }


def _visibility(windows):
    return {
        "planning_horizon": {
            "start": "2026-08-24T00:00:00Z",
            "end": "2026-08-25T00:00:00Z",
        },
        "minimum_elevation_deg": 10.0,
        "visibility_windows": windows,
    }


def _mission(requests):
    return {"scenario_id": SCENARIO_ID, "requests": requests}


def _manual_unscheduled_baseline(contacts=None):
    return {
        "scenario_id": SCENARIO_ID,
        "solver": {
            "engine": "OR-Tools CP-SAT",
            "status": "OPTIMAL",
            "objective_value": 0.0,
        },
        "scheduled_contacts": list(contacts or []),
        "unscheduled_requests": [
            {
                "request_id": TARGET_ID,
                "satellite_id": TARGET_SATELLITE_ID,
                "priority": 5,
            }
        ],
    }


def _evidence(alternative_window_ids=None):
    return {
        "scenario_id": SCENARIO_ID,
        "evidence": [
            {
                "request_id": TARGET_ID,
                "status": "UNSCHEDULED",
                "reason_codes": ["ANTENNA_RESOURCE_CONFLICT"],
                "conflicts": [],
                "feasibility": {"requested_contact_seconds": 900},
                "alternative_window_ids": list(alternative_window_ids or []),
            }
        ],
    }


def _target_only_inputs(windows):
    visibility_data = _visibility(windows)
    mission_data = _mission([
        _request(
            TARGET_ID,
            TARGET_SATELLITE_ID,
            5,
            ["GS_1", "GS_2"],
        )
    ])
    return (
        visibility_data,
        mission_data,
        _manual_unscheduled_baseline(),
        _evidence(),
    )


def _rank(inputs, **kwargs):
    return rank_alternatives(*inputs, TARGET_ID, **kwargs)


def test_real_window_schedules_target_without_displacement():
    window = _window(
        "VW_ALT_REAL",
        TARGET_SATELLITE_ID,
        "GS_1",
        "2026-08-24T10:00:00Z",
        "2026-08-24T10:15:00Z",
    )

    result = _rank(_target_only_inputs([window]))

    assert result["status"] == ALTERNATIVES_FOUND
    assert result["alternatives"] == [
        {
            "rank": 1,
            "alternative_type": "ALTERNATIVE_WINDOW",
            "window_id": "VW_ALT_REAL",
            "station_id": "GS_1",
            "scheduled_start": "2026-08-24T10:00:00Z",
            "scheduled_end": "2026-08-24T10:15:00Z",
            "duration_seconds": 900,
            "displaced_request_ids": [],
            "rescheduled_request_ids": [],
            "ranking_metrics": {
                "displaced_count": 0,
                "displaced_priority_total": 0,
                "rescheduled_count": 0,
                "rescheduled_priority_total": 0,
            },
        }
    ]


def test_real_window_at_different_eligible_station_is_returned():
    window = _window(
        "VW_ALT_OTHER_STATION",
        TARGET_SATELLITE_ID,
        "GS_2",
        "2026-08-24T11:00:00Z",
        "2026-08-24T11:15:00Z",
    )

    result = _rank(_target_only_inputs([window]))

    assert result["alternatives"][0]["station_id"] == "GS_2"
    assert result["alternatives"][0]["window_id"] == "VW_ALT_OTHER_STATION"


def test_multiple_alternatives_rank_deterministically_and_respect_limit():
    windows = [
        _window(
            "VW_LATE",
            TARGET_SATELLITE_ID,
            "GS_1",
            "2026-08-24T12:00:00Z",
            "2026-08-24T12:15:00Z",
        ),
        _window(
            "VW_EARLY_GS2",
            TARGET_SATELLITE_ID,
            "GS_2",
            "2026-08-24T10:00:00Z",
            "2026-08-24T10:15:00Z",
        ),
        _window(
            "VW_EARLY_GS1",
            TARGET_SATELLITE_ID,
            "GS_1",
            "2026-08-24T10:00:00Z",
            "2026-08-24T10:15:00Z",
        ),
    ]
    inputs = _target_only_inputs(windows)

    first = _rank(inputs, limit=2)
    second = _rank(inputs, limit=2)

    assert first == second
    assert [item["window_id"] for item in first["alternatives"]] == [
        "VW_EARLY_GS1",
        "VW_EARLY_GS2",
    ]
    assert [item["rank"] for item in first["alternatives"]] == [1, 2]


def test_no_duration_feasible_candidate_returns_empty_status():
    short_window = _window(
        "VW_TOO_SHORT",
        TARGET_SATELLITE_ID,
        "GS_1",
        "2026-08-24T10:00:00Z",
        "2026-08-24T10:10:00Z",
    )

    result = _rank(_target_only_inputs([short_window]))

    assert result["status"] == NO_FEASIBLE_ALTERNATIVES
    assert result["alternatives"] == []


def test_only_windows_present_in_real_visibility_are_generated():
    real_window = _window(
        "VW_ONLY_REAL_WINDOW",
        TARGET_SATELLITE_ID,
        "GS_1",
        "2026-08-24T10:00:00Z",
        "2026-08-24T10:15:00Z",
    )
    inputs = list(_target_only_inputs([real_window]))
    inputs[3] = _evidence(["VW_NOT_IN_VISIBILITY"])

    result = _rank(tuple(inputs))

    assert [item["window_id"] for item in result["alternatives"]] == [
        "VW_ONLY_REAL_WINDOW"
    ]


def test_higher_priority_contact_is_protected():
    high_request_id = "REQ_HIGH"
    high_satellite_id = "NORAD_20001"
    windows = [
        _window(
            "VW_HIGH",
            high_satellite_id,
            "GS_1",
            "2026-08-24T10:00:00Z",
            "2026-08-24T10:15:00Z",
        ),
        _window(
            "VW_TARGET_CONFLICT",
            TARGET_SATELLITE_ID,
            "GS_1",
            "2026-08-24T10:00:00Z",
            "2026-08-24T10:15:00Z",
        ),
        _window(
            "VW_TARGET_CLEAR",
            TARGET_SATELLITE_ID,
            "GS_2",
            "2026-08-24T11:00:00Z",
            "2026-08-24T11:15:00Z",
        ),
    ]
    mission_data = _mission([
        _request(high_request_id, high_satellite_id, 9, ["GS_1"]),
        _request(TARGET_ID, TARGET_SATELLITE_ID, 5, ["GS_1", "GS_2"]),
    ])
    high_contact = {
        "request_id": high_request_id,
        "satellite_id": high_satellite_id,
        "station_id": "GS_1",
        "window_id": "VW_HIGH",
        "scheduled_start": "2026-08-24T10:00:00Z",
        "scheduled_end": "2026-08-24T10:15:00Z",
        "duration_seconds": 900,
        "priority": 9,
    }
    baseline = _manual_unscheduled_baseline([high_contact])

    result = rank_alternatives(
        _visibility(windows), mission_data, baseline, _evidence(), TARGET_ID
    )

    assert [item["window_id"] for item in result["alternatives"]] == [
        "VW_TARGET_CLEAR"
    ]
    assert result["alternatives"][0]["displaced_request_ids"] == []


def test_lower_priority_displacement_is_disclosed():
    lower_id = "REQ_LOWER"
    lower_satellite_id = "NORAD_20003"
    target_window = _window(
        "VW_TARGET_SHARED",
        TARGET_SATELLITE_ID,
        "GS_1",
        "2026-08-24T10:00:00Z",
        "2026-08-24T10:15:00Z",
    )
    lower_window = _window(
        "VW_LOWER_SHARED",
        lower_satellite_id,
        "GS_1",
        "2026-08-24T10:00:00Z",
        "2026-08-24T10:15:00Z",
    )
    mission_data = _mission([
        _request(TARGET_ID, TARGET_SATELLITE_ID, 5, ["GS_1"]),
        _request(lower_id, lower_satellite_id, 4, ["GS_1"]),
    ])
    baseline_contact = {
        "request_id": lower_id,
        "satellite_id": lower_satellite_id,
        "station_id": "GS_1",
        "window_id": "VW_LOWER_SHARED",
        "scheduled_start": "2026-08-24T10:00:00Z",
        "scheduled_end": "2026-08-24T10:15:00Z",
        "duration_seconds": 900,
        "priority": 4,
    }

    result = rank_alternatives(
        _visibility([target_window, lower_window]),
        mission_data,
        _manual_unscheduled_baseline([baseline_contact]),
        _evidence(),
        TARGET_ID,
    )

    alternative = result["alternatives"][0]
    assert alternative["displaced_request_ids"] == [lower_id]
    assert alternative["ranking_metrics"]["displaced_count"] == 1
    assert alternative["ranking_metrics"]["displaced_priority_total"] == 4


def test_lower_disruption_candidate_ranks_before_displacing_candidate():
    lower_id = "REQ_LOWER"
    lower_satellite_id = "NORAD_20003"
    windows = [
        _window(
            "VW_TARGET_DISRUPTING",
            TARGET_SATELLITE_ID,
            "GS_1",
            "2026-08-24T10:00:00Z",
            "2026-08-24T10:15:00Z",
        ),
        _window(
            "VW_TARGET_CLEAR",
            TARGET_SATELLITE_ID,
            "GS_2",
            "2026-08-24T11:00:00Z",
            "2026-08-24T11:15:00Z",
        ),
        _window(
            "VW_LOWER_SHARED",
            lower_satellite_id,
            "GS_1",
            "2026-08-24T10:00:00Z",
            "2026-08-24T10:15:00Z",
        ),
    ]
    mission_data = _mission([
        _request(TARGET_ID, TARGET_SATELLITE_ID, 5, ["GS_1", "GS_2"]),
        _request(lower_id, lower_satellite_id, 4, ["GS_1"]),
    ])
    baseline_contact = {
        "request_id": lower_id,
        "satellite_id": lower_satellite_id,
        "station_id": "GS_1",
        "window_id": "VW_LOWER_SHARED",
        "scheduled_start": "2026-08-24T10:00:00Z",
        "scheduled_end": "2026-08-24T10:15:00Z",
        "duration_seconds": 900,
        "priority": 4,
    }

    result = rank_alternatives(
        _visibility(windows),
        mission_data,
        _manual_unscheduled_baseline([baseline_contact]),
        _evidence(),
        TARGET_ID,
    )

    assert [item["window_id"] for item in result["alternatives"]] == [
        "VW_TARGET_CLEAR",
        "VW_TARGET_DISRUPTING",
    ]
    assert [
        item["ranking_metrics"]["displaced_count"]
        for item in result["alternatives"]
    ] == [0, 1]


def test_rescheduled_baseline_contact_is_disclosed():
    mover_id = "REQ_MOVER"
    mover_satellite_id = "NORAD_20004"
    windows = [
        _window(
            "VW_TARGET_SHARED",
            TARGET_SATELLITE_ID,
            "GS_1",
            "2026-08-24T10:00:00Z",
            "2026-08-24T10:15:00Z",
        ),
        _window(
            "VW_MOVER_BASELINE",
            mover_satellite_id,
            "GS_1",
            "2026-08-24T10:00:00Z",
            "2026-08-24T10:15:00Z",
        ),
        _window(
            "VW_MOVER_BACKUP",
            mover_satellite_id,
            "GS_2",
            "2026-08-24T11:00:00Z",
            "2026-08-24T11:15:00Z",
        ),
    ]
    mission_data = _mission([
        _request(TARGET_ID, TARGET_SATELLITE_ID, 5, ["GS_1"]),
        _request(mover_id, mover_satellite_id, 4, ["GS_1", "GS_2"]),
    ])
    baseline_contact = {
        "request_id": mover_id,
        "satellite_id": mover_satellite_id,
        "station_id": "GS_1",
        "window_id": "VW_MOVER_BASELINE",
        "scheduled_start": "2026-08-24T10:00:00Z",
        "scheduled_end": "2026-08-24T10:15:00Z",
        "duration_seconds": 900,
        "priority": 4,
    }

    result = rank_alternatives(
        _visibility(windows),
        mission_data,
        _manual_unscheduled_baseline([baseline_contact]),
        _evidence(),
        TARGET_ID,
    )

    alternative = next(
        item
        for item in result["alternatives"]
        if item["window_id"] == "VW_TARGET_SHARED"
    )
    assert alternative["displaced_request_ids"] == []
    assert alternative["rescheduled_request_ids"] == [mover_id]
    assert alternative["ranking_metrics"]["rescheduled_count"] == 1
    assert alternative["ranking_metrics"]["rescheduled_priority_total"] == 4


def test_all_inputs_remain_unchanged_and_ids_stay_canonical():
    window = _window(
        "VW_CANONICAL",
        TARGET_SATELLITE_ID,
        "GS_2",
        "2026-08-24T10:00:00Z",
        "2026-08-24T10:15:00Z",
    )
    inputs = _target_only_inputs([window])
    originals = copy.deepcopy(inputs)

    result = _rank(inputs)

    assert inputs == originals
    assert result["satellite_id"] == TARGET_SATELLITE_ID
    assert result["alternatives"][0]["window_id"] == "VW_CANONICAL"
    assert result["alternatives"][0]["station_id"] == "GS_2"


def test_duplicate_identical_windows_are_collapsed():
    window = _window(
        "VW_DUPLICATE",
        TARGET_SATELLITE_ID,
        "GS_1",
        "2026-08-24T10:00:00Z",
        "2026-08-24T10:15:00Z",
    )

    result = _rank(_target_only_inputs([window, copy.deepcopy(window)]))

    assert [item["window_id"] for item in result["alternatives"]] == [
        "VW_DUPLICATE"
    ]


def test_conflicting_duplicate_window_ids_fail_clearly():
    first = _window(
        "VW_DUPLICATE",
        TARGET_SATELLITE_ID,
        "GS_1",
        "2026-08-24T10:00:00Z",
        "2026-08-24T10:15:00Z",
    )
    conflicting = {**first, "station_id": "GS_2"}

    with pytest.raises(AlternativesValidationError, match="Conflicting duplicate"):
        _rank(_target_only_inputs([first, conflicting]))


def test_target_already_scheduled_returns_empty_status():
    window = _window(
        "VW_ALREADY_SCHEDULED",
        TARGET_SATELLITE_ID,
        "GS_1",
        "2026-08-24T10:00:00Z",
        "2026-08-24T10:15:00Z",
    )
    visibility_data, mission_data, _, evidence = _target_only_inputs([window])
    schedule_result = solve_schedule(visibility_data, mission_data, deterministic=True)

    result = rank_alternatives(
        visibility_data,
        mission_data,
        schedule_result,
        evidence,
        TARGET_ID,
    )

    assert result["status"] == REQUEST_ALREADY_SCHEDULED
    assert result["reason_codes"] == []
    assert result["alternatives"] == []


def test_unknown_request_id_fails_clearly():
    window = _window(
        "VW_REAL",
        TARGET_SATELLITE_ID,
        "GS_1",
        "2026-08-24T10:00:00Z",
        "2026-08-24T10:15:00Z",
    )
    inputs = _target_only_inputs([window])

    with pytest.raises(AlternativesValidationError, match="Unknown mission request"):
        rank_alternatives(*inputs, "REQ_UNKNOWN")


def test_solver_selected_contact_is_inside_real_window():
    window = _window(
        "VW_FLEXIBLE_INTERVAL",
        TARGET_SATELLITE_ID,
        "GS_1",
        "2026-08-24T10:00:00Z",
        "2026-08-24T10:30:00Z",
    )

    result = _rank(_target_only_inputs([window]))
    alternative = result["alternatives"][0]
    start = datetime.fromisoformat(
        alternative["scheduled_start"].replace("Z", "+00:00")
    )
    end = datetime.fromisoformat(
        alternative["scheduled_end"].replace("Z", "+00:00")
    )
    aos = datetime.fromisoformat(window["aos"].replace("Z", "+00:00"))
    los = datetime.fromisoformat(window["los"].replace("Z", "+00:00"))

    assert aos <= start < end <= los
    assert int((end - start).total_seconds()) == 900


def test_full_visibility_not_evidence_hint_is_candidate_source():
    hinted = _window(
        "VW_HINTED",
        TARGET_SATELLITE_ID,
        "GS_1",
        "2026-08-24T11:00:00Z",
        "2026-08-24T11:15:00Z",
    )
    unhinted = _window(
        "VW_UNHINTED",
        TARGET_SATELLITE_ID,
        "GS_2",
        "2026-08-24T10:00:00Z",
        "2026-08-24T10:15:00Z",
    )
    inputs = list(_target_only_inputs([hinted, unhinted]))
    inputs[3] = _evidence(["VW_HINTED"])

    result = _rank(tuple(inputs))

    assert {item["window_id"] for item in result["alternatives"]} == {
        "VW_HINTED",
        "VW_UNHINTED",
    }


def test_real_p2_schedule_evidence_and_alternatives_integration():
    # Single source of truth: backend/data/demo_scenarios.py. The live-API
    # seed script (`python -m backend.data.demo_scenarios ranked_alternatives`)
    # reuses the exact same data so the two can't drift apart.
    lower_a_id = "REQ_LOWER_A"
    lower_b_id = "REQ_LOWER_B"
    visibility_data, mission_data = ranked_alternatives_scenario()

    baseline = solve_schedule(visibility_data, mission_data, deterministic=True)
    evidence = build_conflict_evidence(visibility_data, mission_data, baseline)
    result = rank_alternatives(
        visibility_data,
        mission_data,
        baseline,
        evidence,
        TARGET_ID,
    )

    assert {item["request_id"] for item in baseline["scheduled_contacts"]} == {
        lower_a_id,
        lower_b_id,
    }
    assert result["status"] == ALTERNATIVES_FOUND
    assert result["reason_codes"] == ["ANTENNA_RESOURCE_CONFLICT"]
    assert result["alternatives"][0]["window_id"] == "VW_TARGET_LONG"
    assert result["alternatives"][0]["displaced_request_ids"] == [
        lower_a_id,
        lower_b_id,
    ]
