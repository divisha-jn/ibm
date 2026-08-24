"""Generate real, solver-validated alternatives for unscheduled requests."""

from __future__ import annotations

from datetime import datetime

from backend.solver.scheduler import solve_schedule


ALTERNATIVES_FOUND = "ALTERNATIVES_FOUND"
NO_FEASIBLE_ALTERNATIVES = "NO_FEASIBLE_ALTERNATIVES"
REQUEST_ALREADY_SCHEDULED = "REQUEST_ALREADY_SCHEDULED"

_WINDOW_FIELDS = {
    "window_id",
    "satellite_id",
    "station_id",
    "aos",
    "los",
    "duration_seconds",
    "max_elevation_deg",
}
_FEASIBLE_SOLVER_STATUSES = {"OPTIMAL", "FEASIBLE"}


class AlternativesValidationError(ValueError):
    """Raised when the supplied scheduling envelopes are inconsistent."""


class AlternativesEvaluationError(RuntimeError):
    """Raised when the solver cannot conclusively evaluate a candidate."""


def _require_non_empty_string(value, field_name):
    if not isinstance(value, str) or not value or value != value.strip():
        raise AlternativesValidationError(
            f"{field_name} must be a non-empty, trimmed string."
        )
    return value


def _parse_timestamp(value, field_name):
    _require_non_empty_string(value, field_name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AlternativesValidationError(
            f"{field_name} is not a valid ISO-8601 timestamp: {value!r}."
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AlternativesValidationError(
            f"{field_name} must include a timezone: {value!r}."
        )
    return parsed


def _validate_scenario_ids(mission_data, schedule_result, conflict_evidence):
    scenario_id = _require_non_empty_string(
        mission_data.get("scenario_id"), "mission_data.scenario_id"
    )
    for envelope_name, envelope in (
        ("schedule_result", schedule_result),
        ("conflict_evidence", conflict_evidence),
    ):
        other_scenario_id = envelope.get("scenario_id")
        if other_scenario_id is not None and other_scenario_id != scenario_id:
            raise AlternativesValidationError(
                f"{envelope_name}.scenario_id {other_scenario_id!r} does not "
                f"match mission_data.scenario_id {scenario_id!r}."
            )
    return scenario_id


def _validate_requests(mission_data, request_id):
    requests = mission_data.get("requests")
    if not isinstance(requests, list):
        raise AlternativesValidationError("mission_data.requests must be a list.")

    request_lookup = {}
    for index, request in enumerate(requests):
        if not isinstance(request, dict):
            raise AlternativesValidationError(
                f"mission_data.requests[{index}] must be an object."
            )
        current_request_id = _require_non_empty_string(
            request.get("request_id"),
            f"mission_data.requests[{index}].request_id",
        )
        if current_request_id in request_lookup:
            raise AlternativesValidationError(
                f"Duplicate mission request ID: {current_request_id!r}."
            )
        request_lookup[current_request_id] = request

    if request_id not in request_lookup:
        raise AlternativesValidationError(
            f"Unknown mission request ID: {request_id!r}."
        )

    target_request = request_lookup[request_id]
    satellite_id = _require_non_empty_string(
        target_request.get("satellite_id"),
        f"mission request {request_id!r} satellite_id",
    )
    if not satellite_id.startswith("NORAD_"):
        raise AlternativesValidationError(
            f"Mission request {request_id!r} has no canonical NORAD satellite ID: "
            f"{satellite_id!r}."
        )

    required_seconds = target_request.get("required_contact_seconds")
    if (
        isinstance(required_seconds, bool)
        or not isinstance(required_seconds, int)
        or required_seconds <= 0
    ):
        raise AlternativesValidationError(
            f"Mission request {request_id!r} required_contact_seconds must be "
            "a positive integer."
        )

    priority_lookup = {}
    for current_request_id, request in request_lookup.items():
        priority = request.get("priority")
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise AlternativesValidationError(
                f"Mission request {current_request_id!r} priority must be an integer."
            )
        priority_lookup[current_request_id] = priority

    eligible_stations = target_request.get("eligible_station_ids")
    if not isinstance(eligible_stations, list):
        raise AlternativesValidationError(
            f"Mission request {request_id!r} eligible_station_ids must be a list."
        )
    for station_index, station_id in enumerate(eligible_stations):
        _require_non_empty_string(
            station_id,
            f"mission request {request_id!r} eligible_station_ids[{station_index}]",
        )

    return target_request, request_lookup, priority_lookup


def _validate_visibility(visibility_data):
    planning_horizon = visibility_data.get("planning_horizon")
    if not isinstance(planning_horizon, dict):
        raise AlternativesValidationError(
            "visibility_data.planning_horizon must be an object."
        )
    horizon_start = _parse_timestamp(
        planning_horizon.get("start"), "visibility_data.planning_horizon.start"
    )
    horizon_end = _parse_timestamp(
        planning_horizon.get("end"), "visibility_data.planning_horizon.end"
    )
    if horizon_start >= horizon_end:
        raise AlternativesValidationError(
            "visibility_data planning horizon start must be before end."
        )

    windows = visibility_data.get("visibility_windows")
    if not isinstance(windows, list):
        raise AlternativesValidationError(
            "visibility_data.visibility_windows must be a list."
        )

    unique_windows = []
    windows_by_id = {}
    parsed_times = {}
    for index, window in enumerate(windows):
        if not isinstance(window, dict):
            raise AlternativesValidationError(
                f"visibility_windows[{index}] must be an object."
            )
        missing_fields = _WINDOW_FIELDS - set(window)
        if missing_fields:
            raise AlternativesValidationError(
                f"visibility_windows[{index}] is missing fields: "
                f"{sorted(missing_fields)}."
            )

        window_id = _require_non_empty_string(
            window.get("window_id"), f"visibility_windows[{index}].window_id"
        )
        satellite_id = _require_non_empty_string(
            window.get("satellite_id"),
            f"visibility window {window_id!r} satellite_id",
        )
        if not satellite_id.startswith("NORAD_"):
            raise AlternativesValidationError(
                f"Visibility window {window_id!r} has no canonical NORAD "
                f"satellite ID: {satellite_id!r}."
            )
        _require_non_empty_string(
            window.get("station_id"),
            f"visibility window {window_id!r} station_id",
        )

        aos = _parse_timestamp(window.get("aos"), f"window {window_id!r} aos")
        los = _parse_timestamp(window.get("los"), f"window {window_id!r} los")
        if aos >= los:
            raise AlternativesValidationError(
                f"Visibility window {window_id!r} aos must be before los."
            )

        duration_seconds = window.get("duration_seconds")
        if (
            isinstance(duration_seconds, bool)
            or not isinstance(duration_seconds, int)
            or duration_seconds <= 0
        ):
            raise AlternativesValidationError(
                f"Visibility window {window_id!r} duration_seconds must be a "
                "positive integer."
            )
        max_elevation = window.get("max_elevation_deg")
        if isinstance(max_elevation, bool) or not isinstance(max_elevation, (int, float)):
            raise AlternativesValidationError(
                f"Visibility window {window_id!r} max_elevation_deg must be numeric."
            )

        existing = windows_by_id.get(window_id)
        if existing is not None:
            if existing != window:
                raise AlternativesValidationError(
                    f"Conflicting duplicate visibility window ID: {window_id!r}."
                )
            continue

        windows_by_id[window_id] = window
        parsed_times[window_id] = (aos, los)
        unique_windows.append(window)

    return horizon_start, horizon_end, unique_windows, parsed_times


def _schedule_contacts_by_request(schedule_result, priority_lookup):
    contacts = schedule_result.get("scheduled_contacts")
    if not isinstance(contacts, list):
        raise AlternativesValidationError(
            "schedule_result.scheduled_contacts must be a list."
        )

    contacts_by_request = {}
    for index, contact in enumerate(contacts):
        if not isinstance(contact, dict):
            raise AlternativesValidationError(
                f"schedule_result.scheduled_contacts[{index}] must be an object."
            )
        request_id = _require_non_empty_string(
            contact.get("request_id"),
            f"schedule_result.scheduled_contacts[{index}].request_id",
        )
        if request_id not in priority_lookup:
            raise AlternativesValidationError(
                f"Scheduled request {request_id!r} does not exist in mission_data."
            )
        if request_id in contacts_by_request:
            raise AlternativesValidationError(
                f"Request {request_id!r} is scheduled more than once."
            )
        for field_name in (
            "window_id",
            "station_id",
            "scheduled_start",
            "scheduled_end",
        ):
            _require_non_empty_string(
                contact.get(field_name),
                f"scheduled contact {request_id!r} {field_name}",
            )
        contacts_by_request[request_id] = contact
    return contacts_by_request


def _matching_evidence(conflict_evidence, request_id):
    records = conflict_evidence.get("evidence")
    if not isinstance(records, list):
        raise AlternativesValidationError("conflict_evidence.evidence must be a list.")
    matching = [
        record
        for record in records
        if isinstance(record, dict) and record.get("request_id") == request_id
    ]
    if len(matching) != 1:
        raise AlternativesValidationError(
            f"Expected exactly one conflict-evidence record for {request_id!r}; "
            f"found {len(matching)}."
        )
    reason_codes = matching[0].get("reason_codes")
    if (
        not isinstance(reason_codes, list)
        or not reason_codes
        or any(not isinstance(reason, str) or not reason for reason in reason_codes)
    ):
        raise AlternativesValidationError(
            f"Conflict evidence for {request_id!r} has no valid reason_codes."
        )
    return matching[0]


def _base_result(scenario_id, request_id, satellite_id, status, reason_codes):
    return {
        "scenario_id": scenario_id,
        "request_id": request_id,
        "satellite_id": satellite_id,
        "status": status,
        "reason_codes": list(reason_codes),
        "alternatives": [],
    }


def _contact_assignment(contact):
    return (
        contact["window_id"],
        contact["station_id"],
        contact["scheduled_start"],
        contact["scheduled_end"],
    )


def rank_alternatives(
    visibility_data: dict,
    mission_data: dict,
    schedule_result: dict,
    conflict_evidence: dict,
    request_id: str,
    *,
    limit: int = 3,
) -> dict:
    """Return real solver-validated windows ranked by operational disruption."""
    if any(
        not isinstance(envelope, dict)
        for envelope in (
            visibility_data,
            mission_data,
            schedule_result,
            conflict_evidence,
        )
    ):
        raise AlternativesValidationError(
            "visibility, mission, schedule, and evidence inputs must be objects."
        )
    _require_non_empty_string(request_id, "request_id")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise AlternativesValidationError("limit must be a positive integer.")

    scenario_id = _validate_scenario_ids(
        mission_data, schedule_result, conflict_evidence
    )
    target_request, _, priority_lookup = _validate_requests(
        mission_data, request_id
    )
    horizon_start, horizon_end, windows, parsed_times = _validate_visibility(
        visibility_data
    )
    baseline_contacts = _schedule_contacts_by_request(
        schedule_result, priority_lookup
    )
    satellite_id = target_request["satellite_id"]

    if request_id in baseline_contacts:
        return _base_result(
            scenario_id,
            request_id,
            satellite_id,
            REQUEST_ALREADY_SCHEDULED,
            [],
        )

    unscheduled = schedule_result.get("unscheduled_requests")
    if not isinstance(unscheduled, list):
        raise AlternativesValidationError(
            "schedule_result.unscheduled_requests must be a list."
        )
    matching_unscheduled = [
        record
        for record in unscheduled
        if isinstance(record, dict) and record.get("request_id") == request_id
    ]
    if len(matching_unscheduled) != 1:
        raise AlternativesValidationError(
            f"Expected {request_id!r} exactly once in unscheduled_requests; "
            f"found {len(matching_unscheduled)}."
        )

    evidence_record = _matching_evidence(conflict_evidence, request_id)
    reason_codes = evidence_record["reason_codes"]
    result = _base_result(
        scenario_id,
        request_id,
        satellite_id,
        NO_FEASIBLE_ALTERNATIVES,
        reason_codes,
    )

    required_seconds = target_request["required_contact_seconds"]
    eligible_stations = set(target_request["eligible_station_ids"])
    candidates = []
    for window in windows:
        aos, los = parsed_times[window["window_id"]]
        if (
            window["satellite_id"] == satellite_id
            and window["station_id"] in eligible_stations
            and aos >= horizon_start
            and los <= horizon_end
            and int((los - aos).total_seconds()) >= required_seconds
        ):
            candidates.append((window, aos, los))
    candidates.sort(
        key=lambda candidate: (
            candidate[1],
            candidate[0]["station_id"],
            candidate[0]["window_id"],
        )
    )

    target_priority = priority_lookup[request_id]
    protected_request_ids = {
        baseline_request_id
        for baseline_request_id in baseline_contacts
        if priority_lookup[baseline_request_id] > target_priority
    }

    ranked_candidates = []
    for window, window_aos, window_los in candidates:
        try:
            candidate_schedule = solve_schedule(
                visibility_data,
                mission_data,
                required_request_ids=protected_request_ids,
                required_window_by_request={request_id: window["window_id"]},
                deterministic=True,
            )
        except Exception as exc:  # noqa: BLE001
            raise AlternativesEvaluationError(
                f"Solver failed while evaluating request {request_id!r} on "
                f"window {window['window_id']!r}: {exc}"
            ) from exc

        solver_status = candidate_schedule.get("solver", {}).get("status")
        if solver_status == "INFEASIBLE":
            continue
        if solver_status not in _FEASIBLE_SOLVER_STATUSES:
            raise AlternativesEvaluationError(
                f"Solver returned {solver_status!r} while evaluating request "
                f"{request_id!r} on window {window['window_id']!r}."
            )

        candidate_contacts = _schedule_contacts_by_request(
            candidate_schedule, priority_lookup
        )
        target_contact = candidate_contacts.get(request_id)
        if target_contact is None:
            raise AlternativesEvaluationError(
                f"Solver did not schedule forced request {request_id!r}."
            )
        if target_contact["window_id"] != window["window_id"]:
            raise AlternativesEvaluationError(
                f"Solver scheduled {request_id!r} on {target_contact['window_id']!r} "
                f"instead of forced window {window['window_id']!r}."
            )
        if target_contact["station_id"] != window["station_id"]:
            raise AlternativesEvaluationError(
                f"Solver returned the wrong station for forced window "
                f"{window['window_id']!r}."
            )

        scheduled_start = _parse_timestamp(
            target_contact["scheduled_start"],
            f"candidate {window['window_id']!r} scheduled_start",
        )
        scheduled_end = _parse_timestamp(
            target_contact["scheduled_end"],
            f"candidate {window['window_id']!r} scheduled_end",
        )
        if (
            scheduled_start < window_aos
            or scheduled_end > window_los
            or int((scheduled_end - scheduled_start).total_seconds())
            != required_seconds
            or target_contact.get("duration_seconds") != required_seconds
        ):
            raise AlternativesEvaluationError(
                f"Solver returned an invalid interval for request {request_id!r} "
                f"on window {window['window_id']!r}."
            )

        if not protected_request_ids <= set(candidate_contacts):
            continue

        baseline_request_ids = set(baseline_contacts) - {request_id}
        candidate_request_ids = set(candidate_contacts)
        displaced_request_ids = sorted(
            baseline_request_ids - candidate_request_ids
        )
        rescheduled_request_ids = sorted(
            baseline_request_id
            for baseline_request_id in baseline_request_ids & candidate_request_ids
            if _contact_assignment(baseline_contacts[baseline_request_id])
            != _contact_assignment(candidate_contacts[baseline_request_id])
        )

        displaced_priority_total = sum(
            priority_lookup[displaced_request_id]
            for displaced_request_id in displaced_request_ids
        )
        rescheduled_priority_total = sum(
            priority_lookup[rescheduled_request_id]
            for rescheduled_request_id in rescheduled_request_ids
        )
        ranking_metrics = {
            "displaced_count": len(displaced_request_ids),
            "displaced_priority_total": displaced_priority_total,
            "rescheduled_count": len(rescheduled_request_ids),
            "rescheduled_priority_total": rescheduled_priority_total,
        }
        alternative = {
            "rank": 0,
            "alternative_type": "ALTERNATIVE_WINDOW",
            "window_id": window["window_id"],
            "station_id": window["station_id"],
            "scheduled_start": target_contact["scheduled_start"],
            "scheduled_end": target_contact["scheduled_end"],
            "duration_seconds": required_seconds,
            "displaced_request_ids": displaced_request_ids,
            "rescheduled_request_ids": rescheduled_request_ids,
            "ranking_metrics": ranking_metrics,
        }
        ranking_key = (
            ranking_metrics["displaced_count"],
            ranking_metrics["displaced_priority_total"],
            ranking_metrics["rescheduled_count"],
            ranking_metrics["rescheduled_priority_total"],
            window_aos,
            window["station_id"],
            window["window_id"],
        )
        ranked_candidates.append((ranking_key, alternative))

    ranked_candidates.sort(key=lambda item: item[0])
    alternatives = [
        alternative
        for _, alternative in ranked_candidates[:limit]
    ]
    for rank, alternative in enumerate(alternatives, start=1):
        alternative["rank"] = rank

    if alternatives:
        result["status"] = ALTERNATIVES_FOUND
        result["alternatives"] = alternatives
    return result
