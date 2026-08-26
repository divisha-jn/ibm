import copy
from datetime import datetime

import pytest

from backend.solver.alternatives import rank_alternatives
from backend.solver.conflicts import build_conflict_evidence
from backend.solver.risk import (
    OperationalRiskValidationError,
    assess_operational_risk,
)
from backend.solver.scheduler import solve_schedule


SCENARIO_ID = "RISK_TEST_001"
TARGET_ID = "REQ_TARGET"
TARGET_SATELLITE_ID = "NORAD_10001"


def _window(
    window_id,
    station_id="GS_1",
    aos="2026-08-25T10:00:00Z",
    los="2026-08-25T10:10:00Z",
    *,
    satellite_id=TARGET_SATELLITE_ID,
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
        "max_elevation_deg": 40.0,
    }


def _request(
    request_id=TARGET_ID,
    satellite_id=TARGET_SATELLITE_ID,
    *,
    required_seconds=300,
    priority=5,
    stations=None,
):
    return {
        "request_id": request_id,
        "satellite_id": satellite_id,
        "required_contact_seconds": required_seconds,
        "priority": priority,
        "eligible_station_ids": list(stations or ["GS_1", "GS_2"]),
        "mandatory": False,
    }


def _visibility(windows):
    return {
        "planning_horizon": {
            "start": "2026-08-25T00:00:00Z",
            "end": "2026-08-26T00:00:00Z",
        },
        "minimum_elevation_deg": 10.0,
        "visibility_windows": windows,
    }


def _mission(requests=None):
    return {
        "scenario_id": SCENARIO_ID,
        "requests": list(requests or [_request()]),
    }


def _contact(
    request_id=TARGET_ID,
    satellite_id=TARGET_SATELLITE_ID,
    station_id="GS_1",
    window_id="VW_TARGET",
    start="2026-08-25T10:00:00Z",
    end="2026-08-25T10:05:00Z",
    *,
    priority=5,
):
    duration = int(
        (
            datetime.fromisoformat(end.replace("Z", "+00:00"))
            - datetime.fromisoformat(start.replace("Z", "+00:00"))
        ).total_seconds()
    )
    return {
        "request_id": request_id,
        "satellite_id": satellite_id,
        "station_id": station_id,
        "window_id": window_id,
        "scheduled_start": start,
        "scheduled_end": end,
        "duration_seconds": duration,
        "priority": priority,
    }


def _scheduled_result(contact=None, other_contacts=None):
    return {
        "scenario_id": SCENARIO_ID,
        "solver": {
            "engine": "OR-Tools CP-SAT",
            "status": "OPTIMAL",
            "objective_value": 5.0,
        },
        "scheduled_contacts": [contact or _contact(), *(other_contacts or [])],
        "unscheduled_requests": [],
    }


def _unscheduled_result(other_contacts=None):
    return {
        "scenario_id": SCENARIO_ID,
        "solver": {
            "engine": "OR-Tools CP-SAT",
            "status": "OPTIMAL",
            "objective_value": 0.0,
        },
        "scheduled_contacts": list(other_contacts or []),
        "unscheduled_requests": [
            {
                "request_id": TARGET_ID,
                "satellite_id": TARGET_SATELLITE_ID,
                "priority": 5,
            }
        ],
    }


def _evidence(reason_codes=None, conflicts=None):
    return {
        "scenario_id": SCENARIO_ID,
        "evidence": [
            {
                "request_id": TARGET_ID,
                "status": "UNSCHEDULED",
                "reason_codes": list(reason_codes or ["OPTIMIZATION_TRADEOFF"]),
                "conflicts": list(conflicts or []),
                "feasibility": {"requested_contact_seconds": 300},
                "alternative_window_ids": [],
            }
        ],
    }


def _complete_weather_status():
    return {"data_status": "COMPLETE"}


def _assess_scheduled(
    windows=None,
    *,
    request=None,
    contact=None,
    other_contacts=None,
    events=None,
    weather_status=None,
):
    windows = list(windows or [_window("VW_TARGET")])
    return assess_operational_risk(
        _visibility(windows),
        _mission([request or _request()]),
        _scheduled_result(contact, other_contacts),
        {"scenario_id": SCENARIO_ID, "evidence": []},
        TARGET_ID,
        space_weather_events=[] if events is None else events,
        space_weather_status=(
            _complete_weather_status() if weather_status is None else weather_status
        ),
    )


def _assess_unscheduled(
    windows,
    *,
    reason_codes=None,
    other_contacts=None,
    alternatives_result=None,
):
    return assess_operational_risk(
        _visibility(windows),
        _mission(),
        _unscheduled_result(other_contacts),
        _evidence(reason_codes),
        TARGET_ID,
        space_weather_events=[],
        space_weather_status=_complete_weather_status(),
        alternatives_result=alternatives_result,
    )


