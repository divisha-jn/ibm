"""
backend/data/space_weather.py

STRETCH GOAL — only build this out once the core pipeline (steps 1-11 of the
build plan) is stable. Placeholder now so the module exists and the API layer
(Person 4) can wire an endpoint against it early without waiting on you.

Will fetch real space-weather advisory events (solar flares, geomagnetic
storms) from NASA DONKI: https://api.nasa.gov/DONKI/
"""

from __future__ import annotations

from typing import List


def fetch_space_weather_events(start_date: str, end_date: str) -> List[dict]:
    """Not yet implemented. Returns an empty advisory list so downstream code
    (risk overlay) can be built against a stable-but-empty contract now."""
    return []


if __name__ == "__main__":
    print("space_weather.py is a stretch-goal stub — not implemented yet.")