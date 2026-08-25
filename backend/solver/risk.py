"""Deterministic P2 Operational Risk Index V1.

The Operational Risk Index is a team-defined 0--100 operational fragility
index.  It is not a probability of mission failure, a prediction of satellite
damage, or a scientifically calibrated reliability percentage.

This module is deliberately pure: callers supply canonical visibility,
mission, schedule, conflict, alternatives, and normalized space-weather data.
It performs no network requests, solver runs, or alternatives re-evaluations.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any


FLEXIBILITY_WEIGHT = 20
STATION_WEIGHT = 15
CONFLICT_WEIGHT = 25
RECOVERY_WEIGHT = 20
PRIORITY_WEIGHT = 10
SPACE_WEATHER_WEIGHT = 10

LOW_MAX = 39
MEDIUM_MAX = 69

_WINDOW_FIELDS = {
    "window_id",
    "satellite_id",
    "station_id",
    "aos",
    "los",
    "duration_seconds",
    "max_elevation_deg",
}
_SCHEDULED_CONTACT_FIELDS = {
    "request_id",
    "satellite_id",
    "station_id",
    "window_id",
    "scheduled_start",
    "scheduled_end",
    "duration_seconds",
}
_FLARE_CLASS_RE = re.compile(r"^([ABCMX])(\d+(?:\.\d+)?)$", re.IGNORECASE)

_RECOVERY_SCORES = {
    "DIRECT": 0.1,
    "RESCHEDULE_REQUIRED": 0.5,
    "DISPLACEMENT_REQUIRED": 0.8,
    "NONE": 1.0,
    "UNKNOWN": 0.5,
    "NOT_APPLICABLE_SCHEDULED": 0.0,
}

_REASON_ORDER = (
    "NO_ELIGIBLE_VISIBILITY_WINDOW",
    "INSUFFICIENT_WINDOW_DURATION",
    "SINGLE_FEASIBLE_WINDOW",
    "SINGLE_USABLE_STATION",
    "ANTENNA_RESOURCE_CONFLICT",
    "PARTIALLY_BLOCKED_FEASIBLE_WINDOWS",
    "ALL_FEASIBLE_WINDOWS_BLOCKED",
    "OPTIMIZATION_TRADEOFF",
    "NO_SOLVER_VALIDATED_ALTERNATIVE",
    "RECOVERY_REQUIRES_RESCHEDULING",
    "RECOVERY_REQUIRES_DISPLACEMENT",
    "SOLAR_FLARE_OVERLAP",
    "GEOMAGNETIC_ACTIVITY_CONTEXT",
    "SPACE_WEATHER_EVENT_INVALID",
    "SPACE_WEATHER_DATA_UNKNOWN",
)


class OperationalRiskValidationError(ValueError):
    """Raised when supplied risk inputs are malformed or inconsistent."""


def _require_mapping(value: Any, field_name: str) -> dict:
    if not isinstance(value, dict):
        raise OperationalRiskValidationError(f"{field_name} must be an object.")
    return value


def _require_list(value: Any, field_name: str) -> list:
    if not isinstance(value, list):
        raise OperationalRiskValidationError(f"{field_name} must be a list.")
    return value


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise OperationalRiskValidationError(
            f"{field_name} must be a non-empty, trimmed string."
        )
    return value


def _require_positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise OperationalRiskValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _parse_timestamp(value: Any, field_name: str) -> datetime:
    _require_string(value, field_name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OperationalRiskValidationError(
            f"{field_name} is not a valid ISO-8601 timestamp: {value!r}."
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OperationalRiskValidationError(
            f"{field_name} must include a timezone: {value!r}."
        )
    return parsed


def _validate_scenarios(
    mission_data: dict,
    schedule_result: dict,
    conflict_evidence: dict,
    alternatives_result: dict | None,
) -> str:
    scenario_id = _require_string(
        mission_data.get("scenario_id"), "mission_data.scenario_id"
    )
    envelopes = [
        ("schedule_result", schedule_result),
        ("conflict_evidence", conflict_evidence),
    ]
    if alternatives_result is not None:
        envelopes.append(("alternatives_result", alternatives_result))
    for name, envelope in envelopes:
        other_id = envelope.get("scenario_id")
        if other_id is not None and other_id != scenario_id:
            raise OperationalRiskValidationError(
                f"{name}.scenario_id {other_id!r} does not match "
                f"mission_data.scenario_id {scenario_id!r}."
            )
    return scenario_id


def _validate_target_request(mission_data: dict, request_id: str) -> dict:
    _require_string(request_id, "request_id")
    requests = _require_list(mission_data.get("requests"), "mission_data.requests")
    request_ids = []
    matching = []
    for index, request in enumerate(requests):
        _require_mapping(request, f"mission_data.requests[{index}]")
        current_id = _require_string(
            request.get("request_id"), f"mission_data.requests[{index}].request_id"
        )
        request_ids.append(current_id)
        if current_id == request_id:
            matching.append(request)

    duplicates = sorted(
        current_id for current_id in set(request_ids) if request_ids.count(current_id) > 1
    )
    if duplicates:
        raise OperationalRiskValidationError(
            f"Duplicate mission request IDs: {duplicates}."
        )
    if len(matching) != 1:
        raise OperationalRiskValidationError(
            f"Expected request {request_id!r} exactly once in mission_data; "
            f"found {len(matching)}."
        )

    request = matching[0]
    satellite_id = _require_string(
        request.get("satellite_id"), f"mission request {request_id!r} satellite_id"
    )
    if not satellite_id.startswith("NORAD_"):
        raise OperationalRiskValidationError(
            f"Mission request {request_id!r} has no canonical NORAD satellite ID: "
            f"{satellite_id!r}."
        )
    _require_positive_int(
        request.get("required_contact_seconds"),
        f"mission request {request_id!r} required_contact_seconds",
    )
    priority = request.get("priority")
    if (
        isinstance(priority, bool)
        or not isinstance(priority, int)
        or not 1 <= priority <= 10
    ):
        raise OperationalRiskValidationError(
            f"Mission request {request_id!r} priority must be an integer from 1 to 10."
        )
    station_ids = _require_list(
        request.get("eligible_station_ids"),
        f"mission request {request_id!r} eligible_station_ids",
    )
    for index, station_id in enumerate(station_ids):
        _require_string(
            station_id,
            f"mission request {request_id!r} eligible_station_ids[{index}]",
        )
    mandatory = request.get("mandatory")
    if mandatory is not None and not isinstance(mandatory, bool):
        raise OperationalRiskValidationError(
            f"Mission request {request_id!r} mandatory must be boolean when present."
        )
    return request


def _validate_visibility(visibility_data: dict) -> tuple[datetime, datetime, list[dict]]:
    planning = _require_mapping(
        visibility_data.get("planning_horizon"), "visibility_data.planning_horizon"
    )
    horizon_start = _parse_timestamp(
        planning.get("start"), "visibility_data.planning_horizon.start"
    )
    horizon_end = _parse_timestamp(
        planning.get("end"), "visibility_data.planning_horizon.end"
    )
    if horizon_start >= horizon_end:
        raise OperationalRiskValidationError(
            "visibility_data planning horizon start must be before end."
        )

    windows = _require_list(
        visibility_data.get("visibility_windows"),
        "visibility_data.visibility_windows",
    )
    by_id: dict[str, dict] = {}
    validated: list[dict] = []
    for index, window in enumerate(windows):
        _require_mapping(window, f"visibility_windows[{index}]")
        missing = _WINDOW_FIELDS - set(window)
        if missing:
            raise OperationalRiskValidationError(
                f"visibility_windows[{index}] is missing fields: {sorted(missing)}."
            )
        window_id = _require_string(
            window.get("window_id"), f"visibility_windows[{index}].window_id"
        )
        satellite_id = _require_string(
            window.get("satellite_id"), f"window {window_id!r} satellite_id"
        )
        if not satellite_id.startswith("NORAD_"):
            raise OperationalRiskValidationError(
                f"Visibility window {window_id!r} has no canonical NORAD "
                f"satellite ID: {satellite_id!r}."
            )
        _require_string(window.get("station_id"), f"window {window_id!r} station_id")
        aos = _parse_timestamp(window.get("aos"), f"window {window_id!r} aos")
        los = _parse_timestamp(window.get("los"), f"window {window_id!r} los")
        if aos >= los:
            raise OperationalRiskValidationError(
                f"Visibility window {window_id!r} aos must be before los."
            )
        _require_positive_int(
            window.get("duration_seconds"), f"window {window_id!r} duration_seconds"
        )
        elevation = window.get("max_elevation_deg")
        if isinstance(elevation, bool) or not isinstance(elevation, (int, float)):
            raise OperationalRiskValidationError(
                f"Window {window_id!r} max_elevation_deg must be numeric."
            )

        previous = by_id.get(window_id)
        if previous is not None:
            if previous != window:
                raise OperationalRiskValidationError(
                    f"Conflicting duplicate visibility window ID: {window_id!r}."
                )
            continue
        copied = dict(window)
        copied["_aos"] = aos
        copied["_los"] = los
        by_id[window_id] = window
        validated.append(copied)

    validated.sort(key=lambda item: (item["_aos"], item["station_id"], item["window_id"]))
    return horizon_start, horizon_end, validated


def _validate_schedule(
    schedule_result: dict,
    request: dict,
    windows: list[dict],
) -> tuple[str, dict | None, list[dict]]:
    scheduled = _require_list(
        schedule_result.get("scheduled_contacts"),
        "schedule_result.scheduled_contacts",
    )
    unscheduled = _require_list(
        schedule_result.get("unscheduled_requests"),
        "schedule_result.unscheduled_requests",
    )

    parsed_contacts = []
    target_contacts = []
    seen_scheduled_ids = set()
    windows_by_id = {window["window_id"]: window for window in windows}
    for index, contact in enumerate(scheduled):
        _require_mapping(contact, f"scheduled_contacts[{index}]")
        missing = _SCHEDULED_CONTACT_FIELDS - set(contact)
        if missing:
            raise OperationalRiskValidationError(
                f"scheduled_contacts[{index}] is missing fields: {sorted(missing)}."
            )
        contact_request_id = _require_string(
            contact.get("request_id"), f"scheduled_contacts[{index}].request_id"
        )
        if contact_request_id in seen_scheduled_ids:
            raise OperationalRiskValidationError(
                f"Request {contact_request_id!r} is scheduled more than once."
            )
        seen_scheduled_ids.add(contact_request_id)
        station_id = _require_string(
            contact.get("station_id"),
            f"scheduled contact {contact_request_id!r} station_id",
        )
        window_id = _require_string(
            contact.get("window_id"),
            f"scheduled contact {contact_request_id!r} window_id",
        )
        start = _parse_timestamp(
            contact.get("scheduled_start"),
            f"scheduled contact {contact_request_id!r} scheduled_start",
        )
        end = _parse_timestamp(
            contact.get("scheduled_end"),
            f"scheduled contact {contact_request_id!r} scheduled_end",
        )
        if start >= end:
            raise OperationalRiskValidationError(
                f"Scheduled contact {contact_request_id!r} start must be before end."
            )
        duration = _require_positive_int(
            contact.get("duration_seconds"),
            f"scheduled contact {contact_request_id!r} duration_seconds",
        )
        if duration != int((end - start).total_seconds()):
            raise OperationalRiskValidationError(
                f"Scheduled contact {contact_request_id!r} duration_seconds does not "
                "match its timestamps."
            )
        parsed = dict(contact)
        parsed["_start"] = start
        parsed["_end"] = end
        parsed_contacts.append(parsed)

        if contact_request_id == request["request_id"]:
            if contact.get("satellite_id") != request["satellite_id"]:
                raise OperationalRiskValidationError(
                    f"Scheduled contact {contact_request_id!r} satellite_id does not "
                    "match mission_data."
                )
            if duration != request["required_contact_seconds"]:
                raise OperationalRiskValidationError(
                    f"Scheduled contact {contact_request_id!r} duration does not match "
                    "required_contact_seconds."
                )
            window = windows_by_id.get(window_id)
            if window is None:
                raise OperationalRiskValidationError(
                    f"Scheduled contact {contact_request_id!r} references unknown "
                    f"window {window_id!r}."
                )
            if (
                window["satellite_id"] != request["satellite_id"]
                or window["station_id"] != station_id
                or start < window["_aos"]
                or end > window["_los"]
            ):
                raise OperationalRiskValidationError(
                    f"Scheduled contact {contact_request_id!r} is inconsistent with "
                    f"window {window_id!r}."
                )
            target_contacts.append(parsed)

    target_unscheduled = []
    seen_unscheduled_ids = set()
    for index, record in enumerate(unscheduled):
        _require_mapping(record, f"unscheduled_requests[{index}]")
        current_id = _require_string(
            record.get("request_id"), f"unscheduled_requests[{index}].request_id"
        )
        if current_id in seen_unscheduled_ids:
            raise OperationalRiskValidationError(
                f"Request {current_id!r} is unscheduled more than once."
            )
        seen_unscheduled_ids.add(current_id)
        if current_id == request["request_id"]:
            if record.get("satellite_id") not in (None, request["satellite_id"]):
                raise OperationalRiskValidationError(
                    f"Unscheduled request {current_id!r} satellite_id does not match "
                    "mission_data."
                )
            target_unscheduled.append(record)

    if target_contacts and target_unscheduled:
        raise OperationalRiskValidationError(
            f"Request {request['request_id']!r} is both scheduled and unscheduled."
        )
    if len(target_contacts) == 1:
        return "SCHEDULED", target_contacts[0], parsed_contacts
    if len(target_unscheduled) == 1:
        return "UNSCHEDULED", None, parsed_contacts
    raise OperationalRiskValidationError(
        f"Request {request['request_id']!r} must appear exactly once in either "
        "scheduled_contacts or unscheduled_requests."
    )


def _matching_conflict_record(
    conflict_evidence: dict,
    request_id: str,
    schedule_status: str,
) -> dict | None:
    records = _require_list(
        conflict_evidence.get("evidence"), "conflict_evidence.evidence"
    )
    matching = [
        record
        for record in records
        if isinstance(record, dict) and record.get("request_id") == request_id
    ]
    if schedule_status == "UNSCHEDULED" and len(matching) != 1:
        raise OperationalRiskValidationError(
            f"Expected exactly one conflict-evidence record for unscheduled request "
            f"{request_id!r}; found {len(matching)}."
        )
    if schedule_status == "SCHEDULED" and matching:
        raise OperationalRiskValidationError(
            f"Scheduled request {request_id!r} unexpectedly has conflict evidence."
        )
    if not matching:
        return None
    record = matching[0]
    reasons = _require_list(
        record.get("reason_codes"),
        f"conflict evidence for {request_id!r} reason_codes",
    )
    if not reasons or any(not isinstance(reason, str) or not reason for reason in reasons):
        raise OperationalRiskValidationError(
            f"Conflict evidence for {request_id!r} has invalid reason_codes."
        )
    _require_list(
        record.get("conflicts", []),
        f"conflict evidence for {request_id!r} conflicts",
    )
    return record


def _duration_feasible_windows(
    request: dict,
    windows: list[dict],
    horizon_start: datetime,
    horizon_end: datetime,
) -> tuple[list[dict], list[dict]]:
    eligible_stations = set(request["eligible_station_ids"])
    eligible = [
        window
        for window in windows
        if window["satellite_id"] == request["satellite_id"]
        and window["station_id"] in eligible_stations
        and window["_aos"] >= horizon_start
        and window["_los"] <= horizon_end
    ]
    required = request["required_contact_seconds"]
    feasible = [
        window
        for window in eligible
        if int((window["_los"] - window["_aos"]).total_seconds()) >= required
    ]
    return eligible, feasible


def _flexibility_factor(
    eligible: list[dict], feasible: list[dict], required_seconds: int
) -> tuple[dict, list[str]]:
    count = len(feasible)
    if count <= 1:
        factor_score = 1.0
    elif count == 2:
        factor_score = 0.6
    elif count == 3:
        factor_score = 0.35
    else:
        factor_score = 0.15
    points = round(FLEXIBILITY_WEIGHT * factor_score)
    total_seconds = sum(
        int((window["_los"] - window["_aos"]).total_seconds())
        for window in feasible
    )
    total_slack = sum(
        int((window["_los"] - window["_aos"]).total_seconds()) - required_seconds
        for window in feasible
    )
    reasons = []
    if not eligible:
        reasons.append("NO_ELIGIBLE_VISIBILITY_WINDOW")
    elif not feasible:
        reasons.append("INSUFFICIENT_WINDOW_DURATION")
    elif count == 1:
        reasons.append("SINGLE_FEASIBLE_WINDOW")
    return (
        {
            "weight": FLEXIBILITY_WEIGHT,
            "factor_score": factor_score,
            "points": points,
            "metrics": {
                "duration_feasible_window_count": count,
                "total_feasible_visibility_seconds": total_seconds,
                "total_start_slack_seconds": total_slack,
            },
        },
        reasons,
    )


def _station_factor(feasible: list[dict]) -> tuple[dict, list[str]]:
    stations = sorted({window["station_id"] for window in feasible})
    count = len(stations)
    if count <= 1:
        factor_score = 1.0
    elif count == 2:
        factor_score = 0.5
    else:
        factor_score = 0.2
    points = round(STATION_WEIGHT * factor_score)
    reasons = ["SINGLE_USABLE_STATION"] if count == 1 else []
    return (
        {
            "weight": STATION_WEIGHT,
            "factor_score": factor_score,
            "points": points,
            "metrics": {
                "usable_station_count": count,
                "usable_station_ids": stations,
            },
        },
        reasons,
    )


def _free_segments(
    window_start: datetime,
    window_end: datetime,
    contacts: list[dict],
) -> list[tuple[datetime, datetime]]:
    blocked = []
    for contact in contacts:
        start = max(window_start, contact["_start"])
        end = min(window_end, contact["_end"])
        if start < end:
            blocked.append((start, end))
    blocked.sort(key=lambda interval: interval[0])

    merged: list[list[datetime]] = []
    for start, end in blocked:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)

    free = []
    cursor = window_start
    for start, end in merged:
        if cursor < start:
            free.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < window_end:
        free.append((cursor, window_end))
    return free


def _conflict_factor(
    request: dict,
    feasible: list[dict],
    scheduled_contacts: list[dict],
) -> tuple[dict, list[str]]:
    required = request["required_contact_seconds"]
    blocked_window_ids = []
    conflicting_ids = set()
    for window in feasible:
        station_contacts = [
            contact
            for contact in scheduled_contacts
            if contact["station_id"] == window["station_id"]
            and contact["request_id"] != request["request_id"]
        ]
        overlapping = [
            contact
            for contact in station_contacts
            if max(window["_aos"], contact["_start"])
            < min(window["_los"], contact["_end"])
        ]
        conflicting_ids.update(contact["request_id"] for contact in overlapping)
        free = _free_segments(window["_aos"], window["_los"], station_contacts)
        max_free = max(
            (int((end - start).total_seconds()) for start, end in free),
            default=0,
        )
        if max_free < required:
            blocked_window_ids.append(window["window_id"])

    feasible_count = len(feasible)
    blocked_count = len(blocked_window_ids)
    blocked_fraction = blocked_count / feasible_count if feasible_count else 1.0
    factor_score = blocked_fraction
    points = round(CONFLICT_WEIGHT * factor_score)
    reasons = []
    if blocked_count:
        reasons.append("ANTENNA_RESOURCE_CONFLICT")
        if blocked_count == feasible_count:
            reasons.append("ALL_FEASIBLE_WINDOWS_BLOCKED")
        else:
            reasons.append("PARTIALLY_BLOCKED_FEASIBLE_WINDOWS")
    return (
        {
            "weight": CONFLICT_WEIGHT,
            "factor_score": factor_score,
            "points": points,
            "metrics": {
                "blocked_window_count": blocked_count,
                "duration_feasible_window_count": feasible_count,
                "blocked_window_fraction": blocked_fraction,
                "blocked_window_ids": sorted(blocked_window_ids),
                "conflicting_request_ids": sorted(conflicting_ids),
            },
        },
        reasons,
    )


def _classify_recovery(
    schedule_status: str,
    alternatives_result: dict | None,
    scenario_id: str,
    request: dict,
) -> tuple[dict, list[str]]:
    if schedule_status == "SCHEDULED":
        state = "NOT_APPLICABLE_SCHEDULED"
        best_alternative = None
    elif alternatives_result is None:
        state = "UNKNOWN"
        best_alternative = None
    else:
        _require_mapping(alternatives_result, "alternatives_result")
        if alternatives_result.get("scenario_id") not in (None, scenario_id):
            raise OperationalRiskValidationError(
                "alternatives_result scenario does not match mission_data."
            )
        if alternatives_result.get("request_id") != request["request_id"]:
            raise OperationalRiskValidationError(
                "alternatives_result.request_id does not match the target request."
            )
        if alternatives_result.get("satellite_id") not in (
            None,
            request["satellite_id"],
        ):
            raise OperationalRiskValidationError(
                "alternatives_result.satellite_id does not match the target request."
            )
        status = alternatives_result.get("status")
        if status == "NO_FEASIBLE_ALTERNATIVES":
            state = "NONE"
            best_alternative = None
        elif status == "ALTERNATIVES_FOUND":
            alternatives = _require_list(
                alternatives_result.get("alternatives"),
                "alternatives_result.alternatives",
            )
            if not alternatives:
                raise OperationalRiskValidationError(
                    "ALTERNATIVES_FOUND requires at least one alternative."
                )
            for index, alternative in enumerate(alternatives):
                _require_mapping(alternative, f"alternatives[{index}]")
                _require_positive_int(
                    alternative.get("rank"), f"alternatives[{index}].rank"
                )
            best_alternative = min(alternatives, key=lambda item: item["rank"])
            displaced = _require_list(
                best_alternative.get("displaced_request_ids", []),
                "best alternative displaced_request_ids",
            )
            rescheduled = _require_list(
                best_alternative.get("rescheduled_request_ids", []),
                "best alternative rescheduled_request_ids",
            )
            if displaced:
                state = "DISPLACEMENT_REQUIRED"
            elif rescheduled:
                state = "RESCHEDULE_REQUIRED"
            else:
                state = "DIRECT"
        elif status in ("PIPELINE_UNAVAILABLE", None):
            state = "UNKNOWN"
            best_alternative = None
        elif status == "REQUEST_ALREADY_SCHEDULED":
            raise OperationalRiskValidationError(
                "An unscheduled target cannot have REQUEST_ALREADY_SCHEDULED "
                "alternatives status."
            )
        else:
            raise OperationalRiskValidationError(
                f"Unsupported alternatives_result.status: {status!r}."
            )

    factor_score = _RECOVERY_SCORES[state]
    points = round(RECOVERY_WEIGHT * factor_score)
    reasons = []
    if state == "NONE":
        reasons.append("NO_SOLVER_VALIDATED_ALTERNATIVE")
    elif state == "RESCHEDULE_REQUIRED":
        reasons.append("RECOVERY_REQUIRES_RESCHEDULING")
    elif state == "DISPLACEMENT_REQUIRED":
        reasons.append("RECOVERY_REQUIRES_DISPLACEMENT")
    return (
        {
            "weight": RECOVERY_WEIGHT,
            "state": state,
            "factor_score": factor_score,
            "points": points,
            "best_alternative": copy.deepcopy(best_alternative),
        },
        reasons,
    )


def _priority_factor(request: dict) -> dict:
    priority = request["priority"]
    factor_score = max(0.0, min(priority / 10.0, 1.0))
    return {
        "weight": PRIORITY_WEIGHT,
        "factor_score": factor_score,
        "points": round(PRIORITY_WEIGHT * factor_score),
        "metrics": {
            "priority": priority,
            "approved_scale_min": 1,
            "approved_scale_max": 10,
            "meaning": "OPERATIONAL_CONSEQUENCE",
            "mandatory_included": False,
        },
    }


def _weather_status(status: dict | None) -> str:
    if status is None:
        return "UNKNOWN"
    _require_mapping(status, "space_weather_status")
    direct = status.get("data_status", status.get("status"))
    if isinstance(direct, str):
        normalized = direct.upper()
        if normalized in {"COMPLETE", "PARTIAL", "UNAVAILABLE", "UNKNOWN"}:
            return normalized

    event_types = status.get("event_types")
    if isinstance(event_types, dict):
        values = []
        for event_type in ("solar_flare", "geomagnetic_storm"):
            value = event_types.get(event_type)
            if isinstance(value, dict):
                value = value.get("status")
            if isinstance(value, str):
                values.append(value.upper())
        if len(values) == 2 and all(value == "COMPLETE" for value in values):
            return "COMPLETE"
        if values and all(value == "UNAVAILABLE" for value in values):
            return "UNAVAILABLE"
        if values:
            return "PARTIAL"
    return "UNKNOWN"


def _safe_event_time(event: dict, field: str) -> datetime | None:
    value = event.get(field)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _event_sort_key(event: dict) -> tuple[str, str, str]:
    return (
        str(event.get("start_time") or ""),
        str(event.get("event_type") or ""),
        str(event.get("event_id") or ""),
    )


def _flare_factor_score(class_type: Any) -> float | None:
    if not isinstance(class_type, str):
        return None
    match = _FLARE_CLASS_RE.fullmatch(class_type.strip())
    if match is None:
        return None
    class_letter = match.group(1).upper()
    if class_letter == "C":
        return 0.2
    if class_letter == "M":
        return 0.6
    if class_letter == "X":
        return 1.0
    return 0.0


def _space_weather_factor(
    events: list[dict] | None,
    status: dict | None,
    schedule_status: str,
    contact: dict | None,
    horizon_start: datetime,
    horizon_end: datetime,
) -> tuple[dict, list[str]]:
    if events is None:
        events = []
    _require_list(events, "space_weather_events")
    quality = _weather_status(status)
    matched_events = []
    context_events = []
    invalid_event = False
    flare_scores = []
    reasons = []

    for event in events:
        if not isinstance(event, dict):
            invalid_event = True
            continue
        event_type = event.get("event_type")
        if event_type == "solar_flare":
            start = _safe_event_time(event, "start_time")
            end = _safe_event_time(event, "end_time")
            if start is None or end is None or start >= end:
                invalid_event = True
                continue
            if (
                schedule_status == "SCHEDULED"
                and contact is not None
                and start < contact["_end"]
                and end > contact["_start"]
            ):
                matched_events.append(copy.deepcopy(event))
                reasons.append("SOLAR_FLARE_OVERLAP")
                class_score = _flare_factor_score(event.get("class_type"))
                if class_score is None:
                    invalid_event = True
                    class_score = 0.5
                flare_scores.append(class_score)
        elif event_type == "geomagnetic_storm":
            start = _safe_event_time(event, "start_time")
            if start is None:
                invalid_event = True
                continue
            kp = event.get("max_kp_index")
            if kp is not None and (
                isinstance(kp, bool) or not isinstance(kp, (int, float)) or not 0 <= kp <= 9
            ):
                invalid_event = True
            if horizon_start <= start <= horizon_end:
                context_events.append(copy.deepcopy(event))
                reasons.append("GEOMAGNETIC_ACTIVITY_CONTEXT")
        else:
            invalid_event = True

    matched_events.sort(key=_event_sort_key)
    context_events.sort(key=_event_sort_key)
    if invalid_event:
        reasons.append("SPACE_WEATHER_EVENT_INVALID")

    if schedule_status != "SCHEDULED":
        state = "NOT_ASSESSED_UNSCHEDULED"
        factor_score = None
        points = None
    elif flare_scores:
        factor_score = max(flare_scores)
        state = "SOLAR_FLARE_OVERLAP"
        points = round(SPACE_WEATHER_WEIGHT * factor_score)
    elif quality == "COMPLETE" and not invalid_event:
        factor_score = 0.0
        state = "CLEAR" if not events else "NO_CONTACT_RELEVANT_FLARE"
        points = 0
    else:
        factor_score = 0.5
        state = "UNKNOWN"
        points = round(SPACE_WEATHER_WEIGHT * factor_score)

    if quality != "COMPLETE":
        reasons.append("SPACE_WEATHER_DATA_UNKNOWN")
    if invalid_event and schedule_status == "SCHEDULED" and not flare_scores:
        factor_score = 0.5
        state = "UNKNOWN"
        points = round(SPACE_WEATHER_WEIGHT * factor_score)

    effective_quality = "PARTIAL" if invalid_event and quality == "COMPLETE" else quality
    return (
        {
            "weight": SPACE_WEATHER_WEIGHT,
            "status": effective_quality,
            "state": state,
            "factor_score": factor_score,
            "points": points,
            "matched_events": matched_events,
            "context_events": context_events,
        },
        reasons,
    )


def _ordered_reasons(reasons: list[str]) -> list[str]:
    unique = set(reasons)
    ordered = [reason for reason in _REASON_ORDER if reason in unique]
    ordered.extend(sorted(unique - set(_REASON_ORDER)))
    return ordered


def _risk_level(score: int) -> str:
    if score <= LOW_MAX:
        return "LOW"
    if score <= MEDIUM_MAX:
        return "MEDIUM"
    return "HIGH"


def assess_operational_risk(
    visibility_data: dict,
    mission_data: dict,
    schedule_result: dict,
    conflict_evidence: dict,
    request_id: str,
    *,
    space_weather_events: list[dict] | None = None,
    space_weather_status: dict | None = None,
    alternatives_result: dict | None = None,
) -> dict:
    """Assess one request using the approved Operational Risk Index V1 policy.

    Scheduled requests receive an integer 0--100 index and LOW/MEDIUM/HIGH
    level.  Unscheduled requests receive structured unresolved/conflict and
    recovery evidence, but no score or level.

    All inputs are treated as immutable.  This function performs no I/O.
    """
    for name, envelope in (
        ("visibility_data", visibility_data),
        ("mission_data", mission_data),
        ("schedule_result", schedule_result),
        ("conflict_evidence", conflict_evidence),
    ):
        _require_mapping(envelope, name)
    if alternatives_result is not None:
        _require_mapping(alternatives_result, "alternatives_result")

    scenario_id = _validate_scenarios(
        mission_data, schedule_result, conflict_evidence, alternatives_result
    )
    request = _validate_target_request(mission_data, request_id)
    horizon_start, horizon_end, windows = _validate_visibility(visibility_data)
    schedule_status, contact, scheduled_contacts = _validate_schedule(
        schedule_result, request, windows
    )
    conflict_record = _matching_conflict_record(
        conflict_evidence, request_id, schedule_status
    )

    eligible, feasible = _duration_feasible_windows(
        request, windows, horizon_start, horizon_end
    )
    flexibility, reasons = _flexibility_factor(
        eligible, feasible, request["required_contact_seconds"]
    )
    station, station_reasons = _station_factor(feasible)
    reasons.extend(station_reasons)
    conflict, conflict_reasons = _conflict_factor(
        request, feasible, scheduled_contacts
    )
    reasons.extend(conflict_reasons)
    recovery, recovery_reasons = _classify_recovery(
        schedule_status, alternatives_result, scenario_id, request
    )
    reasons.extend(recovery_reasons)
    priority = _priority_factor(request)
    weather, weather_reasons = _space_weather_factor(
        space_weather_events,
        space_weather_status,
        schedule_status,
        contact,
        horizon_start,
        horizon_end,
    )
    reasons.extend(weather_reasons)

    if conflict_record is not None:
        reasons.extend(conflict_record["reason_codes"])
    if alternatives_result is not None:
        alternative_reasons = alternatives_result.get("reason_codes", [])
        if isinstance(alternative_reasons, list):
            reasons.extend(
                reason for reason in alternative_reasons if isinstance(reason, str)
            )

    factors = {
        "scheduling_flexibility": flexibility,
        "station_redundancy": station,
        "conflict_pressure": conflict,
        "recovery": recovery,
        "mission_priority": priority,
        "space_weather": weather,
    }

    if schedule_status == "SCHEDULED":
        factor_points = [
            flexibility["points"],
            station["points"],
            conflict["points"],
            recovery["points"],
            priority["points"],
            weather["points"],
        ]
        score = max(0, min(100, int(sum(factor_points))))
        assessment_status = "ASSESSED"
        level = _risk_level(score)
        public_contact = {
            "station_id": contact["station_id"],
            "window_id": contact["window_id"],
            "scheduled_start": contact["scheduled_start"],
            "scheduled_end": contact["scheduled_end"],
        }
    else:
        score = None
        level = None
        assessment_status = "UNRESOLVED"
        public_contact = None

    overall_quality = "COMPLETE" if weather["status"] == "COMPLETE" else "PARTIAL"
    result = {
        "scenario_id": scenario_id,
        "request_id": request_id,
        "satellite_id": request["satellite_id"],
        "schedule_status": schedule_status,
        "assessment_status": assessment_status,
        "contact": public_contact,
        "risk_score": score,
        "risk_level": level,
        "reason_codes": _ordered_reasons(reasons),
        "factors": factors,
        "data_quality": {
            "overall": overall_quality,
            "space_weather": weather["status"],
        },
    }
    if schedule_status == "UNSCHEDULED":
        result["conflict_evidence"] = copy.deepcopy(conflict_record)
    return result
