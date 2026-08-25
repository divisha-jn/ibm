# API Contracts (for frontend / Person 5)

Backend: FastAPI, defined in `backend/main.py`, routes in `backend/api/routes.py`.

## Base URL

Run locally with:
```
python -m backend.main
```
This binds `0.0.0.0:8000` and mounts all routes under the `/api/v1` prefix. So:

```
http://localhost:8000/api/v1
```

All endpoint paths below are relative to this base (e.g. `/schedule` means
`GET http://localhost:8000/api/v1/schedule`).

Interactive, always-up-to-date docs (auto-generated from the same Pydantic
models used at runtime — trust these over this file if they ever disagree):
`http://localhost:8000/docs`

## CORS

Configured in `backend/main.py` via `CORSMiddleware`:

```python
allow_origins=["*"]
allow_credentials=True
allow_methods=["*"]
allow_headers=["*"]
```

**`http://localhost:3000` is allowed**, including credentialed requests
(cookies / `Authorization` headers). Note: `allow_origins=["*"]` combined
with `allow_credentials=True` looks like it should be rejected by browsers
(the fetch spec forbids a literal `*` origin on credentialed responses) —
but Starlette's `CORSMiddleware` detects this combination and echoes back
the actual request `Origin` header instead of `*`, so it works correctly
in practice. Verified against the installed Starlette's middleware source,
not just the config.

## Error response shape

There is no standardized error envelope across all endpoints. What you'll
actually see:

| Situation | Status | Body |
|---|---|---|
| Request body fails Pydantic validation (missing/wrong-typed field) | `422` | FastAPI default: `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}` |
| `POST /what-if/apply` with an unknown, already-applied, or non-applicable `what_if_id` | `404` | `{"detail": "<human-readable message>"}` |
| Genuinely unexpected server-side bug | `500` | FastAPI default bare body, no custom shape |

In practice, `500`s should be rare: every endpoint except `/what-if/apply`
is written to fail *inward* rather than raise — if the live solver,
CelesTrak, or Granite are unavailable, the endpoint falls back to stub/mock
data and still returns `200`. Check the response body itself for signals
that you got a fallback (see per-endpoint notes below) rather than relying
on a non-2xx status.

## Loading / timeout expectations

| Endpoint | Typical | Worst case | Notes |
|---|---|---|---|
| `GET /schedule` | < 1s (stub) or a few seconds (live: CelesTrak + Skyfield + CP-SAT) | tens of seconds on a cold visibility-window cache (first request, or every 6h) | Visibility windows are cached with a 6h TTL — only regenerated when stale |
| `POST /explain` | < 1s (fallback) or a few seconds + Granite call (live) | ~60s | Granite/watsonx call has a 60s timeout (`WATSONX_TIMEOUT_SECONDS` env var, default 60) — this is the number to size your frontend request timeout against |
| `POST /what-if` | similar to `/schedule` + `/explain` combined (re-solves, then explains) | ~60s+ | Same Granite timeout applies to both the intent-parsing call and the explanation call, so worst case is roughly double |
| `POST /what-if/apply` | < 100ms | — | Pure file write, no network calls |

Recommend a frontend timeout of at least **90s** on `/explain` and
`/what-if` to comfortably clear the Granite 60s ceiling plus solver time.

---

## Endpoints

### `GET /schedule`

