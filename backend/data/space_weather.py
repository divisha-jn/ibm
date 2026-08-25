"""
backend/data/space_weather.py

Fetches real space-weather advisory events from NASA's DONKI (Database Of
Notifications, Knowledge, Information) API and caches them locally, the
same pattern as celestrak.py.

Covers two event types most relevant to ground-station operations:
- FLR (solar flares) — can disrupt HF radio and cause signal degradation
- GST (geomagnetic storms) — can disrupt satellite operations and tracking

NASA DONKI docs: https://api.nasa.gov/  (see the DONKI section)

Get a free API key at https://api.nasa.gov/ (takes 30 seconds, no approval
wait). DEMO_KEY works for testing but is rate-limited to ~30 requests/hour
shared across everyone using it — use a real key for the actual demo.

Usage:
    from backend.data.space_weather import fetch_space_weather_events

    events = fetch_space_weather_events("2026-08-20", "2026-08-27")
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import List, Literal

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_CACHE_DIR = REPO_ROOT / "backend" / "data" / "raw"
RAW_CACHE_DIR.mkdir(parents=True, exist_ok=True)

DONKI_BASE_URL = "https://api.nasa.gov/DONKI"
CACHE_MAX_AGE_SECONDS = 6 * 60 * 60  # 6 hours — advisories don't need to be fresher than this for a demo

# Reads from environment variable NASA_API_KEY if set (see .env.example),
# falls back to NASA's public rate-limited demo key.
NASA_API_KEY = os.environ.get("NASA_API_KEY", "DEMO_KEY") 

EventType = Literal["FLR", "GST"]


class SpaceWeatherError(RuntimeError):
    pass


def _cache_path(event_type: str, start_date: str, end_date: str) -> Path:
    return RAW_CACHE_DIR / f"donki_{event_type}_{start_date}_{end_date}.json"


def _cache_is_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) < CACHE_MAX_AGE_SECONDS


def _fetch_donki_events(
    event_type: EventType, start_date: str, end_date: str, force_refresh: bool = False
) -> List[dict]:
    """Fetch one event type (FLR or GST) from DONKI for a date range.
    Dates must be 'YYYY-MM-DD' strings."""
    cache_file = _cache_path(event_type, start_date, end_date)

    if not force_refresh and _cache_is_fresh(cache_file):
        with open(cache_file, "r") as f:
            return json.load(f)

    url = f"{DONKI_BASE_URL}/{event_type}"
    params = {"startDate": start_date, "endDate": end_date, "api_key": NASA_API_KEY}

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, json.JSONDecodeError) as exc:
        # Fall back to stale cache rather than crashing the pipeline mid-demo
        if cache_file.exists():
            with open(cache_file, "r") as f:
                return json.load(f)
        raise SpaceWeatherError(f"Failed to fetch DONKI {event_type} data and no cache available: {exc}") from exc

    with open(cache_file, "w") as f:
        json.dump(data, f, indent=2)

    return data


def _normalize_flare(raw: dict) -> dict:
    """Convert a raw DONKI FLR record into our shared advisory shape."""
    return {
        "event_type": "solar_flare",
        "event_id": raw.get("flrID"),
        "start_time": raw.get("beginTime"),
        "peak_time": raw.get("peakTime"),
        "end_time": raw.get("endTime"),
        "class_type": raw.get("classType"),  # e.g. "M2.3", "X1.0" — higher letter/number = more severe
        "source_location": raw.get("sourceLocation"),
        "advisory": f"Solar flare ({raw.get('classType', 'unknown class')}) — possible HF/radio signal degradation",
    }


def _normalize_geomagnetic_storm(raw: dict) -> dict:
    """Convert a raw DONKI GST record into our shared advisory shape."""
    kp_values = raw.get("allKpIndex", [])
    max_kp = max((k.get("kpIndex", 0) for k in kp_values), default=None)
    return {
        "event_type": "geomagnetic_storm",
        "event_id": raw.get("gstID"),
        "start_time": raw.get("startTime"),
        "max_kp_index": max_kp,  # Kp scale 0-9, 5+ is considered a storm
        "advisory": f"Geomagnetic storm (max Kp {max_kp}) — possible satellite tracking/comms disruption",
    }


def fetch_space_weather_events(
    start_date: str, end_date: str, force_refresh: bool = False
) -> List[dict]:
    """Fetch and normalize all space-weather advisory events (flares + storms)
    for a date range, in a shared shape ready for risk.py to consume.

    Args:
        start_date: 'YYYY-MM-DD'
        end_date: 'YYYY-MM-DD'
        force_refresh: bypass the 6-hour cache and re-fetch from NASA

    Returns:
        List of normalized advisory dicts, sorted by start_time.
    """
    events: List[dict] = []

    try:
        flares = _fetch_donki_events("FLR", start_date, end_date, force_refresh)
        events.extend(_normalize_flare(f) for f in flares)
    except SpaceWeatherError as exc:
        print(f"[space_weather] WARNING: skipping solar flare data: {exc}")

    try:
        storms = _fetch_donki_events("GST", start_date, end_date, force_refresh)
        events.extend(_normalize_geomagnetic_storm(s) for s in storms)
    except SpaceWeatherError as exc:
        print(f"[space_weather] WARNING: skipping geomagnetic storm data: {exc}")

    events.sort(key=lambda e: e.get("start_time") or "")
    return events


if __name__ == "__main__":
    from datetime import datetime, timedelta, timezone
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=7)
    print(f"Fetching space-weather advisories from {start} to {end}...")
    events = fetch_space_weather_events(str(start), str(end))
    print(f"Found {len(events)} advisory event(s):")
    print(json.dumps(events, indent=2))