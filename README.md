## Data pipeline: visibility windows

`GET /schedule` needs a set of satellite/ground-station visibility windows
before it can solve a schedule. That data is generated, not hand-authored.

**Where it lives:** `backend/data/generated/visibility_windows_scheduler.json`
— the canonical, solver-ready cache (gitignored, regenerated per machine).
A second file, `visibility_windows.json`, holds P1's frozen contract-shape
snapshot (`satellite`/`station`/`visibility_start`/`visibility_end`) — it's
no longer read by the live `/schedule` path, only written when someone runs
`save_visibility_windows()` directly (e.g. `docs/handoff_person1.md`'s demo
command below).

**How refresh works:** `backend/api/data_pipeline.py`'s `_get_visibility_data()`
checks the scheduler cache's age against a 6-hour TTL (`VISIBILITY_CACHE_TTL_SECONDS`)
and its shape against `_visibility_cache_is_compatible()`. If it's missing,
stale, or shaped wrong, it regenerates automatically — this runs on-request,
inline, the first time `/schedule` (or `/what-if`) is called after the
cache goes stale. There is no background/cron refresh job.

**How to force a manual refresh:** delete
`backend/data/generated/visibility_windows_scheduler.json` and make any
request to `/schedule`. To regenerate P1's separate frozen-contract
snapshot (`visibility_windows.json`), run directly:

```python
from backend.data.passes import generate_all_visibility_windows, save_visibility_windows
save_visibility_windows(generate_all_visibility_windows())
```

**The two reusable functions**, both in `backend/data/passes.py`:

- `generate_all_visibility_windows(horizon_hours: int = 48, force_refresh_celestrak: bool = False) -> List[VisibilityWindow]`
  Computes passes for the demo satellite set across all configured ground
  stations over the given horizon (CelesTrak → Skyfield/SGP4). Returns an
  in-memory list; does not write to disk.

- `save_visibility_windows(windows, start=None, end=None, minimum_elevation_deg=10.0, filename="visibility_windows.json") -> Path`
  Serialises a list of windows to `backend/data/generated/<filename>` in the
  contract #3 envelope shape (`planning_horizon`, `minimum_elevation_deg`,
  `visibility_windows`). Returns the path written.

**Note:** `backend/api/scheduling.py`'s `obtain_visibility_data()` also calls
`generate_all_visibility_windows()` but skips the cache/TTL entirely — it
always regenerates and adapts straight into the solver's input shape. It
isn't called from any live endpoint (`/schedule` and `/what-if` both go
through `data_pipeline.py`'s cached path) — only `run_scheduling()` from the
same module is still exercised, by `backend/tests/test_backend_scheduling.py`
and `backend/tests/test_conflict_explanation_integration.py`.

## Demo scenarios

Real orbital passes aren't predictable on demand, so there's no way to make
`GET /schedule` naturally reproduce a specific conflict just by waiting.
Instead, `backend/data/demo_scenarios.py` seeds the live app with a fixed,
already-unit-tested scenario:

```bash
python -m backend.data.demo_scenarios [antenna_conflict | ranked_alternatives]
```

Defaults to `antenna_conflict` if no name is given. Both overwrite
`data/mission_requests.json` and
`backend/data/generated/visibility_windows_scheduler.json`; both require
`ortools` (Python ≤3.12 — see [Loading / timeout expectations](docs/api_contracts.md))
on whichever endpoint you hit, otherwise you'll get the hardcoded/mock
fallback instead of the seeded scenario.

**Restore the default demo data** afterwards with:
```bash
git checkout -- data/mission_requests.json
```
(the visibility cache file is gitignored — it's just overwritten again the
next time `/schedule` regenerates it from real orbital data).

### `antenna_conflict` — a straight priority conflict, no alternative

Two requests contend for the same ground station at the same time; only
the higher-priority one can be scheduled, and there's no other window for
the loser to move to.

**Then hit:** `GET /api/v1/schedule`

```json
{
  "scheduled_contacts": [
    { "request_id": "REQ_HIGH_PRIORITY", "priority": 9, "...": "..." }
  ],
  "unscheduled_requests": [
    {
      "request_id": "REQ_LOW_PRIORITY",
      "priority": 5,
      "reason_codes": ["ANTENNA_RESOURCE_CONFLICT"],
      "conflicts": [{ "conflicting_request_id": "REQ_HIGH_PRIORITY", "...": "..." }]
    }
  ]
}
```

`POST /api/v1/alternatives {"scenario_id": "LIVE_CONFLICT_ENRICHMENT", "request_id": "REQ_LOW_PRIORITY"}`
returns `status: "NO_FEASIBLE_ALTERNATIVES"` — there genuinely isn't another
window, so this scenario is not useful for testing the ranked-alternatives
UI. Use `ranked_alternatives` for that.

**Single source of truth:** `backend/data/demo_scenarios.py::antenna_conflict_scenario()`,
imported directly by `backend/tests/test_data_pipeline.py`'s
`test_schedule_enriches_station_conflict_from_same_p2_inputs`.

### `ranked_alternatives` — a real alternative exists, at a displacement cost

A high-priority request needs a full 20-minute pass, but a lower-priority
pair already splits that same station-time slot into two 10-minute
contacts whose *combined* priority outweighs the high-priority request's
alone — so the solver schedules the pair instead. Unlike `antenna_conflict`,
the loser here does have one other viable window: the full slot, at the
cost of displacing both current holders.

**Then hit:** `GET /api/v1/schedule`

```json
{
  "scheduled_contacts": [
    { "request_id": "REQ_LOWER_A", "priority": 4, "...": "..." },
    { "request_id": "REQ_LOWER_B", "priority": 4, "...": "..." }
  ],
  "unscheduled_requests": [
    {
      "request_id": "REQ_ALT_TARGET",
      "priority": 6,
      "reason_codes": ["ANTENNA_RESOURCE_CONFLICT"],
      "conflicts": ["...", "..."]
    }
  ]
}
```

**Then hit** `POST /api/v1/alternatives {"scenario_id": "P2_ALTERNATIVES_TEST", "request_id": "REQ_ALT_TARGET"}`:

```json
{
  "status": "ALTERNATIVES_FOUND",
  "alternatives": [
    {
      "rank": 1,
      "window_id": "VW_TARGET_LONG",
      "displaced_request_ids": ["REQ_LOWER_A", "REQ_LOWER_B"],
      "ranking_metrics": { "displaced_count": 2, "displaced_priority_total": 8, "...": "..." }
    }
  ]
}
```

**Single source of truth:** `backend/data/demo_scenarios.py::ranked_alternatives_scenario()`,
imported directly by `backend/tests/test_alternatives.py`'s
`test_real_p2_schedule_evidence_and_alternatives_integration`.
