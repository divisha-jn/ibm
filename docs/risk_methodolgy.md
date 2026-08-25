# P2 Operational Risk Index V1

## Definition

The Operational Risk Index is a deterministic, team-defined operational
fragility index for one mission request. A scheduled request receives an
integer score from 0 to 100 plus a `LOW`, `MEDIUM`, or `HIGH` level.

The index is **not**:

- a probability of mission failure;
- a prediction of satellite damage;
- a scientifically calibrated reliability percentage; or
- AI-generated judgment.

The weights and thresholds below are explicit hackathon product-policy
choices. P2 returns structured factors and evidence; P3 owns natural-language
explanations.

## Public P2 function

```python
assess_operational_risk(
    visibility_data,
    mission_data,
    schedule_result,
    conflict_evidence,
    request_id,
    *,
    space_weather_events=None,
    space_weather_status=None,
    alternatives_result=None,
)
```

The function is pure and deterministic. It performs no network access, NASA
fetch, scheduler solve, alternatives rerun, or file write, and it does not
mutate supplied inputs.

## Formula

For a scheduled request:

```text
Operational Risk Index =
    scheduling_flexibility_points
  + ground_station_redundancy_points
  + conflict_pressure_points
  + recovery_difficulty_points
  + mission_priority_points
  + space_weather_points
```

Each contribution uses Python's `round(weight * factor_score)`. The sum is
clamped to the inclusive range 0--100.

| Factor | Maximum points | Weight |
|---|---:|---:|
| Scheduling flexibility | 20 | 20% |
| Ground-station redundancy | 15 | 15% |
| Conflict pressure | 25 | 25% |
| Recovery difficulty | 20 | 20% |
| Mission priority/consequence | 10 | 10% |
| Space weather | 10 | 10% |
| **Total** | **100** | **100%** |

Risk levels are product-policy bands, not probabilities:

| Score | Level |
|---:|---|
| 0--39 | `LOW` |
| 40--69 | `MEDIUM` |
| 70--100 | `HIGH` |

## Canonical duration-feasible windows

A visibility window is considered for the target when all of the following
are true:

- its `satellite_id` equals the request satellite;
- its `station_id` occurs in the request's `eligible_station_ids`;
- it lies completely inside the canonical planning horizon; and
- actual `los - aos` is at least `required_contact_seconds`.

Actual timestamps are authoritative for feasibility. The supplied
`duration_seconds` is validated as positive but is not trusted as the duration
calculation because P1's whole-second timestamp serialization can differ from
the original duration by one second.

Identical duplicate window IDs are collapsed. Conflicting records sharing one
window ID are rejected.

## Factor 1: scheduling flexibility (20 points)

Let `N` be the number of unique duration-feasible windows.

| N | Factor score | Points |
|---:|---:|---:|
| 0 | 1.00 | 20 |
| 1 | 1.00 | 20 |
| 2 | 0.60 | 12 |
| 3 | 0.35 | 7 |
| 4 or more | 0.15 | 3 |

Returned metrics:

- `duration_feasible_window_count`
- `total_feasible_visibility_seconds`, using actual timestamp durations
- `total_start_slack_seconds`, the sum of `window duration - required duration`

Slack is evidence, not a second weighted factor.

## Factor 2: ground-station redundancy (15 points)

Let `S` be the number of distinct station IDs among duration-feasible windows.
An eligible station with no real duration-feasible window does not count.

| S | Factor score | Points |
|---:|---:|---:|
| 0 | 1.00 | 15 |
| 1 | 1.00 | 15 |
| 2 | 0.50 | 8 |
| 3 or more | 0.20 | 3 |

## Factor 3: conflict pressure (25 points)

For every duration-feasible window, P2 examines scheduled contacts at the
same station, excluding the target request's own contact. Overlapping occupied
segments are merged using the same semantics as the existing conflict engine.
A window is blocked when its longest remaining free segment is shorter than
the target's required duration.

```text
blocked_window_fraction =
    blocked duration-feasible windows / duration-feasible windows

factor_score = blocked_window_fraction
points = round(25 * factor_score)
```

When there are no duration-feasible windows, the factor score is 1.0. Conflict
count and competing priorities are returned as evidence but do not add extra
weighted points.

## Factor 4: recovery difficulty (20 points)

P2 consumes a supplied `alternatives_result`; risk never calls
`rank_alternatives()` itself. The best alternative is the lowest numbered
rank. Returned alternative count is not scored because it is capped by the
request's `limit`.

| Recovery state | Definition | Factor score | Points |
|---|---|---:|---:|
| `DIRECT` | No displacement or rescheduling | 0.10 | 2 |
| `RESCHEDULE_REQUIRED` | Rescheduling but no displacement | 0.50 | 10 |
| `DISPLACEMENT_REQUIRED` | At least one displacement | 0.80 | 16 |
| `NONE` | `NO_FEASIBLE_ALTERNATIVES` | 1.00 | 20 |
| `UNKNOWN` | No usable alternatives result | 0.50 | 10 |
| `NOT_APPLICABLE_SCHEDULED` | Normal scheduled V1 contact | 0.00 | 0 |

Unscheduled requests expose recovery classification but receive no overall
index.

## Factor 5: mission priority (10 points)

