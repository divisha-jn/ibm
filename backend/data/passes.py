"""
backend/data/passes.py

Core of Person 1's pipeline:

    CelesTrak GP data -> Skyfield/SGP4 -> real visibility windows

Computes when a satellite is above a ground station's minimum elevation
angle within a given time horizon, and emits results in the shared
contract format (contracts/visibility_windows.example.json) that
Person 2 (solver), Person 4 (backend) and Person 5 (frontend) all consume.

Usage:
    python -m backend.data.passes          # Day-1 goal: print one real pass
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from skyfield.api import EarthSatellite, load, wgs84

from backend.data.celestrak import fetch_satellite, fetch_demo_catalog
from backend.data.ground_stations import GroundStation, load_ground_stations

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATED_DIR = REPO_ROOT / "backend" / "data" / "generated"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)

# Skyfield timescale — load once, reused across all pass computations.
_TS = load.timescale()


def _to_z(dt: datetime) -> str:
    """Return a UTC datetime as an ISO 8601 string ending in Z (not +00:00)."""
    return dt.replace(microsecond=0, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class VisibilityWindow:
    """
    One satellite pass over one ground station.
    Field names match contract #3 (visibility_windows.example.json) exactly
    so the dict output can be fed directly to the solver and frontend.
    """

    window_id: str           # e.g. "VW_0001"
    satellite_id: str        # e.g. "NORAD_25544"
    satellite: str           # display name, e.g. "ISS (ZARYA)"
    station_id: str          # e.g. "GS_SG_01"
    aos: str                 # ISO 8601 UTC, e.g. "2026-08-11T02:13:18Z"
    los: str                 # ISO 8601 UTC
    duration_seconds: int
    max_elevation_deg: float
    source: Dict             # orbit provenance metadata

    def to_dict(self) -> dict:
        # Keep the frozen P1 visibility contract unchanged. ``window_id``,
        # ``satellite_id`` and ``source`` are retained as internal provenance
        # for the P1 -> P2 adapter but are not part of the frozen contract.
        return {
            "satellite": self.satellite,
            "station": self.station_id,
            "visibility_start": self.aos,
            "visibility_end": self.los,
            "max_elevation_deg": self.max_elevation_deg,
            "duration_seconds": self.duration_seconds,
        }


def satellite_from_omm(omm_json: dict) -> EarthSatellite:
    """Build a Skyfield EarthSatellite straight from a CelesTrak GP JSON record."""
    return EarthSatellite.from_omm(_TS, omm_json)


def _norad_id(gp: dict) -> str:
    """Return a stable satellite_id string from a GP record, e.g. 'NORAD_25544'."""
    catnr = gp.get("NORAD_CAT_ID") or gp.get("CCSDS_OMID", "").split("-")[0]
    return f"NORAD_{catnr}"


def _source_block(gp: dict) -> dict:
    """Build the source provenance block required by contract #3."""
    return {
        "orbit_provider": "CelesTrak",
        "propagator": "SGP4",
        "calculation_library": "Skyfield",
        "orbit_epoch": gp.get("EPOCH", ""),
    }


def find_visibility_windows(
    sat: EarthSatellite,
    station: GroundStation,
    start: datetime,
    end: datetime,
    gp_record: Optional[dict] = None,
    satellite_id: Optional[str] = None,
    window_id_offset: int = 0,
) -> List[VisibilityWindow]:
    """Find all passes in [start, end] where `sat` is above `station`'s
    minimum elevation angle.

    Args:
        sat:              Skyfield EarthSatellite.
        station:          GroundStation (provides station_id and min elevation).
        start / end:      Planning horizon (timezone-aware recommended).
        gp_record:        Raw CelesTrak GP dict used for the source block and
                          satellite_id derivation.  Pass None only in tests.
        satellite_id:     Override the satellite_id string (used when gp_record
                          is unavailable, e.g. unit tests).
        window_id_offset: Starting index for sequential VW_NNNN IDs within this
                          call (so callers can produce globally unique IDs).
    """
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

    sat_id = satellite_id or (
        _norad_id(gp_record) if gp_record else sat.name.strip()
    )
    source = _source_block(gp_record) if gp_record else {}

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
            duration = int(
                (set_time.utc_datetime() - rise_time.utc_datetime()).total_seconds()
            )
            idx = window_id_offset + len(windows) + 1
            windows.append(
                VisibilityWindow(
                    window_id=f"VW_{idx:04d}",
                    satellite_id=sat_id,
                    satellite=sat.name.strip(),
                    station_id=station.id,
                    aos=_to_z(rise_time.utc_datetime()),
                    los=_to_z(set_time.utc_datetime()),
                    duration_seconds=duration,
                    max_elevation_deg=round(max_elevation, 1),
                    source=source,
                )
            )
            rise_time = None

    return windows


def generate_all_visibility_windows(
    horizon_hours: int = 48,
    force_refresh_celestrak: bool = False,
) -> List[VisibilityWindow]:
    """Compute visibility windows for the full demo satellite set (~5 satellites)
    across all configured ground stations over a fixed planning horizon.

    Window IDs are assigned sequentially (VW_0001, VW_0002, …) across the
    full output so every ID is unique within one planning run.
    """
    stations = load_ground_stations()
    gp_records = fetch_demo_catalog(force_refresh=force_refresh_celestrak)

    start = datetime.now(timezone.utc)
    end = start + timedelta(hours=horizon_hours)

    all_windows: List[VisibilityWindow] = []
    for gp in gp_records:
        sat = satellite_from_omm(gp)
        sat_id = _norad_id(gp)
        for station in stations:
            new_windows = find_visibility_windows(
                sat,
                station,
                start,
                end,
                gp_record=gp,
                satellite_id=sat_id,
                window_id_offset=len(all_windows),
            )
            all_windows.extend(new_windows)

    all_windows.sort(key=lambda w: w.aos)
    return all_windows


def save_visibility_windows(
    windows: List[VisibilityWindow],
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    minimum_elevation_deg: float = 10.0,
    filename: str = "visibility_windows.json",
) -> Path:
    """Serialise windows to disk in the full contract #3 envelope:

        {
          "planning_horizon": { "start": "...", "end": "..." },
          "minimum_elevation_deg": 10.0,
          "visibility_windows": [ ... ]
        }

    start / end default to now and now+48 h if omitted.
    """
    now = datetime.now(timezone.utc)
    horizon_start = start or now
    horizon_end = end or (now + timedelta(hours=48))

    payload = {
        "planning_horizon": {
            "start": _to_z(horizon_start),
            "end": _to_z(horizon_end),
        },
        "minimum_elevation_deg": minimum_elevation_deg,
        "visibility_windows": [w.to_dict() for w in windows],
    }

    out_path = GENERATED_DIR / filename
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)
    return out_path


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

    windows = find_visibility_windows(
        sat, station, start, end,
        gp_record=gp,
        satellite_id=_norad_id(gp),
    )

    if not windows:
        print("No visibility windows found in the next 48 hours for this station. "
              "Try a longer horizon or a different station.")
        return

    w = windows[0]
    print("\nFirst real pass found:")
    print(json.dumps(w.to_dict(), indent=2))


if __name__ == "__main__":
    _day1_single_pass_demo()
