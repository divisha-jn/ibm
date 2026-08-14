"""
backend/data/ground_stations.py

Loads and validates ground station definitions from data/ground_stations.json.
This is the shared input file the rest of the team's code (solver, backend,
frontend) also reads indirectly through your visibility window output, so
keep the schema stable once others start consuming it.

Contract: contracts/ground_stations.example.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List

# Repo root is three levels up from this file: backend/data/ground_stations.py
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATIONS_PATH = REPO_ROOT / "data" / "ground_stations.json"

REQUIRED_FIELDS = {"id", "name", "latitude", "longitude", "elevation_m", "min_elevation_deg"}


@dataclass(frozen=True)
class GroundStation:
    id: str
    name: str
    latitude: float
    longitude: float
    elevation_m: float
    min_elevation_deg: float  # minimum antenna elevation angle counted as "visible"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "elevation_m": self.elevation_m,
            "min_elevation_deg": self.min_elevation_deg,
        }


class GroundStationValidationError(ValueError):
    pass


def _validate_raw(entry: dict) -> None:
    missing = REQUIRED_FIELDS - entry.keys()
    if missing:
        raise GroundStationValidationError(
            f"Ground station entry {entry.get('id', '<unknown>')} missing fields: {missing}"
        )
    if not (-90 <= entry["latitude"] <= 90):
        raise GroundStationValidationError(f"Invalid latitude for {entry['id']}: {entry['latitude']}")
    if not (-180 <= entry["longitude"] <= 180):
        raise GroundStationValidationError(f"Invalid longitude for {entry['id']}: {entry['longitude']}")
    if not (0 <= entry["min_elevation_deg"] < 90):
        raise GroundStationValidationError(
            f"Invalid min_elevation_deg for {entry['id']}: {entry['min_elevation_deg']}"
        )


def load_ground_stations(path: Path | str | None = None) -> List[GroundStation]:
    """Load and validate ground stations from JSON. Raises GroundStationValidationError
    on malformed entries so bad config fails loudly at startup, not deep in the solver."""
    p = Path(path) if path else DEFAULT_STATIONS_PATH
    if not p.exists():
        raise FileNotFoundError(
            f"Ground stations file not found at {p}. "
            f"Copy contracts/ground_stations.example.json to data/ground_stations.json to get started."
        )

    with open(p, "r") as f:
        raw = json.load(f)

    stations = []
    seen_ids = set()
    for entry in raw:
        _validate_raw(entry)
        if entry["id"] in seen_ids:
            raise GroundStationValidationError(f"Duplicate ground station id: {entry['id']}")
        seen_ids.add(entry["id"])
        stations.append(
            GroundStation(
                id=entry["id"],
                name=entry["name"],
                latitude=float(entry["latitude"]),
                longitude=float(entry["longitude"]),
                elevation_m=float(entry["elevation_m"]),
                min_elevation_deg=float(entry["min_elevation_deg"]),
            )
        )
    return stations


if __name__ == "__main__":
    stations = load_ground_stations()
    for s in stations:
        print(f"{s.id}: {s.name} ({s.latitude}, {s.longitude}) min_el={s.min_elevation_deg}deg")