def _alternative_result(state):
    base = {
        "scenario_id": SCENARIO_ID,
        "request_id": TARGET_ID,
        "satellite_id": TARGET_SATELLITE_ID,
        "reason_codes": ["ANTENNA_RESOURCE_CONFLICT"],
    }
    if state == "NONE":
        return {**base, "status": "NO_FEASIBLE_ALTERNATIVES", "alternatives": []}
    displaced = ["REQ_OTHER"] if state == "DISPLACEMENT_REQUIRED" else []
    rescheduled = ["REQ_OTHER"] if state == "RESCHEDULE_REQUIRED" else []
    return {
        **base,
        "status": "ALTERNATIVES_FOUND",
        "alternatives": [
            {
                "rank": 1,
                "alternative_type": "ALTERNATIVE_WINDOW",
                "window_id": "VW_TARGET",
                "station_id": "GS_1",
                "scheduled_start": "2026-08-25T10:00:00Z",
                "scheduled_end": "2026-08-25T10:05:00Z",
                "duration_seconds": 300,
                "displaced_request_ids": displaced,
                "rescheduled_request_ids": rescheduled,
                "ranking_metrics": {
                    "displaced_count": len(displaced),
                    "displaced_priority_total": 4 if displaced else 0,
                    "rescheduled_count": len(rescheduled),
                    "rescheduled_priority_total": 4 if rescheduled else 0,
                },
            }
        ],
    }


def _flare(class_type="M2.3", *, start="2026-08-25T10:01:00Z", end="2026-08-25T10:03:00Z"):
    return {
        "event_type": "solar_flare",
        "event_id": f"FLR_{class_type}",
        "start_time": start,
        "peak_time": start,
        "end_time": end,
        "class_type": class_type,
        "source_location": "N15E20",
        "advisory": "fixture",
    }


def _p1_weather_status(flr="ok", gst="ok"):
    return {"FLR": flr, "GST": gst}


def _gst(readings, *, start="2026-08-25T09:00:00Z"):
    numeric_kp = [
        reading.get("kp_index")
        for reading in readings
        if isinstance(reading, dict)
        and isinstance(reading.get("kp_index"), (int, float))
        and not isinstance(reading.get("kp_index"), bool)
    ]
    max_kp = max(numeric_kp, default=None)
    max_reading = next(
        (
            reading
            for reading in readings
            if isinstance(reading, dict) and reading.get("kp_index") == max_kp
        ),
        {},
    )
    return {
        "event_type": "geomagnetic_storm",
        "event_id": "GST_1",
        "start_time": start,
        "max_kp_index": max_kp,
        "max_kp_time": max_reading.get("time"),
        "kp_readings": copy.deepcopy(readings),
        "advisory": "fixture",
    }


# Scheduling flexibility ----------------------------------------------------


def test_no_feasible_window_is_unresolved_with_max_flexibility_factor():
    result = _assess_unscheduled([], reason_codes=["NO_ELIGIBLE_VISIBILITY_WINDOW"])
    factor = result["factors"]["scheduling_flexibility"]
    assert factor["factor_score"] == 1.0
    assert factor["points"] == 20
    assert factor["metrics"]["duration_feasible_window_count"] == 0
    assert "NO_ELIGIBLE_VISIBILITY_WINDOW" in result["reason_codes"]


def test_exactly_one_feasible_window():
    result = _assess_scheduled()
    factor = result["factors"]["scheduling_flexibility"]
    assert factor == {
        "weight": 20,
        "factor_score": 1.0,
        "points": 20,
        "metrics": {
            "duration_feasible_window_count": 1,
            "total_feasible_visibility_seconds": 600,
            "total_start_slack_seconds": 300,
        },
    }
    assert "SINGLE_FEASIBLE_WINDOW" in result["reason_codes"]


def test_two_feasible_windows():
    result = _assess_scheduled(
        [
            _window("VW_TARGET"),
            _window("VW_SECOND", aos="2026-08-25T11:00:00Z", los="2026-08-25T11:10:00Z"),
        ]
    )
    factor = result["factors"]["scheduling_flexibility"]
    assert factor["factor_score"] == 0.6
    assert factor["points"] == 12


def test_three_feasible_windows():
    windows = [
        _window("VW_TARGET"),
        _window("VW_2", aos="2026-08-25T11:00:00Z", los="2026-08-25T11:10:00Z"),
        _window("VW_3", aos="2026-08-25T12:00:00Z", los="2026-08-25T12:10:00Z"),
    ]
    factor = _assess_scheduled(windows)["factors"]["scheduling_flexibility"]
    assert factor["factor_score"] == 0.35
    assert factor["points"] == 7


def test_four_or_more_feasible_windows():
    windows = [
        _window("VW_TARGET"),
        *[
            _window(
                f"VW_{hour}",
                aos=f"2026-08-25T{hour:02d}:00:00Z",
                los=f"2026-08-25T{hour:02d}:10:00Z",
            )
            for hour in (11, 12, 13)
        ],
    ]
    factor = _assess_scheduled(windows)["factors"]["scheduling_flexibility"]
    assert factor["factor_score"] == 0.15
    assert factor["points"] == 3


