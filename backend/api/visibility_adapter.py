"""Convert P1 visibility results into P2's scheduling input structure."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Protocol


class VisibilityWindowSource(Protocol):
    satellite_id: str
    station: str
    visibility_start: str
    visibility_end: str
    duration_seconds: int
    max_elevation_deg: float


def _iso_utc(value: datetime | str) -> str:
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        parsed = value

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _window_id(window: VisibilityWindowSource) -> str:
    identity = "|".join(
        (
            window.satellite_id,
            window.station,
            window.visibility_start,
            window.visibility_end,
        )
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16].upper()
    return f"VW_{digest}"


def adapt_visibility_for_scheduler(
    windows: Iterable[VisibilityWindowSource],
    planning_start: datetime | str,
    planning_end: datetime | str,
    minimum_elevation_deg: float,
) -> dict:
    """Return P1 windows in P2's frozen visibility input structure.

    The adapter intentionally requires P1 ``VisibilityWindow`` objects because
    the frozen serialized P1 contract contains a display name but no stable
    satellite ID. It never attempts to infer identity from that display name.
    """
    adapted_windows = []

    for window in windows:
        if not window.satellite_id.startswith("NORAD_"):
            raise ValueError(
                f"Visibility window has no stable NORAD identity: {window.satellite_id!r}"
            )

        adapted_windows.append(
            {
                "window_id": _window_id(window),
                "satellite_id": window.satellite_id,
                "station_id": window.station,
                "aos": window.visibility_start,
                "los": window.visibility_end,
                "duration_seconds": window.duration_seconds,
                "max_elevation_deg": window.max_elevation_deg,
            }
        )

    return {
        "planning_horizon": {
            "start": _iso_utc(planning_start),
            "end": _iso_utc(planning_end),
        },
        "minimum_elevation_deg": float(minimum_elevation_deg),
        "visibility_windows": adapted_windows,
    }
