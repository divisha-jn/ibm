# Mission Ops Scheduling Copilot

An AI-assisted satellite ground-station scheduling tool. Built for the IBM Bob Hackathon.

---

## Problem Statement

Satellite operators must manually schedule communication windows between satellites and ground stations, balancing competing priorities, tight visibility windows, and antenna resource constraints. When a contact request is rejected, operators have little visibility into *why* — or what they could change to fix it.

## Solution

A scheduling copilot that:
- **Solves** the optimal contact schedule automatically using OR-Tools CP-SAT
- **Explains** every scheduling decision and rejection in plain language using IBM Granite (watsonx.ai)
- **Answers what-if questions** — ask "what if this mission becomes mandatory?" and the solver re-runs instantly to show the impact
- **Ranks alternatives** — for any rejected request, finds and ranks the best alternative windows by operational disruption cost

---

## AI Approach & Architecture

### Challenge Theme
**Space & Satellite Operations** — intelligent scheduling and decision support for ground-station contact management.

### IBM Bob Usage
This project was built using **IBM Bob** as the primary development tool — for code generation, architecture decisions, debugging, and iterative refinement across all components.

### How it works

```
User question
      │
      ▼
IBM Granite (watsonx.ai)          ← intent parsing, natural-language explanation
      │
      ▼
OR-Tools CP-SAT solver            ← optimal schedule, conflict detection, alternatives ranking
      │
      ▼
FastAPI backend  ──────────────►  Next.js frontend
(Python)                          (Gantt chart + AI Copilot chat panel)
```

| Layer | What it does |
|---|---|
| `backend/ai/` | Granite client, intent parser (what-if queries), explanation prompts |
| `backend/solver/` | OR-Tools scheduler, conflict evidence builder, alternatives ranker, risk scorer |
| `backend/data/` | Visibility window generation via CelesTrak TLEs + Skyfield/SGP4 |
| `backend/api/` | FastAPI routes — `/schedule`, `/explain`, `/what-if`, `/alternatives`, `/risk` |
| `frontend/` | Gantt chart, AI Copilot chat panel (Next.js + React) |

The solver and Granite are deliberately separated: OR-Tools determines *what* the schedule is (deterministic, mathematically optimal); Granite only *explains* it and parses natural-language what-if queries. Granite never influences scheduling decisions.

---

## Setup

**Requirements:** Python 3.10–3.12 · Node.js 18+

> `ortools` has no Python 3.13 wheel — the app will run on 3.13 but will serve mock schedule data instead of a real solved schedule.

**1. Configure environment**
```bash
cp .env.example .env
# Fill in WATSONX_APIKEY and WATSONX_PROJECT_ID
```

**2. Backend**
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000
```

**3. Frontend** (separate terminal)
```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Backend runs on port 8000.

> **First load is slow (10–30s)** — on first request the backend fetches live orbital data from CelesTrak and computes visibility windows. Subsequent requests use a 6-hour cache and are fast.

### Running without credentials or ortools

The app degrades gracefully — nothing crashes:

| Missing | Effect |
|---|---|
| `.env` credentials | AI explanations show factual stubs instead of Granite responses |
| `ortools` (Python 3.13) | Schedule shows hardcoded mock data instead of a solved schedule |

---

<!-- INTERNAL NOTES — safe to delete before submission -->


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