def test_short_and_ineligible_windows_are_excluded():
    windows = [
        _window("VW_TARGET"),
        _window("VW_SHORT", aos="2026-08-25T11:00:00Z", los="2026-08-25T11:04:00Z"),
        _window("VW_INELIGIBLE", station_id="GS_9", aos="2026-08-25T12:00:00Z", los="2026-08-25T12:10:00Z"),
    ]
    factor = _assess_scheduled(windows)["factors"]["scheduling_flexibility"]
    assert factor["metrics"]["duration_feasible_window_count"] == 1


def test_actual_timestamps_not_reported_duration_determine_feasibility():
    short = _window("VW_SHORT", aos="2026-08-25T11:00:00Z", los="2026-08-25T11:04:59Z")
    short["duration_seconds"] = 999
    result = _assess_scheduled([_window("VW_TARGET"), short])
    assert result["factors"]["scheduling_flexibility"]["metrics"]["duration_feasible_window_count"] == 1


# Ground-station redundancy -------------------------------------------------


def test_one_usable_station():
    factor = _assess_scheduled()["factors"]["station_redundancy"]
    assert factor["factor_score"] == 1.0
    assert factor["points"] == 15
    assert factor["metrics"]["usable_station_ids"] == ["GS_1"]


def test_two_usable_stations():
    windows = [
        _window("VW_TARGET"),
        _window("VW_GS2", "GS_2", "2026-08-25T11:00:00Z", "2026-08-25T11:10:00Z"),
    ]
    factor = _assess_scheduled(windows)["factors"]["station_redundancy"]
    assert factor["factor_score"] == 0.5
    assert factor["points"] == 8
    assert factor["metrics"]["usable_station_ids"] == ["GS_1", "GS_2"]


def test_multiple_windows_at_one_station_count_once():
    windows = [
        _window("VW_TARGET"),
        _window("VW_2", aos="2026-08-25T11:00:00Z", los="2026-08-25T11:10:00Z"),
    ]
    factor = _assess_scheduled(windows)["factors"]["station_redundancy"]
    assert factor["metrics"]["usable_station_count"] == 1


def test_eligible_station_without_real_feasible_window_is_not_counted():
    result = _assess_scheduled(request=_request(stations=["GS_1", "GS_2", "GS_3"]))
    assert result["factors"]["station_redundancy"]["metrics"]["usable_station_ids"] == ["GS_1"]


# Conflict pressure ---------------------------------------------------------


def test_no_blocked_windows():
    factor = _assess_scheduled()["factors"]["conflict_pressure"]
    assert factor["factor_score"] == 0.0
    assert factor["points"] == 0
    assert factor["metrics"]["blocked_window_count"] == 0


def test_partial_blocked_windows():
    windows = [
        _window("VW_TARGET"),
        _window("VW_BACKUP", aos="2026-08-25T11:00:00Z", los="2026-08-25T11:10:00Z"),
        _window("VW_OTHER", aos="2026-08-25T11:00:00Z", los="2026-08-25T11:10:00Z", satellite_id="NORAD_20002"),
    ]
    other = _contact(
        "REQ_OTHER",
        "NORAD_20002",
        "GS_1",
        "VW_OTHER",
        "2026-08-25T11:00:00Z",
        "2026-08-25T11:10:00Z",
        priority=9,
    )
    factor = _assess_scheduled(windows, other_contacts=[other])["factors"]["conflict_pressure"]
    assert factor["factor_score"] == 0.5
    assert factor["points"] == 12
    assert factor["metrics"]["conflicting_request_ids"] == ["REQ_OTHER"]


def test_all_feasible_windows_blocked_for_unscheduled_request():
    target_window = _window("VW_TARGET")
    other_window = _window("VW_OTHER", satellite_id="NORAD_20002")
    other = _contact(
        "REQ_OTHER",
        "NORAD_20002",
        "GS_1",
        "VW_OTHER",
        "2026-08-25T10:00:00Z",
        "2026-08-25T10:10:00Z",
        priority=9,
    )
    result = _assess_unscheduled(
        [target_window, other_window],
        reason_codes=["ANTENNA_RESOURCE_CONFLICT"],
        other_contacts=[other],
    )
    factor = result["factors"]["conflict_pressure"]
    assert factor["factor_score"] == 1.0
    assert factor["points"] == 25
    assert "ALL_FEASIBLE_WINDOWS_BLOCKED" in result["reason_codes"]


def test_targets_own_contact_is_excluded_from_conflict_pressure():
    factor = _assess_scheduled()["factors"]["conflict_pressure"]
    assert factor["metrics"]["blocked_window_fraction"] == 0.0
    assert factor["metrics"]["conflicting_request_ids"] == []


def test_overlapping_contacts_are_merged_before_free_segment_check():
    target = _window("VW_TARGET", aos="2026-08-25T10:00:00Z", los="2026-08-25T10:20:00Z")
    other_windows = [
        _window("VW_O1", aos="2026-08-25T10:00:00Z", los="2026-08-25T10:12:00Z", satellite_id="NORAD_20001"),
        _window("VW_O2", aos="2026-08-25T10:08:00Z", los="2026-08-25T10:20:00Z", satellite_id="NORAD_20002"),
    ]
    contacts = [
        _contact("REQ_O1", "NORAD_20001", "GS_1", "VW_O1", "2026-08-25T10:00:00Z", "2026-08-25T10:12:00Z"),
        _contact("REQ_O2", "NORAD_20002", "GS_1", "VW_O2", "2026-08-25T10:08:00Z", "2026-08-25T10:20:00Z"),
    ]
    result = _assess_unscheduled(
        [target, *other_windows],
        reason_codes=["ANTENNA_RESOURCE_CONFLICT"],
        other_contacts=contacts,
    )
    assert result["factors"]["conflict_pressure"]["metrics"]["blocked_window_count"] == 1


