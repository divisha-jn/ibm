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

    result = fetch_space_weather_events("2026-08-20", "2026-08-27")
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
FetchStatus = Literal["ok", "stale", "failed"]


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
) -> tuple[List[dict], Literal["ok", "stale"]]:
    """Fetch one event type (FLR or GST) from DONKI for a date range.
    Dates must be 'YYYY-MM-DD' strings.

    Returns the raw events and whether they are fresh (``ok``) or a stale
    cache fallback used after a failed DONKI refresh (``stale``).
    """
    cache_file = _cache_path(event_type, start_date, end_date)

    if not force_refresh and _cache_is_fresh(cache_file):
        try:
            with open(cache_file, "r") as f:
                return json.load(f), "ok"
        except (OSError, json.JSONDecodeError) as exc:
            # A broken fresh cache is not usable; try DONKI before declaring
            # this event type unavailable.
            print(
                f"[space_weather] WARNING: could not read fresh {event_type} "
                f"cache; refreshing from DONKI: {exc}"
            )

    url = f"{DONKI_BASE_URL}/{event_type}"
    params = {"startDate": start_date, "endDate": end_date, "api_key": NASA_API_KEY}

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, json.JSONDecodeError) as exc:
        # Fall back to stale cache rather than crashing the pipeline mid-demo
        if cache_file.exists():
            try:
                with open(cache_file, "r") as f:
                    return json.load(f), "stale"
            except (OSError, json.JSONDecodeError) as cache_exc:
                raise SpaceWeatherError(
                    f"Failed to fetch DONKI {event_type} data and the cache "
                    f"is unusable: {cache_exc}"
                ) from exc
        raise SpaceWeatherError(
            f"Failed to fetch DONKI {event_type} data and no cache available: {exc}"
        ) from exc

    try:
        with open(cache_file, "w") as f:
            json.dump(data, f, indent=2)
    except OSError as exc:
        # The live result is still fresh and usable even if caching it fails.
        print(
            f"[space_weather] WARNING: could not cache fresh {event_type} "
            f"data: {exc}"
        )

    return data, "ok"


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
    # Keep every individual Kp reading with its own timestamp, not just the max —
    # P2 needs to know WHEN the peak actually happened relative to a scheduled contact.
    kp_readings = [
        {
            "time": k.get("observedTime"),
            "kp_index": k.get("kpIndex"),
            "source": k.get("source"),
        }
        for k in kp_values
    ]
    max_kp = max((k.get("kpIndex", 0) for k in kp_values), default=None)
    max_kp_time = None
    if kp_readings:
        peak_reading = max(kp_readings, key=lambda r: (r["kp_index"] if r["kp_index"] is not None else -1))
        max_kp_time = peak_reading["time"]

    return {
        "event_type": "geomagnetic_storm",
        "event_id": raw.get("gstID"),
        "start_time": raw.get("startTime"),
        "max_kp_index": max_kp,  # Kp scale 0-9, 5+ is considered a storm
        "max_kp_time": max_kp_time,  # when the peak actually occurred
        "kp_readings": kp_readings,  # full timeline of every reading, in case P2 needs more than just the peak
        "advisory": f"Geomagnetic storm (max Kp {max_kp}) — possible satellite tracking/comms disruption",
    }


def fetch_space_weather_events(
    start_date: str, end_date: str, force_refresh: bool = False
) -> dict:
    """Fetch and normalize all space-weather advisory events (flares + storms)
    for a date range, in a shared shape ready for risk.py to consume.

    Args:
        start_date: 'YYYY-MM-DD'
        end_date: 'YYYY-MM-DD'
        force_refresh: bypass the 6-hour cache and re-fetch from NASA

    Returns:
        {
            "events": [...],               # normalized advisory dicts, sorted by start_time
            "fetch_status": {
                "FLR": "ok" | "stale" | "failed",
                "GST": "ok" | "stale" | "failed",
            }
        }

        Status meanings:
        - "ok": fresh usable data from DONKI or the fresh cache; this includes
          a successful response containing zero events.
        - "stale": a DONKI refresh failed and stale cached data was returned.
        - "failed": neither DONKI nor the cache provided usable data.

        IMPORTANT for P2: an empty events list only means clear weather if
        fetch_status says "ok" for that type. If fetch_status says "stale" or
        "failed", treat it as unknown risk, not confirmed-clear — don't
        schedule as if it's safe just because the list is empty.
    """
    events: List[dict] = []
    fetch_status: dict[EventType, FetchStatus] = {"FLR": "failed", "GST": "failed"}

    try:
        flares, fetch_status["FLR"] = _fetch_donki_events(
            "FLR", start_date, end_date, force_refresh
        )
        events.extend(_normalize_flare(f) for f in flares)
    except SpaceWeatherError as exc:
        print(f"[space_weather] WARNING: FLR fetch failed: {exc}")
        fetch_status["FLR"] = "failed"

    try:
        storms, fetch_status["GST"] = _fetch_donki_events(
            "GST", start_date, end_date, force_refresh
        )
        events.extend(_normalize_geomagnetic_storm(s) for s in storms)
    except SpaceWeatherError as exc:
        print(f"[space_weather] WARNING: GST fetch failed: {exc}")
        fetch_status["GST"] = "failed"

    events.sort(key=lambda e: e.get("start_time") or "")
    return {"events": events, "fetch_status": fetch_status}


if __name__ == "__main__":
    from datetime import datetime, timedelta, timezone

    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=7)
    print(f"Fetching space-weather advisories from {start} to {end}...")
    result = fetch_space_weather_events(str(start), str(end))
    print(f"Fetch status: {result['fetch_status']}")
    print(f"Found {len(result['events'])} advisory event(s):")
    print(json.dumps(result["events"], indent=2))
