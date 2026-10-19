"""Završni audit pokriva i prvobitni primer alata, bez pravih zahteva za prognozu."""

import pytest

from dexter.config import settings
from dexter.tools import registry
from dexter.tools.weather import WeatherArgs, weather_get


@pytest.mark.parametrize("days", [1, 7])
async def test_weather_keeps_configured_location_units_timezone_and_day_count(
    monkeypatch, respx_mock, days
):
    cfg = settings()
    monkeypatch.setattr(cfg, "weather_lat", 45.0)
    monkeypatch.setattr(cfg, "weather_lon", 20.0)
    monkeypatch.setattr(cfg, "weather_location", "Probni grad")
    route = respx_mock.get("https://api.open-meteo.com/v1/forecast").respond(
        200,
        json={
            "current": {"temperature_2m": 12, "weather_code": 0, "wind_speed_10m": 5},
            "daily": {
                "time": [f"2026-10-{19 + i}" for i in range(days)],
                "weather_code": [999] * days,
                "temperature_2m_max": [15] * days,
                "temperature_2m_min": [8] * days,
                "precipitation_probability_max": [20] * days,
            },
        },
    )
    result = await weather_get(WeatherArgs(dana=days))
    assert result["lokacija"] == "Probni grad" and result["sada"]["vetar_kmh"] == 5
    assert result["sada"]["opis"] == "vedro ☀️" and len(result["dani"]) == days
    assert result["dani"][0] == {
        "datum": "2026-10-19",
        "opis": "nepoznato",
        "max": 15,
        "min": 8,
        "sansa_padavina": 20,
    }
    params = route.calls[0].request.url.params
    assert params["latitude"] == "45.0" and params["longitude"] == "20.0"
    assert params["timezone"] == "Europe/Belgrade" and params["forecast_days"] == str(days)


async def test_weather_http_failure_is_not_presented_as_forecast(respx_mock):
    respx_mock.get("https://api.open-meteo.com/v1/forecast").respond(503)
    outcome = await registry.execute("weather_get", {})
    assert outcome.is_error and "Greška" in outcome.text