# Mission priority ----------------------------------------------------------


def test_low_priority_contributes_one_point():
    factor = _assess_scheduled(request=_request(priority=1))["factors"]["mission_priority"]
    assert factor["factor_score"] == 0.1
    assert factor["points"] == 1


def test_high_priority_contributes_ten_points():
    factor = _assess_scheduled(request=_request(priority=10))["factors"]["mission_priority"]
    assert factor["factor_score"] == 1.0
    assert factor["points"] == 10
    assert factor["metrics"]["meaning"] == "OPERATIONAL_CONSEQUENCE"


@pytest.mark.parametrize("priority", [0, 11, -1, 5.5, True])
def test_priority_outside_approved_range_fails(priority):
    with pytest.raises(OperationalRiskValidationError, match="priority must be"):
        _assess_scheduled(request=_request(priority=priority))


# Space weather -------------------------------------------------------------


@pytest.mark.parametrize(
    ("class_type", "factor_score", "points"),
    [("C3.2", 0.2, 2), ("M2.3", 0.6, 6), ("X1.0", 1.0, 10)],
)
def test_overlapping_flare_class_mapping(class_type, factor_score, points):
    factor = _assess_scheduled(events=[_flare(class_type)])["factors"]["space_weather"]
    assert factor["factor_score"] == factor_score
    assert factor["points"] == points
    assert len(factor["matched_events"]) == 1


def test_flare_outside_contact_has_no_points_when_data_complete():
    factor = _assess_scheduled(
        events=[_flare(start="2026-08-25T11:00:00Z", end="2026-08-25T11:02:00Z")]
    )["factors"]["space_weather"]
    assert factor["factor_score"] == 0.0
    assert factor["points"] == 0
    assert factor["matched_events"] == []


def test_missing_flare_end_time_is_invalid_and_neutral():
    event = _flare()
    event["end_time"] = None
    result = _assess_scheduled(events=[event])
    factor = result["factors"]["space_weather"]
    assert factor["factor_score"] == 0.5
    assert factor["status"] == "PARTIAL"
    assert "SPACE_WEATHER_EVENT_INVALID" in result["reason_codes"]


@pytest.mark.parametrize("class_type", [None, "unknown", "Z9"])
def test_overlapping_invalid_or_missing_flare_class_is_neutral(class_type):
    event = _flare("M1")
    event["class_type"] = class_type
    result = _assess_scheduled(events=[event])
    assert result["factors"]["space_weather"]["factor_score"] == 0.5
    assert "SPACE_WEATHER_EVENT_INVALID" in result["reason_codes"]


def test_gst_is_context_only_and_adds_no_points():
    event = {
        "event_type": "geomagnetic_storm",
        "event_id": "GST_1",
        "start_time": "2026-08-25T09:00:00Z",
        "max_kp_index": 7,
        "advisory": "fixture",
    }
    result = _assess_scheduled(events=[event])
    factor = result["factors"]["space_weather"]
    assert factor["factor_score"] == 0.0
    assert factor["points"] == 0
    assert factor["context_events"] == [event]
    assert "GEOMAGNETIC_ACTIVITY_CONTEXT" in result["reason_codes"]


def test_empty_events_without_status_are_unknown_not_clear():
    result = _assess_scheduled(events=[], weather_status={})
    factor = result["factors"]["space_weather"]
    assert factor["status"] == "UNKNOWN"
    assert factor["state"] == "UNKNOWN"
    assert factor["factor_score"] == 0.5
    assert factor["points"] == 5
    assert "SPACE_WEATHER_DATA_UNKNOWN" in result["reason_codes"]


def test_complete_empty_weather_is_clear_with_zero_points():
    factor = _assess_scheduled(events=[])["factors"]["space_weather"]
    assert factor["status"] == "COMPLETE"
    assert factor["state"] == "CLEAR"
    assert factor["factor_score"] == 0.0
    assert factor["points"] == 0


def test_positive_flare_is_scored_while_partial_status_is_preserved():
    result = _assess_scheduled(
        events=[_flare("X2.0")], weather_status={"data_status": "PARTIAL"}
    )
    assert result["factors"]["space_weather"]["points"] == 10
    assert "SPACE_WEATHER_DATA_UNKNOWN" in result["reason_codes"]


