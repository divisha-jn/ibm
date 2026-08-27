import requests

from backend.data import space_weather


class _Response:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


def test_fresh_success_with_zero_events_has_ok_status(monkeypatch, tmp_path):
    monkeypatch.setattr(space_weather, "RAW_CACHE_DIR", tmp_path)
    monkeypatch.setattr(
        space_weather.requests,
        "get",
        lambda *args, **kwargs: _Response([]),
    )

    result = space_weather.fetch_space_weather_events(
        "2026-08-20", "2026-08-27", force_refresh=True
    )

    assert result == {
        "events": [],
        "fetch_status": {"FLR": "ok", "GST": "ok"},
    }


def test_fresh_cache_is_ok_without_calling_nasa(monkeypatch, tmp_path):
    monkeypatch.setattr(space_weather, "RAW_CACHE_DIR", tmp_path)
    for event_type in ("FLR", "GST"):
        space_weather._cache_path(
            event_type, "2026-08-20", "2026-08-27"
        ).write_text("[]")

    def unexpected_request(*args, **kwargs):
        raise AssertionError("fresh cache must not call NASA")

    monkeypatch.setattr(space_weather.requests, "get", unexpected_request)

    result = space_weather.fetch_space_weather_events("2026-08-20", "2026-08-27")

    assert result["fetch_status"] == {"FLR": "ok", "GST": "ok"}


def test_nasa_failure_with_cache_has_stale_status(monkeypatch, tmp_path):
    monkeypatch.setattr(space_weather, "RAW_CACHE_DIR", tmp_path)
    for event_type in ("FLR", "GST"):
        space_weather._cache_path(
            event_type, "2026-08-20", "2026-08-27"
        ).write_text("[]")

    def failed_request(*args, **kwargs):
        raise requests.RequestException("DONKI unavailable")

    monkeypatch.setattr(space_weather.requests, "get", failed_request)

    result = space_weather.fetch_space_weather_events(
        "2026-08-20", "2026-08-27", force_refresh=True
    )

    assert result == {
        "events": [],
        "fetch_status": {"FLR": "stale", "GST": "stale"},
    }


def test_nasa_failure_without_cache_has_failed_status(monkeypatch, tmp_path):
    monkeypatch.setattr(space_weather, "RAW_CACHE_DIR", tmp_path)

    def failed_request(*args, **kwargs):
        raise requests.RequestException("DONKI unavailable")

    monkeypatch.setattr(space_weather.requests, "get", failed_request)

    result = space_weather.fetch_space_weather_events(
        "2026-08-20", "2026-08-27", force_refresh=True
    )

    assert result == {
        "events": [],
        "fetch_status": {"FLR": "failed", "GST": "failed"},
    }


def test_gst_normalization_preserves_kp_time_index_and_source():
    result = space_weather._normalize_geomagnetic_storm(
        {
            "gstID": "GST_1",
            "startTime": "2026-08-25T06:00:00Z",
            "allKpIndex": [
                {
                    "observedTime": "2026-08-25T09:00:00Z",
                    "kpIndex": 6,
                    "source": "NOAA",
                },
                {
                    "observedTime": "2026-08-25T12:00:00Z",
                    "kpIndex": 7,
                },
            ],
        }
    )

    assert result["kp_readings"] == [
        {
            "time": "2026-08-25T09:00:00Z",
            "kp_index": 6,
            "source": "NOAA",
        },
        {
            "time": "2026-08-25T12:00:00Z",
            "kp_index": 7,
            "source": None,
        },
    ]
    assert result["max_kp_index"] == 7
    assert result["max_kp_time"] == "2026-08-25T12:00:00Z"


def test_flare_normalization_contract_is_unchanged():
    raw = {
        "flrID": "FLR_1",
        "beginTime": "2026-08-25T09:00:00Z",
        "peakTime": "2026-08-25T09:05:00Z",
        "endTime": "2026-08-25T09:10:00Z",
        "classType": "M2.3",
        "sourceLocation": "N15E20",
    }

    assert space_weather._normalize_flare(raw) == {
        "event_type": "solar_flare",
        "event_id": "FLR_1",
        "start_time": "2026-08-25T09:00:00Z",
        "peak_time": "2026-08-25T09:05:00Z",
        "end_time": "2026-08-25T09:10:00Z",
        "class_type": "M2.3",
        "source_location": "N15E20",
        "advisory": "Solar flare (M2.3) — possible HF/radio signal degradation",
    }
