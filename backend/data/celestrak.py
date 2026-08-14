"""
backend/data/celestrak.py

Fetches real satellite orbital element (GP/TLE) data from CelesTrak and
caches it locally so the team isn't hammering CelesTrak on every run and
still has data if CelesTrak is briefly down mid-demo.

CelesTrak GP JSON endpoint docs: https://celestrak.org/NORAD/documentation/gp-data-formats.php

Usage:
    from backend.data.celestrak import fetch_satellite, fetch_by_catalog_numbers

    sat = fetch_satellite("ISS (ZARYA)")
    sats = fetch_by_catalog_numbers([25544, 48274])
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List, Optional

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_CACHE_DIR = REPO_ROOT / "backend" / "data" / "raw"
RAW_CACHE_DIR.mkdir(parents=True, exist_ok=True)

CELESTRAK_GP_URL = "https://celestrak.org/NORAD/elements/gp.php"
CACHE_MAX_AGE_SECONDS = 6 * 60 * 60  # 6 hours — orbital elements don't need to be fresher than this for a demo

# Track a fixed, curated satellite list for the hackathon so the "5-10 satellites"
# scope stays deterministic and demo-safe rather than pulling a random slice.
# NOTE: verify these NORAD catalog numbers at celestrak.org before the demo —
# swap in whichever satellites you actually want to feature.
DEMO_CATALOG_NUMBERS = [
    25544,  # ISS (ZARYA)
    48274,  # NOAA-20
    43013,  # NOAA-1 (placeholder — confirm real ID)
    33591,  # NOAA-19
    27424,  # AQUA
]


class CelesTrakError(RuntimeError):
    pass


def _cache_path(name: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    return RAW_CACHE_DIR / f"{safe}.json"


def _cache_is_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) < CACHE_MAX_AGE_SECONDS


def _fetch_gp_json(params: dict, cache_key: str, force_refresh: bool = False) -> List[dict]:
    cache_file = _cache_path(cache_key)

    if not force_refresh and _cache_is_fresh(cache_file):
        with open(cache_file, "r") as f:
            return json.load(f)

    query = dict(params)
    query["FORMAT"] = "json"

    try:
        resp = requests.get(CELESTRAK_GP_URL, params=query, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, json.JSONDecodeError) as exc:
        # Fall back to stale cache rather than crashing the whole pipeline mid-demo
        if cache_file.exists():
            with open(cache_file, "r") as f:
                return json.load(f)
        raise CelesTrakError(f"Failed to fetch CelesTrak data and no cache available: {exc}") from exc

    if not data:
        raise CelesTrakError(f"CelesTrak returned no GP data for params={params}")

    with open(cache_file, "w") as f:
        json.dump(data, f, indent=2)

    return data


def fetch_satellite(name: str, force_refresh: bool = False) -> dict:
    """Fetch one satellite's GP data by name, e.g. 'ISS (ZARYA)'."""
    data = _fetch_gp_json({"NAME": name}, cache_key=f"name_{name}", force_refresh=force_refresh)
    return data[0]


def fetch_by_catalog_number(catalog_number: int, force_refresh: bool = False) -> dict:
    """Fetch one satellite's GP data by NORAD catalog number (most reliable lookup)."""
    data = _fetch_gp_json(
        {"CATNR": str(catalog_number)}, cache_key=f"catnr_{catalog_number}", force_refresh=force_refresh
    )
    return data[0]


def fetch_by_catalog_numbers(catalog_numbers: List[int], force_refresh: bool = False) -> List[dict]:
    """Fetch GP data for multiple satellites. Skips any single satellite that fails
    (e.g. bad catalog number) rather than failing the whole batch, and prints a warning."""
    results = []
    for catnr in catalog_numbers:
        try:
            results.append(fetch_by_catalog_number(catnr, force_refresh=force_refresh))
        except CelesTrakError as exc:
            print(f"[celestrak] WARNING: skipping catalog number {catnr}: {exc}")
    return results


def fetch_demo_catalog(force_refresh: bool = False) -> List[dict]:
    """Fetch the curated demo satellite set (~5 satellites) used for the hackathon build."""
    return fetch_by_catalog_numbers(DEMO_CATALOG_NUMBERS, force_refresh=force_refresh)


if __name__ == "__main__":
    print("Fetching ISS (ZARYA) from CelesTrak...")
    sat = fetch_satellite("ISS (ZARYA)")
    print(json.dumps(sat, indent=2))