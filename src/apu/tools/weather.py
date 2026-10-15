"""Vremenska prognoza (Open-Meteo, bez ključa). Preneto iz weather.js.

Ovo je PRIMER kako se stari alat prebacuje: pydantic model za ulaz,
async funkcija, dekorator. Isti šablon važi za svih 46 starih alata.
"""

import httpx
from pydantic import BaseModel, Field

from apu.config import settings
from apu.tools.registry import tool

WMO = {
    0: "vedro ☀️", 1: "pretežno vedro 🌤️", 2: "promenljivo oblačno ⛅", 3: "oblačno ☁️",
    45: "magla 🌫️", 48: "ledena magla 🌫️", 51: "slaba rosulja 🌦️", 53: "rosulja 🌦️",
    55: "jaka rosulja 🌧️", 61: "slaba kiša 🌦️", 63: "kiša 🌧️", 65: "jaka kiša 🌧️",
    71: "slab sneg 🌨️", 73: "sneg 🌨️", 75: "jak sneg ❄️", 80: "pljuskovi 🌦️",
    81: "jaki pljuskovi 🌧️", 82: "veoma jaki pljuskovi ⛈️", 95: "grmljavina ⛈️",
    96: "grmljavina sa gradom ⛈️", 99: "jaka grmljavina sa gradom ⛈️",
}  # fmt: skip


class WeatherArgs(BaseModel):
    dana: int = Field(1, ge=1, le=7, description="Za koliko dana unapred (1 = danas).")


@tool("weather_get", "Vremenska prognoza za korisnikov grad, za danas ili do 7 dana unapred.")
async def weather_get(args: WeatherArgs) -> dict:
    cfg = settings()
    params = {
        "latitude": cfg.weather_lat,
        "longitude": cfg.weather_lon,
        "current": "temperature_2m,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": cfg.timezone,
        "forecast_days": args.dana,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
        r.raise_for_status()
        data = r.json()

    d = data["daily"]
    return {
        "lokacija": cfg.weather_location,
        "sada": {
            "temperatura": data["current"]["temperature_2m"],
            "opis": WMO.get(data["current"]["weather_code"], "nepoznato"),
            "vetar_kmh": data["current"]["wind_speed_10m"],
        },
        "dani": [
            {
                "datum": d["time"][i],
                "opis": WMO.get(d["weather_code"][i], "nepoznato"),
                "max": d["temperature_2m_max"][i],
                "min": d["temperature_2m_min"][i],
                "sansa_padavina": d["precipitation_probability_max"][i],
            }
            for i in range(len(d["time"]))
        ],
    }