@pytest.mark.parametrize(
    ("flr_status", "gst_status", "quality", "points"),
    [
        ("ok", "ok", "COMPLETE", 0),
        ("ok", "stale", "PARTIAL", 5),
        ("stale", "ok", "PARTIAL", 5),
        ("stale", "stale", "PARTIAL", 5),
        ("ok", "failed", "PARTIAL", 5),
        ("failed", "ok", "PARTIAL", 5),
        ("stale", "failed", "PARTIAL", 5),
        ("failed", "stale", "PARTIAL", 5),
        ("failed", "failed", "UNAVAILABLE", 5),
    ],
)
def test_p1_fetch_status_mapping(flr_status, gst_status, quality, points):
    result = _assess_scheduled(
        events=[],
        weather_status=_p1_weather_status(flr_status, gst_status),
    )
    factor = result["factors"]["space_weather"]
    assert factor["status"] == quality
    assert factor["points"] == points
    assert factor["state"] == ("CLEAR" if quality == "COMPLETE" else "UNKNOWN")


def test_stale_status_is_reported_without_adding_severity_points():
    result = _assess_scheduled(
        events=[], weather_status=_p1_weather_status("ok", "stale")
    )
    assert "SPACE_WEATHER_DATA_STALE" in result["reason_codes"]
    assert "SPACE_WEATHER_DATA_UNKNOWN" in result["reason_codes"]


def test_failed_empty_weather_is_not_clear():
    factor = _assess_scheduled(
        events=[], weather_status=_p1_weather_status("failed", "failed")
    )["factors"]["space_weather"]
    assert factor["status"] == "UNAVAILABLE"
    assert factor["state"] == "UNKNOWN"
    assert factor["factor_score"] == 0.5


@pytest.mark.parametrize(
    ("kp_index", "factor_score", "points"),
    [
        (4, 0.0, 0),
        (5, 0.2, 2),
        (6, 0.4, 4),
        (7, 0.6, 6),
        (8, 0.8, 8),
        (9, 1.0, 10),
    ],
)
def test_contact_relevant_kp_mapping(kp_index, factor_score, points):
    event = _gst(
        [
            {
                "time": "2026-08-25T10:01:00Z",
                "kp_index": kp_index,
                "source": "NOAA",
            }
        ]
    )
    result = _assess_scheduled(
        events=[event], weather_status=_p1_weather_status()
    )
    factor = result["factors"]["space_weather"]
    assert factor["factor_score"] == factor_score
    assert factor["points"] == points
    assert factor["effective_kp_index"] == kp_index
    assert factor["matched_kp_readings"] == event["kp_readings"]
    assert factor["context_events"] == []
    assert "GEOMAGNETIC_STORM_CONTACT_RELEVANT" in result["reason_codes"]


@pytest.mark.parametrize(
    ("observed_at", "matched"),
    [
        ("2026-08-25T09:59:59Z", False),
        ("2026-08-25T10:00:00Z", True),
        ("2026-08-25T10:05:00Z", False),
    ],
)
def test_kp_contact_matching_uses_half_open_interval(observed_at, matched):
    event = _gst(
        [{"time": observed_at, "kp_index": 8, "source": "NOAA"}]
    )
    factor = _assess_scheduled(
        events=[event], weather_status=_p1_weather_status()
    )["factors"]["space_weather"]
    assert bool(factor["matched_kp_readings"]) is matched
    assert factor["points"] == (8 if matched else 0)


def test_multiple_contact_kp_readings_preserve_evidence_and_use_maximum():
    readings = [
        {"time": "2026-08-25T10:00:00Z", "kp_index": 5, "source": "NOAA"},
        {"time": "2026-08-25T10:02:00Z", "kp_index": 7, "source": None},
        {"time": "2026-08-25T10:04:00Z", "kp_index": 6, "source": "GFZ"},
        {"time": "2026-08-25T10:06:00Z", "kp_index": 9, "source": "NOAA"},
    ]
    factor = _assess_scheduled(
        events=[_gst(readings)], weather_status=_p1_weather_status()
    )["factors"]["space_weather"]
    assert factor["matched_kp_readings"] == readings[:3]
    assert factor["effective_kp_index"] == 7
    assert factor["factor_score"] == 0.6
    assert factor["points"] == 6


@pytest.mark.parametrize(
    "bad_reading",
    [
        {"time": "not-a-time", "kp_index": 8, "source": "NOAA"},
        {"time": "2026-08-25T10:01:00Z", "kp_index": "8", "source": "NOAA"},
        {"time": "2026-08-25T10:01:00Z", "kp_index": True, "source": "NOAA"},
        {"time": "2026-08-25T10:01:00Z", "kp_index": 10, "source": "NOAA"},
    ],
)
def test_malformed_kp_reading_is_ignored_and_flagged(bad_reading):
    valid = {"time": "2026-08-25T10:02:00Z", "kp_index": 6, "source": None}
    result = _assess_scheduled(
        events=[_gst([bad_reading, valid])],
        weather_status=_p1_weather_status(),
    )
    factor = result["factors"]["space_weather"]
    assert factor["matched_kp_readings"] == [valid]
    assert factor["effective_kp_index"] == 6
    assert factor["points"] == 4
    assert factor["status"] == "PARTIAL"
    assert "INVALID_KP_READING" in result["reason_codes"]
    assert "SPACE_WEATHER_EVENT_INVALID" in result["reason_codes"]