Returns the baseline schedule (contract #5). No request body.

**Response `200`** — `ScheduleResult`:
```json
{
  "scenario_id": "DEMO_001",
  "solver": {
    "engine": "OR-Tools CP-SAT",
    "status": "OPTIMAL",
    "objective_value": 13.0
  },
  "scheduled_contacts": [
    {
      "request_id": "REQ_001",
      "satellite_id": "NORAD_25544",
      "station_id": "GS_SG_01",
      "antenna_id": "GS_SG_01_A1",
      "window_id": "VW_0001",
      "scheduled_start": "2026-08-11T02:14:00Z",
      "scheduled_end": "2026-08-11T02:19:00Z",
      "duration_seconds": 300,
      "priority": 8
    }
  ],
  "unscheduled_requests": [
    {
      "request_id": "REQ_002",
      "satellite_id": "NORAD_48274",
      "reason_codes": ["ANTENNA_RESOURCE_CONFLICT"],
      "conflicts": [
        {
          "conflicting_request_id": "REQ_001",
          "station_id": "GS_SG_01",
          "overlap_seconds": 240,
          "request_priority": 5,
          "conflicting_request_priority": 8
        }
      ]
    }
  ]
}
```

`solver.objective_value` is `null` when the solver reports a non-`OPTIMAL`
status. There's no field that tells you whether this is the live solve or
the hardcoded fallback — the shape is identical either way by design.

`unscheduled_requests[].conflicts` is the same `ConflictRecord` shape as
`/explain`'s `evidence.conflicts` — this is so P5 can render a rejection
banner (who it lost to, at which station, how much overlap, both
priorities) directly from `/schedule` without a separate `/explain` call
per rejected request. It's `[]` when the request had no competing contact
(e.g. `reason_codes: ["NO_ELIGIBLE_VISIBILITY_WINDOW"]`) — only nonempty
alongside conflict-driven reason codes like `ANTENNA_RESOURCE_CONFLICT` or
`OPTIMIZATION_TRADEOFF`.

### `POST /explain`

Natural-language explanation for why a specific request was (or wasn't)
scheduled.

**Request** — `ExplainRequest`:
```json
{
  "scenario_id": "DEMO_001",
  "request_id": "REQ_002"
}
```
Note: `scenario_id` is accepted but currently **not used** by the handler —
it always explains against whatever the current live/stub baseline is,
not a specific stored scenario. Send it for forward-compatibility, but
don't rely on it selecting anything yet.

**Response `200`** — `ExplainResponse`:
```json
{
  "request_id": "REQ_002",
  "explanation": "REQ_002 (priority 5) could not be scheduled because antenna GS_SG_01_A1 at GS_SG_01 is already occupied by REQ_001 (priority 8) for 240 seconds of the available window.",
  "evidence": {
    "reason_codes": ["ANTENNA_RESOURCE_CONFLICT"],
    "conflicts": [
      {
        "conflicting_request_id": "REQ_001",
        "station_id": "GS_SG_01",
        "overlap_seconds": 240,
        "request_priority": 5,
        "conflicting_request_priority": 8
      }
    ],
    "feasibility": {
      "requested_contact_seconds": 300
    },
    "alternative_window_ids": []
  }
}
```

**`explanation`** is always a plain string (Granite prose or factual
fallback) — render it as a paragraph.

**`evidence`** is `null` in two cases:
- The request was scheduled successfully (no conflict to report)
- The live solver pipeline is down (ortools unavailable)

When `evidence` is non-null, P5 can use it to:
- Show a reason badge from `reason_codes[0]` (e.g. `ANTENNA_RESOURCE_CONFLICT`)
- Render a conflict card from `conflicts[]` — highlight the `conflicting_request_id` block on the Gantt
- Show `alternative_window_ids` as "Try instead" suggestions if the list is non-empty

If `request_id` was scheduled successfully, or the pipeline is down,
`explanation` is still a plain string — e.g. `"REQ_002 was scheduled
successfully — no conflict evidence found."` or `"Conflict evidence for
REQ_002 is not available (live solver pipeline inactive — check ortools
installation)."`. You always get `200` with some string; `evidence: null`
is the signal that there is nothing structured to render.

### `POST /alternatives`

Ranked alternative resolutions for one unscheduled request — **real
solver re-solves against candidate windows**, not an LLM suggestion.
Ranked by operational disruption: fewest, then lowest-priority,
displaced/rescheduled requests first.

**Request** — `AlternativesRequest`:
```json
{
  "scenario_id": "DEMO_001",
  "request_id": "REQ_002",
  "limit": 3
}
```
`limit` is optional, defaults to `3` — the max number of ranked
alternatives to return.

**Response `200`** — `AlternativesResponse`:
```json
{
  "scenario_id": "DEMO_001",
  "request_id": "REQ_002",
  "satellite_id": "NORAD_48274",
  "status": "ALTERNATIVES_FOUND",
  "reason_codes": ["ANTENNA_RESOURCE_CONFLICT"],
  "alternatives": [
    {
      "rank": 1,
      "alternative_type": "ALTERNATIVE_WINDOW",
      "window_id": "VW_0042",
      "station_id": "GS_PERTH_01",
      "scheduled_start": "2026-08-27T08:10:00Z",
      "scheduled_end": "2026-08-27T08:15:00Z",
      "duration_seconds": 300,
      "displaced_request_ids": [],
      "rescheduled_request_ids": [],
      "ranking_metrics": {
        "displaced_count": 0,
        "displaced_priority_total": 0,
        "rescheduled_count": 0,
        "rescheduled_priority_total": 0
      }
    }
  ]
}
```

`status` is one of:
- `ALTERNATIVES_FOUND` — `alternatives[]` has 1–`limit` real, solver-validated candidate windows, best first (see `ranking_metrics` below)
- `NO_FEASIBLE_ALTERNATIVES` — request is genuinely unschedulable anywhere in the horizon; `alternatives` is `[]`, `reason_codes` explains why
- `REQUEST_ALREADY_SCHEDULED` — `request_id` isn't actually unscheduled; `alternatives` and `reason_codes` are both `[]`
- `PIPELINE_UNAVAILABLE` — app-level status (not from the solver itself): `ortools` is down, `request_id` doesn't exist in the scenario, or any solver step failed. Same fail-inward-with-`200` convention as `/schedule` and `/explain` — check `status`, not the HTTP status code. `satellite_id` is `null` in this case (it's only known once the request is validated against mission data).

Each entry in `alternatives[]` is a **real, re-solved** candidate — the
solver was forced to place `request_id` on that exact window and actually
succeeded, so `scheduled_start`/`scheduled_end`/`duration_seconds` are
guaranteed feasible, not just "the window exists." `ranking_metrics` is
what determines sort order: fewer `displaced_count` wins, ties broken by
lower `displaced_priority_total`, then `rescheduled_count`, then
`rescheduled_priority_total`. `displaced_request_ids` are requests that
would lose their contact entirely; `rescheduled_request_ids` keep a
contact but at a different time/station.

### `POST /what-if`

Parses a natural-language what-if query, re-solves, and returns the
impact + explanation. Does **not** persist anything — see
`/what-if/apply` to commit a result.

**Request** — `WhatIfRequest`:
```json
{
  "base_scenario_id": "DEMO_001",
  "user_query": "what if I boost REQ_002's priority to 10?"
}
```

**Response `200`** — `WhatIfResponse`:
```json
{
  "what_if_id": "WI_86AF2F",
  "base_scenario_id": "DEMO_001",
  "user_query": "what if I boost REQ_002's priority to 10?",
  "interpretation": {
    "intent": "MODIFY_SCENARIO",
    "operations": [
      { "operation": "SET_PRIORITY", "request_id": "REQ_002", "station_id": null, "station_ids": null, "value": 10 }
    ],
    "requires_resolve": true,
    "error": null
  },
  "result": {
    "solver_status": "OPTIMAL",
    "impact": {
      "newly_scheduled": ["REQ_002"],
      "newly_unscheduled": ["REQ_001"],
      "unchanged": []
    },
    "proposed_schedule": { "...": "full ScheduleResult shape, see /schedule above" },
    "explanation": "Raising REQ_002's priority to 10 caused it to displace lower-priority competing requests. It is now scheduled.",
    "can_apply": true
  }
}
```

`result` is `null` when `interpretation.intent == "UNSUPPORTED"` (e.g. the
query wasn't a recognizable scenario mutation) — check for `null` before
reading `result.*`.

**`can_apply`** tells you whether this result is eligible to be committed
via `/what-if/apply`. It's `false` when the response was computed via the
mock fallback (e.g. `ortools` unavailable) rather than the live solver —
those results can be shown to the user but can't be applied.

Four supported operations inside `interpretation.operations`:
`SET_PRIORITY` (request_id + value), `SET_REQUIRED_DURATION` (request_id +
value in seconds), `DISABLE_STATION` (station_id), `SET_ELIGIBLE_STATIONS`
(request_id + station_ids).

### `POST /what-if/apply`

Commits a previously returned `/what-if` result as the new baseline —
overwrites the scenario data so the next `/schedule` and `/what-if` calls
start from it. One-time use per `what_if_id`.

**Request** — `ApplyWhatIfRequest`:
```json
{ "what_if_id": "WI_86AF2F" }
```

**Response `200`** — `ApplyWhatIfResponse`:
```json
{
  "applied": true,
  "what_if_id": "WI_86AF2F",
  "scenario_id": "DEMO_001",
  "schedule": { "...": "full ScheduleResult shape, see /schedule above" }
}
```

**Response `404`** when `what_if_id` is unknown, already applied, or was
computed with `can_apply: false`:
```json
{
  "detail": "No applicable what-if result for 'WI_86AF2F' — unknown id, already applied, or computed without the live solver."
}
```
Only attempt `/what-if/apply` after checking `result.can_apply === true`
on the original `/what-if` response — otherwise you'll always get `404`.
