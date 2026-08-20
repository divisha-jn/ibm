"""
backend/data/passes.py

Core of Person 1's pipeline:

    CelesTrak GP data -> Skyfield/SGP4 -> real visibility windows

Computes when a satellite is above a ground station's minimum elevation
angle within a given time horizon, and emits results in the shared
contract format (see contracts/visibility_windows.example.json) that
Person 2 (solver), Person 4 (backend) and Person 5 (frontend) all consume.

Usage:
    python -m backend.data.passes          # Day-1 goal: print one real pass
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

from skyfield.api import EarthSatellite, load, wgs84

from backend.data.celestrak import fetch_satellite, fetch_demo_catalog
from backend.data.ground_stations import GroundStation, load_ground_stations

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATED_DIR = REPO_ROOT / "backend" / "data" / "generated"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)

# Skyfield timescale — load once, reused across all pass computations.
_TS = load.timescale()


@dataclass(frozen=True)
class VisibilityWindow:
    """Matches contracts/visibility_windows.example.json"""

    satellite: str
    station: str
    visibility_start: str  # ISO 8601 UTC
    visibility_end: str  # ISO 8601 UTC
    max_elevation_deg: float
    duration_seconds: int

    def to_dict(self) -> dict:
        return asdict(self)


def satellite_from_omm(omm_json: dict) -> EarthSatellite:
    """Build a Skyfield EarthSatellite straight from a CelesTrak GP JSON record."""
    return EarthSatellite.from_omm(_TS, omm_json)


def find_visibility_windows(
    sat: EarthSatellite,
    station: GroundStation,
    start: datetime,
    end: datetime,
    satellite_label: str | None = None,
) -> List[VisibilityWindow]:
    """Find all windows in [start, end] where `sat` is above `station`'s
    minimum elevation angle, using Skyfield's built-in event finder
    (rise above / culminate / set below the given elevation)."""
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    topos = wgs84.latlon(station.latitude, station.longitude, elevation_m=station.elevation_m)
    difference = sat - topos

    t0 = _TS.from_datetime(start)
    t1 = _TS.from_datetime(end)

    times, events = sat.find_events(
        topos, t0, t1, altitude_degrees=station.min_elevation_deg
    )
    # events: 0 = rise above min elevation, 1 = culminate, 2 = set below min elevation

    windows: List[VisibilityWindow] = []
    rise_time = None
    max_elevation = 0.0

    for t, event in zip(times, events):
        if event == 0:  # rise
            rise_time = t
            max_elevation = 0.0
        elif event == 1:  # culminate — track peak elevation within the pass
            alt, _, _ = difference.at(t).altaz()
            max_elevation = max(max_elevation, alt.degrees)
        elif event == 2 and rise_time is not None:  # set — window complete
            set_time = t
            duration = (set_time.utc_datetime() - rise_time.utc_datetime()).total_seconds()
            windows.append(
                VisibilityWindow(
                    satellite=satellite_label or sat.name,
                    station=station.id,
                    visibility_start=rise_time.utc_datetime().replace(microsecond=0).isoformat(),
                    visibility_end=set_time.utc_datetime().replace(microsecond=0).isoformat(),
                    max_elevation_deg=round(max_elevation, 1),
                    duration_seconds=int(duration),
                )
            )
            rise_time = None

    return windows


def generate_all_visibility_windows(
    horizon_hours: int = 48,
    force_refresh_celestrak: bool = False,
) -> List[VisibilityWindow]:
    """Scale step: compute visibility windows for the full demo satellite set
    (~5 satellites) across all configured ground stations (~2-3 stations)
    over a fixed planning horizon."""
    stations = load_ground_stations()
    gp_records = fetch_demo_catalog(force_refresh=force_refresh_celestrak)

    start = datetime.now(timezone.utc)
    end = start + timedelta(hours=horizon_hours)

    all_windows: List[VisibilityWindow] = []
    for gp in gp_records:
        sat = satellite_from_omm(gp)
        label = gp.get("OBJECT_NAME", sat.name).strip()
        for station in stations:
            windows = find_visibility_windows(sat, station, start, end, satellite_label=label)
            all_windows.extend(windows)

    all_windows.sort(key=lambda w: w.visibility_start)
    return all_windows


def save_visibility_windows(windows: List[VisibilityWindow], filename: str = "visibility_windows.json") -> Path:
    out_path = GENERATED_DIR / filename
    with open(out_path, "w") as f:
        json.dump([w.to_dict() for w in windows], f, indent=2)
    return out_path

def get_visibility_windows(
    horizon_hours: int = 48,
    force_refresh_celestrak: bool = False,
) -> List[dict]:
    """Convenience wrapper for Person 4's backend: one call that returns
    ready-to-serve plain dicts (JSON-serializable) matching Contract #3,
    instead of needing to call generate + save + to_dict separately.

    Example:
        from backend.data.passes import get_visibility_windows
        windows = get_visibility_windows()   # -> list[dict], ready for a JSON response
    """
    windows = generate_all_visibility_windows(
        horizon_hours=horizon_hours, force_refresh_celestrak=force_refresh_celestrak
    )
    return [w.to_dict() for w in windows]


def _day1_single_pass_demo() -> None:
    """Day-1 goal: retrieve one real satellite from CelesTrak and print one
    real pass over one ground station."""
    print("Fetching ISS (ZARYA) orbital data from CelesTrak...")
    gp = fetch_satellite("ISS (ZARYA)")
    sat = satellite_from_omm(gp)

    stations = load_ground_stations()
    station = stations[0]
    print(f"Using ground station: {station.name} ({station.id})")

    start = datetime.now(timezone.utc)
    end = start + timedelta(hours=48)

    windows = find_visibility_windows(sat, station, start, end, satellite_label="ISS (ZARYA)")

    if not windows:
        print("No visibility windows found in the next 48 hours for this station. "
              "Try a longer horizon or a different station.")
        return

    w = windows[0]
    print("\nFirst real pass found:")
    print(json.dumps(w.to_dict(), indent=2))


if __name__ == "__main__":
    _day1_single_pass_demo()