Current mission data and tests consistently use integer priority values within
1--10 (observed repository values are 4--10). V1 validates the approved 1--10
range.

```text
factor_score = priority / 10
points = round(10 * factor_score)
```

Higher priority represents operational consequence and attention. It does not
mean higher probability of scheduling failure. `mandatory` is not included
because the current scheduler does not enforce mandatory semantics.

## Factor 6: space weather (10 points)

P2 consumes normalized P1 events supplied by orchestration. It never calls
NASA or `fetch_space_weather_events()`.

### Solar flares

A flare is contact-relevant only when both timestamps are valid and its
half-open interval overlaps the scheduled contact:

```text
flare.start_time < scheduled_end
and flare.end_time > scheduled_start
```

| Highest overlapping flare class | Factor score | Points |
|---|---:|---:|
| No confirmed overlap | 0.00 | 0 |
| C | 0.20 | 2 |
| M | 0.60 | 6 |
| X | 1.00 | 10 |
| Overlap with missing/invalid class | 0.50 | 5 |

A/B classes are valid but below V1's scored C/M/X classes and contribute zero.
With multiple overlapping flares, the maximum factor score is used. These are
team-defined environmental points based on standard flare-class ordering, not
failure probabilities. NOAA background reference:
https://www.spaceweather.gov/phenomena/solar-flares-radio-blackouts

### Geomagnetic storms

P1 supplies GST `start_time` and `max_kp_index`, but does not retain the time
of the maximum Kp observation or a justified active interval. GST records
whose start lies in the planning horizon are therefore returned only in
`context_events` with `GEOMAGNETIC_ACTIVITY_CONTEXT`. They contribute no
contact-specific V1 points. No storm duration is inferred.

## Space-weather data quality

Absence of `space_weather_status` means `UNKNOWN`. In particular, an empty
event list without status is not confirmed clear weather:

```text
unknown factor_score = 0.50
unknown points = 5
reason = SPACE_WEATHER_DATA_UNKNOWN
```

An explicit `COMPLETE` status plus no contact-relevant flare produces zero
points. `PARTIAL`, `UNAVAILABLE`, or `UNKNOWN` status preserves the neutral
five-point policy unless verified overlapping flare evidence supplies a
different factor score. Verified positive flare evidence is scored even when
status is partial, while the data-quality warning remains.

Malformed events produce `SPACE_WEATHER_EVENT_INVALID`. If no valid positive
evidence remains, V1 uses the neutral factor.

Supported status forms include a top-level `data_status`/`status`, or future
per-event-type statuses under `event_types`.

## Scheduled and unscheduled behavior

### Scheduled

```text
schedule_status = SCHEDULED
assessment_status = ASSESSED
risk_score = integer 0--100
risk_level = LOW | MEDIUM | HIGH
```

The exact station, window, start, and end are included in `contact`.

### Unscheduled

```text
schedule_status = UNSCHEDULED
assessment_status = UNRESOLVED
risk_score = null
risk_level = null
contact = null
```

The response retains factor evidence, the supplied conflict-evidence record,
and recovery classification. It never labels an outcome that has already
failed to schedule as merely `HIGH` risk.

## Reason codes

Existing conflict codes are preserved where supplied:

- `NO_ELIGIBLE_VISIBILITY_WINDOW`
- `INSUFFICIENT_WINDOW_DURATION`
- `ANTENNA_RESOURCE_CONFLICT`
- `OPTIMIZATION_TRADEOFF`

Risk V1 adds:

- `SINGLE_FEASIBLE_WINDOW`
- `SINGLE_USABLE_STATION`
- `PARTIALLY_BLOCKED_FEASIBLE_WINDOWS`
- `ALL_FEASIBLE_WINDOWS_BLOCKED`
- `NO_SOLVER_VALIDATED_ALTERNATIVE`
- `RECOVERY_REQUIRES_RESCHEDULING`
- `RECOVERY_REQUIRES_DISPLACEMENT`
- `SOLAR_FLARE_OVERLAP`
- `GEOMAGNETIC_ACTIVITY_CONTEXT`
- `SPACE_WEATHER_DATA_UNKNOWN`
- `SPACE_WEATHER_EVENT_INVALID`

Reason order and all lists in the output are deterministic.

## Validation

`OperationalRiskValidationError` is raised for malformed or inconsistent
inputs, including:

- missing/duplicate/unknown target requests;
- scenario-ID mismatches;
- noncanonical satellite or window identifiers;
- invalid or timezone-free timestamps;
- invalid planning horizons;
- conflicting duplicate windows;
- a target appearing as both scheduled and unscheduled;
- an assigned contact inconsistent with its visibility window or duration;
- priority outside the approved 1--10 range; and
- inconsistent alternatives or conflict evidence.

## Known V1 limitations

- Weights and LOW/MEDIUM/HIGH thresholds are hackathon policy, not calibrated.
- Normal scheduled contacts receive zero recovery points.
- Priority is consequence, not failure likelihood.
- `mandatory` and `max_elevation_deg` are not scored.
- Space-weather applicability is not satellite-, frequency-, or station-specific.
- GST cannot be tied to a contact until timed Kp observations or a justified
  active interval are supplied.
- The current P1 list cannot distinguish successful no-event retrieval from
  failed retrieval without separate status metadata.
