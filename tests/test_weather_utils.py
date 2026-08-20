from unittest.mock import MagicMock

import utils.weather_utils as weather_utils


def test_fetch_weather_forecast_groups_time_slots(monkeypatch):
    geo_response = MagicMock()
    geo_response.json.return_value = [
        {"lat": "28.61", "lon": "77.20"}
    ]
    geo_response.raise_for_status.return_value = None

    forecast_response = MagicMock()
    forecast_response.json.return_value = {
        "hourly": {
            "time": [
                "2026-09-01T08:00",
                "2026-09-01T14:00",
                "2026-09-01T19:00",
                "2026-09-01T23:00",
            ],
            "temperature_2m": [21, 28, 24, 20],
            "weathercode": [0, 2, 61, 3],
        }
    }
    forecast_response.raise_for_status.return_value = None

    responses = [geo_response, forecast_response]

    monkeypatch.setattr(
        weather_utils.requests,
        "get",
        lambda *args, **kwargs: responses.pop(0),
    )

    result = weather_utils.fetch_weather_forecast(
        "Delhi",
        "2026-09-01",
        num_days=1,
    )

    assert result["1"]["morning"]["weather"] == "Clear"
    assert result["1"]["morning"]["temp"] == 21

    assert result["1"]["afternoon"]["weather"] == "Partly cloudy"
    assert result["1"]["evening"]["weather"] == "Slight rain"

    # 23:00 should be ignored
    assert len(result["1"]) == 3


def test_fetch_weather_returns_empty_for_unknown_location(monkeypatch):
    geo_response = MagicMock()
    geo_response.json.return_value = []
    geo_response.raise_for_status.return_value = None

    monkeypatch.setattr(
        weather_utils.requests,
        "get",
        lambda *args, **kwargs: geo_response,
    )

    result = weather_utils.fetch_weather_forecast(
        "NotARealPlaceXYZ",
        "2026-09-01",
    )

    assert result == {}