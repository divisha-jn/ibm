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

## Demo scenario: antenna resource conflict

Real orbital passes aren't predictable on demand, so there's no way to make
`GET /schedule` naturally reproduce a specific conflict just by waiting.
Instead, `backend/data/demo_scenarios.py` seeds the live app with a fixed,
already-unit-tested scenario:

```bash
python -m backend.data.demo_scenarios
```

This overwrites `data/mission_requests.json` and
`backend/data/generated/visibility_windows_scheduler.json` with two
requests contending for the same ground station at the same time.

**Then hit:** `GET /api/v1/schedule` (requires `ortools`, i.e. Python ≤3.12
— see [Loading / timeout expectations](docs/api_contracts.md) — otherwise
you'll get the hardcoded stub instead of this scenario).

**Expected response** (abridged — full shape is the normal `ScheduleResult`
contract, see `docs/api_contracts.md`):
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

**Restore the default demo data** afterwards with:
```bash
git checkout -- data/mission_requests.json
```
(the visibility cache file is gitignored — it's just overwritten again the
next time `/schedule` regenerates it from real orbital data).

**Single source of truth:** the scenario data lives in
`backend/data/demo_scenarios.py::antenna_conflict_scenario()`, which
`backend/tests/test_data_pipeline.py`'s
`test_schedule_enriches_station_conflict_from_same_p2_inputs` imports and
asserts against directly — the seed script and the pytest fixture are
reading the exact same function, not hand-copied duplicates, so they can't
drift apart.
