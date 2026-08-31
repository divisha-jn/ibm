# Mission Ops Scheduling Copilot

**Team: Bob In Orbit**

An AI-assisted satellite ground-station scheduling tool. Built for the IBM Bob Hackathon.

---

## Problem Statement

Satellite operators must manually schedule communication windows between satellites and ground stations, balancing competing priorities, tight visibility windows, and antenna resource constraints. When a contact request is rejected, operators have little visibility into *why* — or what they could change to fix it.

## Solution

A scheduling copilot that:
- **Solves** the optimal contact schedule automatically using OR-Tools CP-SAT
- **Explains** every scheduling decision and rejection in plain language using an LLM on IBM watsonx.ai
- **Answers what-if questions** — ask "what if this mission becomes mandatory?" and the solver re-runs instantly to show the impact
- **Ranks alternatives** — for any rejected request, finds and ranks the best alternative windows by operational disruption cost
- **Scores operational risk** — a deterministic 0–100 fragility index per request, factoring in scheduling flexibility, station redundancy, conflict pressure, recovery options, mission priority, and real NASA space-weather advisories

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
LLM on IBM watsonx.ai              ← intent parsing, natural-language explanation
      │
      ▼
OR-Tools CP-SAT solver             ← optimal schedule, conflict detection, alternatives ranking, risk scoring
      │
      ▼
FastAPI backend  ──────────────►  Next.js frontend
(Python)                          (Gantt chart + AI Copilot chat panel)
```

| Layer | What it does |
|---|---|
| `backend/ai/` | watsonx.ai client, intent parser (what-if queries), explanation prompts |
| `backend/solver/` | OR-Tools scheduler, conflict evidence builder, alternatives ranker, risk scorer |
| `backend/data/` | Visibility window generation via CelesTrak TLEs + Skyfield/SGP4, NASA DONKI space-weather advisories |
| `backend/api/` | FastAPI routes — `/schedule`, `/explain`, `/what-if`, `/alternatives`, `/risk` |
| `frontend/` | Gantt chart, AI Copilot chat panel (Next.js + React) |

The solver and the LLM are deliberately separated: OR-Tools determines *what* the schedule is (deterministic, mathematically optimal, and — for the risk index — the exact scoring formula); the LLM only *explains* decisions in natural language and parses free-text what-if queries. It never touches a scheduling decision or a risk score.

Model: watsonx.ai hosting `meta-llama/llama-4-maverick-17b-128e-instruct-fp8` by default (configurable via `WATSONX_MODEL_ID` in `.env` — see `backend/ai/granite.py`).

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
| `.env` credentials | AI explanations show factual stubs instead of live watsonx.ai responses |
| `ortools` (Python 3.13) | Schedule shows hardcoded mock data instead of a solved schedule |
