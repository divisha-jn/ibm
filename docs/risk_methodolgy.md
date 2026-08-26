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

P1 supplies GST `start_time`, `max_kp_index`, `max_kp_time`, and individual
timed `kp_readings`. Each reading has `time`, `kp_index`, and nullable
`source`. A reading is contact-relevant only when its valid timezone-aware
timestamp falls in the contact's half-open interval:

```text
scheduled_start <= kp_reading.time < scheduled_end
```

`start_time`, event-wide `max_kp_index`, and an out-of-contact `max_kp_time`
never create contact-specific points. No GST duration or applicability window
is inferred. Old GST records without `kp_readings` remain context-only.

For multiple valid in-contact readings, P2 preserves every matched reading as
evidence and uses only the maximum Kp:

| Maximum contact-relevant Kp | Factor score | Points |
|---:|---:|---:|
| `< 5` | 0.00 | 0 |
| `5 <= Kp < 6` | 0.20 | 2 |
| `6 <= Kp < 7` | 0.40 | 4 |
| `7 <= Kp < 8` | 0.60 | 6 |
| `8 <= Kp < 9` | 0.80 | 8 |
| `>= 9` (valid Kp range caps at 9) | 1.00 | 10 |

Kp is observed environmental-severity input. Mapping Kp severity to these
Operational Risk Index points is team-defined product policy. It is not a
probability of contact failure or a prediction of satellite damage.

When both a timed GST reading and an overlapping solar flare are relevant,
P2 uses the maximum of their factor scores. It never adds them, so the entire
Space Weather factor remains capped at 10 points. The output preserves both
events and all valid matched Kp readings as evidence.

## Space-weather data quality

P1 supplies per-type status as:

```json
{
  "FLR": "ok" | "stale" | "failed",
  "GST": "ok" | "stale" | "failed"
}
```

- `ok` means fresh usable live or cached data, including a successful result
  containing zero events.
- `stale` means a refresh failed and stale cached data was returned. Its
  events remain usable evidence, but data quality is degraded.
- `failed` means no usable live or cached data exists for that type.

P2 derives overall weather quality deterministically:

| FLR | GST | Weather quality |
|---|---|---|
| `ok` | `ok` | `COMPLETE` |
| `failed` | `failed` | `UNAVAILABLE` |
| Any other valid combination | | `PARTIAL` |

Therefore `events=[]` with `ok`/`ok` is confirmed clear and contributes zero
points. Empty events with partial or unavailable data do not prove clear
conditions and retain the existing conservative neutral policy. Staleness
does not itself add numerical severity points: valid evidence from a stale
type is scored normally while status remains `PARTIAL`.

Absence of `space_weather_status` means `UNKNOWN`. In particular, an empty
event list without status is not confirmed clear weather:

```text
unknown factor_score = 0.50
unknown points = 5
reason = SPACE_WEATHER_DATA_UNKNOWN
```

An explicit `COMPLETE` status plus no contact-relevant event produces zero
points. `PARTIAL`, `UNAVAILABLE`, or `UNKNOWN` status preserves the neutral
five-point policy unless valid contact-relevant flare or Kp evidence supplies
a different factor score. Valid evidence is scored even when status is
partial, while the data-quality warning remains.

Malformed events produce `SPACE_WEATHER_EVENT_INVALID`; malformed individual
Kp observations additionally produce `INVALID_KP_READING`. Invalid readings
are ignored rather than converted to Kp zero. Other valid readings remain
usable. If no valid contact-relevant evidence remains, V1 uses the neutral
factor.

For backward compatibility, supported legacy status forms include a top-level
`data_status`/`status` or per-event-type statuses under `event_types`.

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
- `GEOMAGNETIC_STORM_CONTACT_RELEVANT`
- `GEOMAGNETIC_ACTIVITY_CONTEXT`
- `INVALID_KP_READING`
- `SPACE_WEATHER_EVENT_INVALID`
- `SPACE_WEATHER_DATA_STALE`
- `SPACE_WEATHER_DATA_UNKNOWN`

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
- Timed Kp readings are treated only as instantaneous evidence; no activity
  interval is inferred between readings.