def test_old_gst_without_timed_readings_remains_context_only():
    event = {
        "event_type": "geomagnetic_storm",
        "event_id": "GST_OLD",
        "start_time": "2026-08-25T10:01:00Z",
        "max_kp_index": 9,
        "advisory": "old fixture",
    }
    factor = _assess_scheduled(
        events=[event], weather_status=_p1_weather_status()
    )["factors"]["space_weather"]
    assert factor["points"] == 0
    assert factor["matched_events"] == []
    assert factor["matched_kp_readings"] == []
    assert factor["effective_kp_index"] is None
    assert factor["context_events"] == [event]


@pytest.mark.parametrize(
    ("flare_class", "kp_index", "expected_points"),
    [("M2.3", 8, 8), ("X1.0", 6, 10)],
)
def test_flare_and_gst_use_maximum_not_sum(flare_class, kp_index, expected_points):
    storm = _gst(
        [
            {
                "time": "2026-08-25T10:02:00Z",
                "kp_index": kp_index,
                "source": "NOAA",
            }
        ]
    )
    result = _assess_scheduled(
        events=[_flare(flare_class), storm],
        weather_status=_p1_weather_status(),
    )
    factor = result["factors"]["space_weather"]
    assert factor["points"] == expected_points
    assert len(factor["matched_events"]) == 2
    assert factor["matched_kp_readings"] == storm["kp_readings"]
    assert "SOLAR_FLARE_OVERLAP" in result["reason_codes"]
    assert "GEOMAGNETIC_STORM_CONTACT_RELEVANT" in result["reason_codes"]


def test_stale_gst_evidence_contributes_with_partial_quality():
    storm = _gst(
        [{"time": "2026-08-25T10:01:00Z", "kp_index": 7, "source": "NOAA"}]
    )
    result = _assess_scheduled(
        events=[storm], weather_status=_p1_weather_status("ok", "stale")
    )
    factor = result["factors"]["space_weather"]
    assert factor["status"] == "PARTIAL"
    assert factor["points"] == 6
    assert "SPACE_WEATHER_DATA_STALE" in result["reason_codes"]


def test_failed_flr_does_not_block_valid_gst_evidence():
    storm = _gst(
        [{"time": "2026-08-25T10:01:00Z", "kp_index": 8, "source": "NOAA"}]
    )
    result = _assess_scheduled(
        events=[storm], weather_status=_p1_weather_status("failed", "ok")
    )
    assert result["factors"]["space_weather"]["status"] == "PARTIAL"
    assert result["factors"]["space_weather"]["points"] == 8
    assert "SPACE_WEATHER_DATA_UNKNOWN" in result["reason_codes"]


def test_failed_gst_does_not_block_valid_flare_evidence():
    result = _assess_scheduled(
        events=[_flare("M2.3")],
        weather_status=_p1_weather_status("ok", "failed"),
    )
    assert result["factors"]["space_weather"]["status"] == "PARTIAL"
    assert result["factors"]["space_weather"]["points"] == 6
    assert "SPACE_WEATHER_DATA_UNKNOWN" in result["reason_codes"]


# Recovery ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "factor_score", "points", "reason"),
    [
        ("DIRECT", 0.1, 2, None),
        ("RESCHEDULE_REQUIRED", 0.5, 10, "RECOVERY_REQUIRES_RESCHEDULING"),
        ("DISPLACEMENT_REQUIRED", 0.8, 16, "RECOVERY_REQUIRES_DISPLACEMENT"),
        ("NONE", 1.0, 20, "NO_SOLVER_VALIDATED_ALTERNATIVE"),
    ],
)
def test_unscheduled_recovery_classification(state, factor_score, points, reason):
    result = _assess_unscheduled(
        [_window("VW_TARGET")],
        alternatives_result=_alternative_result(state),
    )
    factor = result["factors"]["recovery"]
    assert factor["state"] == state
    assert factor["factor_score"] == factor_score
    assert factor["points"] == points
    if reason:
        assert reason in result["reason_codes"]


def test_missing_alternatives_is_unknown_recovery():
    factor = _assess_unscheduled([_window("VW_TARGET")])["factors"]["recovery"]
    assert factor["state"] == "UNKNOWN"
    assert factor["factor_score"] == 0.5
    assert factor["points"] == 10


def test_scheduled_request_recovery_is_not_applicable_and_zero():
    factor = _assess_scheduled()["factors"]["recovery"]
    assert factor["state"] == "NOT_APPLICABLE_SCHEDULED"
    assert factor["factor_score"] == 0.0
    assert factor["points"] == 0


# Overall behavior and validation -------------------------------------------


def test_exact_low_risk_example():
    windows = [
        _window("VW_TARGET"),
        _window("VW_2", "GS_2", "2026-08-25T11:00:00Z", "2026-08-25T11:10:00Z"),
        _window("VW_3", "GS_1", "2026-08-25T12:00:00Z", "2026-08-25T12:10:00Z"),
        _window("VW_4", "GS_2", "2026-08-25T13:00:00Z", "2026-08-25T13:10:00Z"),
    ]
    result = _assess_scheduled(windows, request=_request(priority=1))
    assert result["risk_score"] == 12
    assert result["risk_level"] == "LOW"


