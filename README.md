## Data pipeline: visibility windows

`GET /schedule` needs a set of satellite/ground-station visibility windows
before it can solve a schedule. That data is generated, not hand-authored.

**Where it lives:** `backend/data/generated/visibility_windows.json`
(gitignored — regenerated per machine, only a `.gitkeep` is tracked).

**How refresh works:** `backend/api/data_pipeline.py`'s `_get_visibility_data()`
checks the file's age against a 6-hour TTL (`VISIBILITY_CACHE_TTL_SECONDS`).
If the file is missing or stale, it regenerates automatically — this runs
on-request, inline, the first time `/schedule` (or `/what-if`) is called
after the cache goes stale. There is no background/cron refresh job.

**How to force a manual refresh:** delete the file and make any request to
`/schedule`, or run directly:

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