def test_exact_medium_risk_example():
    result = _assess_scheduled(request=_request(priority=5))
    assert result["risk_score"] == 40
    assert result["risk_level"] == "MEDIUM"


def test_exact_high_risk_example_and_score_is_bounded():
    other_window = _window("VW_OTHER", satellite_id="NORAD_20002")
    other_contact = _contact(
        "REQ_OTHER",
        "NORAD_20002",
        "GS_1",
        "VW_OTHER",
        "2026-08-25T10:00:00Z",
        "2026-08-25T10:10:00Z",
        priority=10,
    )
    result = _assess_scheduled(
        [_window("VW_TARGET"), other_window],
        request=_request(priority=10),
        other_contacts=[other_contact],
        events=[_flare("X2.0")],
    )
    assert result["risk_score"] == 80
    assert result["risk_level"] == "HIGH"
    assert 0 <= result["risk_score"] <= 100


def test_score_equals_sum_of_factor_points():
    result = _assess_scheduled(events=[_flare("M2.3")])
    assert result["risk_score"] == sum(
        factor["points"] for factor in result["factors"].values()
    )


def test_unscheduled_request_has_no_score_or_level():
    result = _assess_unscheduled([_window("VW_TARGET")])
    assert result["schedule_status"] == "UNSCHEDULED"
    assert result["assessment_status"] == "UNRESOLVED"
    assert result["risk_score"] is None
    assert result["risk_level"] is None
    assert result["contact"] is None
    assert result["conflict_evidence"]["request_id"] == TARGET_ID


def test_inputs_are_not_mutated_and_repeated_output_is_deterministic():
    inputs = (
        _visibility([_window("VW_TARGET")]),
        _mission(),
        _scheduled_result(),
        {"scenario_id": SCENARIO_ID, "evidence": []},
        [_flare("C2.0")],
        {"data_status": "COMPLETE"},
    )
    originals = copy.deepcopy(inputs)
    first = assess_operational_risk(
        *inputs[:4],
        TARGET_ID,
        space_weather_events=inputs[4],
        space_weather_status=inputs[5],
    )
    second = assess_operational_risk(
        *inputs[:4],
        TARGET_ID,
        space_weather_events=inputs[4],
        space_weather_status=inputs[5],
    )
    assert inputs == originals
    assert first == second


def test_timed_kp_inputs_are_not_mutated_and_output_is_deterministic():
    storm = _gst(
        [
            {"time": "2026-08-25T10:01:00Z", "kp_index": 8, "source": "NOAA"},
            {"time": "2026-08-25T10:02:00Z", "kp_index": 6, "source": None},
        ]
    )
    status = _p1_weather_status("stale", "ok")
    inputs = (
        _visibility([_window("VW_TARGET")]),
        _mission(),
        _scheduled_result(),
        {"scenario_id": SCENARIO_ID, "evidence": []},
        [storm],
        status,
    )
    originals = copy.deepcopy(inputs)

    first = assess_operational_risk(
        *inputs[:4],
        TARGET_ID,
        space_weather_events=inputs[4],
        space_weather_status=inputs[5],
    )
    second = assess_operational_risk(
        *inputs[:4],
        TARGET_ID,
        space_weather_events=inputs[4],
        space_weather_status=inputs[5],
    )

    assert inputs == originals
    assert first == second


def test_operational_risk_weights_remain_exactly_approved_values():
    factors = _assess_scheduled()["factors"]
    assert {
        name: factor["weight"] for name, factor in factors.items()
    } == {
        "scheduling_flexibility": 20,
        "station_redundancy": 15,
        "conflict_pressure": 25,
        "recovery": 20,
        "mission_priority": 10,
        "space_weather": 10,
    }


def test_scenario_mismatch_fails_clearly():
    schedule = _scheduled_result()
    schedule["scenario_id"] = "OTHER"
    with pytest.raises(OperationalRiskValidationError, match="does not match"):
        assess_operational_risk(
            _visibility([_window("VW_TARGET")]),
            _mission(),
            schedule,
            {"scenario_id": SCENARIO_ID, "evidence": []},
            TARGET_ID,
        )


def test_unknown_request_fails_clearly():
    with pytest.raises(OperationalRiskValidationError, match="exactly once"):
        assess_operational_risk(
            _visibility([_window("VW_TARGET")]),
            _mission(),
            _scheduled_result(),
            {"scenario_id": SCENARIO_ID, "evidence": []},
            "REQ_UNKNOWN",
        )


def test_request_cannot_be_scheduled_and_unscheduled():
    schedule = _scheduled_result()
    schedule["unscheduled_requests"] = [
        {"request_id": TARGET_ID, "satellite_id": TARGET_SATELLITE_ID}
    ]
    with pytest.raises(OperationalRiskValidationError, match="both scheduled and unscheduled"):
        assess_operational_risk(
            _visibility([_window("VW_TARGET")]),
            _mission(),
            schedule,
            {"scenario_id": SCENARIO_ID, "evidence": []},
            TARGET_ID,
        )


def test_identical_duplicate_visibility_windows_are_collapsed():
    window = _window("VW_TARGET")
    result = _assess_scheduled([window, copy.deepcopy(window)])
    assert result["factors"]["scheduling_flexibility"]["metrics"]["duration_feasible_window_count"] == 1


def test_conflicting_duplicate_visibility_ids_fail():
    first = _window("VW_TARGET")
    conflicting = {**first, "los": "2026-08-25T10:11:00Z"}
    with pytest.raises(OperationalRiskValidationError, match="Conflicting duplicate"):
        _assess_scheduled([first, conflicting])


def test_contact_duration_mismatch_fails():
    contact = _contact()
    contact["duration_seconds"] = 299
    with pytest.raises(OperationalRiskValidationError, match="does not match its timestamps"):
        _assess_scheduled(contact=contact)


# P1 -> P2 integration style ------------------------------------------------


def test_real_schedule_to_timed_p1_gst_risk_integration_is_deterministic():
    visibility_data = _visibility([_window("VW_TARGET")])
    mission_data = _mission()
    schedule = solve_schedule(visibility_data, mission_data, deterministic=True)
    evidence = build_conflict_evidence(visibility_data, mission_data, schedule)
    weather = {
        "events": [
            _gst(
                [
                    {
                        "time": "2026-08-25T10:01:00Z",
                        "kp_index": 8,
                        "source": "NOAA",
                    }
                ]
            )
        ],
        "fetch_status": _p1_weather_status(),
    }

    first = assess_operational_risk(
        visibility_data,
        mission_data,
        schedule,
        evidence,
        TARGET_ID,
        space_weather_events=weather["events"],
        space_weather_status=weather["fetch_status"],
    )
    second = assess_operational_risk(
        visibility_data,
        mission_data,
        schedule,
        evidence,
        TARGET_ID,
        space_weather_events=weather["events"],
        space_weather_status=weather["fetch_status"],
    )

    assert schedule["scheduled_contacts"][0]["request_id"] == TARGET_ID
    assert first["schedule_status"] == "SCHEDULED"
    assert first["factors"]["space_weather"]["points"] == 8
    assert first["factors"]["space_weather"]["effective_kp_index"] == 8
    assert first["risk_score"] == sum(
        factor["points"] for factor in first["factors"].values()
    )
    assert first == second


def test_p1_p2_schedule_conflicts_alternatives_weather_risk_integration():
    target_window = _window(
        "VW_TARGET_LONG",
        aos="2026-08-25T10:00:00Z",
        los="2026-08-25T10:20:00Z",
    )
    lower_a_window = _window(
        "VW_LOWER_A",
        aos="2026-08-25T10:00:00Z",
        los="2026-08-25T10:10:00Z",
        satellite_id="NORAD_20001",
    )
    lower_b_window = _window(
        "VW_LOWER_B",
        aos="2026-08-25T10:10:00Z",
        los="2026-08-25T10:20:00Z",
        satellite_id="NORAD_20002",
    )
    visibility_data = _visibility(
        [target_window, lower_a_window, lower_b_window]
    )
    mission_data = _mission(
        [
            _request(required_seconds=1200, priority=6, stations=["GS_1"]),
            _request(
                "REQ_LOWER_A",
                "NORAD_20001",
                required_seconds=600,
                priority=4,
                stations=["GS_1"],
            ),
            _request(
                "REQ_LOWER_B",
                "NORAD_20002",
                required_seconds=600,
                priority=4,
                stations=["GS_1"],
            ),
        ]
    )
    schedule = solve_schedule(visibility_data, mission_data, deterministic=True)
    evidence = build_conflict_evidence(visibility_data, mission_data, schedule)
    alternatives = rank_alternatives(
        visibility_data,
        mission_data,
        schedule,
        evidence,
        TARGET_ID,
    )
    events = [_flare("M2.3")]

    result = assess_operational_risk(
        visibility_data,
        mission_data,
        schedule,
        evidence,
        TARGET_ID,
        space_weather_events=events,
        space_weather_status={"data_status": "COMPLETE"},
        alternatives_result=alternatives,
    )

    assert result["schedule_status"] == "UNSCHEDULED"
    assert result["assessment_status"] == "UNRESOLVED"
    assert result["risk_score"] is None
    assert result["risk_level"] is None
    assert result["factors"]["scheduling_flexibility"]["points"] == 20
    assert result["factors"]["station_redundancy"]["points"] == 15
    assert result["factors"]["conflict_pressure"]["points"] == 25
    assert result["factors"]["recovery"]["state"] == "DISPLACEMENT_REQUIRED"
    assert result["factors"]["recovery"]["points"] == 16
    assert result["factors"]["space_weather"]["state"] == "NOT_ASSESSED_UNSCHEDULED"
    assert result["reason_codes"] == [
        "SINGLE_FEASIBLE_WINDOW",
        "SINGLE_USABLE_STATION",
        "ANTENNA_RESOURCE_CONFLICT",
        "ALL_FEASIBLE_WINDOWS_BLOCKED",
        "RECOVERY_REQUIRES_DISPLACEMENT",
    ]
