"""Weather MCP Server.

Open-Meteo API: бесплатно, без ключей, глобальное покрытие.
Поля API в этом модуле сверены curl-запросом 2026-03-16:
- daily.weather_code
- daily.wind_speed_10m_max
- current_weather.weathercode
"""
from __future__ import annotations

import logging
from datetime import datetime

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("weather")

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HTTP_TIMEOUT = 15.0

_cache: dict[str, tuple[datetime, dict]] = {}
CACHE_TTL_SECONDS = 900  # 15 минут


WEATHER_DESCRIPTIONS: dict[int, str] = {
    0: "Ясно",
    1: "Преимущественно ясно",
    2: "Переменная облачность",
    3: "Пасмурно",
    45: "Туман",
    48: "Туман с изморозью",
    51: "Лёгкая морось",
    53: "Морось",
    55: "Сильная морось",
    56: "Ледяная морось",
    57: "Сильная ледяная морось",
    61: "Небольшой дождь",
    63: "Дождь",
    65: "Сильный дождь",
    66: "Ледяной дождь",
    67: "Сильный ледяной дождь",
    71: "Небольшой снег",
    73: "Снег",
    75: "Сильный снег",
    77: "Снежная крупа",
    80: "Небольшой ливень",
    81: "Ливень",
    82: "Сильный ливень",
    85: "Небольшой снегопад",
    86: "Сильный снегопад",
    95: "Гроза",
    96: "Гроза с небольшим градом",
    99: "Гроза с сильным градом",
}


def _cache_key(city: str, days: int) -> str:
    return f"{city.lower().strip()}:{days}"


def _get_cached(key: str) -> dict | None:
    record = _cache.get(key)
    if not record:
        return None

    cached_time, cached_data = record
    if (datetime.now() - cached_time).total_seconds() >= CACHE_TTL_SECONDS:
        return None
    return cached_data


def _set_cache(key: str, data: dict) -> None:
    _cache[key] = (datetime.now(), data)


def _code_to_text(code: int | None) -> str:
    if code is None:
        return "Нет данных"
    return WEATHER_DESCRIPTIONS.get(code, f"Код {code}")


def _value_at(values: list, index: int, default):
    if not isinstance(values, list) or index >= len(values):
        return default
    value = values[index]
    return default if value is None else value


async def _geocode(city: str) -> dict | None:
    """city -> {name, country, latitude, longitude, timezone}."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.get(
            GEOCODING_URL,
            params={
                "name": city,
                "count": 1,
                "language": "ru",
            },
        )
        if resp.status_code != 200:
            logger.warning("Geocoding failed (%d): %s", resp.status_code, resp.text)
            return None

        payload = resp.json()
        results = payload.get("results")
        if not results:
            return None

        match = results[0]
        return {
            "name": match.get("name", city),
            "country": match.get("country", ""),
            "latitude": match["latitude"],
            "longitude": match["longitude"],
            "timezone": match.get("timezone", "UTC"),
        }


@mcp.tool()
async def get_weather_forecast(
    city: str,
    days: int = 1,
    training_type: str = "",
) -> dict:
    """Прогноз погоды и оценка условий для outdoor-тренировки."""
    days = max(1, min(days, 7))

    ck = _cache_key(city, days)
    cached = _get_cached(ck)

    if cached is None:
        geo = await _geocode(city)
        if geo is None:
            return {
                "error": (
                    f"Город '{city}' не найден. "
                    "Попробуйте другое написание."
                )
            }

        daily_params = ",".join(
            [
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_sum",
                "precipitation_probability_max",
                "weather_code",
                "wind_speed_10m_max",
            ]
        )

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(
                FORECAST_URL,
                params={
                    "latitude": geo["latitude"],
                    "longitude": geo["longitude"],
                    "daily": daily_params,
                    "current_weather": True,
                    "timezone": geo["timezone"],
                    "forecast_days": days,
                },
            )
            if resp.status_code != 200:
                logger.error("Open-Meteo %d: %s", resp.status_code, resp.text)
                return {"error": "Сервис погоды временно недоступен."}

            data = resp.json()

        current = data.get("current_weather", {})
        daily = data.get("daily", {})
        dates = daily.get("time", []) if isinstance(daily, dict) else []

        forecast_list: list[dict] = []
        for i, date_str in enumerate(dates):
            forecast_list.append(
                {
                    "date": date_str,
                    "temp_max_c": _value_at(daily.get("temperature_2m_max", []), i, 20),
                    "temp_min_c": _value_at(daily.get("temperature_2m_min", []), i, 10),
                    "precipitation_mm": _value_at(daily.get("precipitation_sum", []), i, 0),
                    "precipitation_probability_pct": _value_at(
                        daily.get("precipitation_probability_max", []),
                        i,
                        0,
                    ),
                    "wind_max_kmh": _value_at(daily.get("wind_speed_10m_max", []), i, 0),
                    "description": _code_to_text(_value_at(daily.get("weather_code", []), i, None)),
                }
            )

        cached = {
            "city": f"{geo['name']}, {geo['country']}",
            "timezone": geo["timezone"],
            "current": {
                "temperature_c": current.get("temperature"),
                "description": _code_to_text(current.get("weathercode")),
            },
            "forecast": forecast_list,
        }
        _set_cache(ck, cached)

    result = {**cached}
    if training_type and cached.get("forecast"):
        result["training_assessment"] = _assess_training(cached["forecast"][0], training_type)

    return result


def _assess_training(today: dict, training_type: str) -> dict:
    """Единая оценка outdoor-тренировки на сегодня."""
    thresholds = {
        "running": {"max_precip": 3, "min_temp": -15, "max_temp": 35, "max_wind": 50},
        "cycling": {"max_precip": 1, "min_temp": -5, "max_temp": 35, "max_wind": 40},
        "walking": {"max_precip": 5, "min_temp": -20, "max_temp": 38, "max_wind": 60},
        "outdoor_gym": {"max_precip": 2, "min_temp": -10, "max_temp": 35, "max_wind": 50},
        "swimming_outdoor": {"max_precip": 0, "min_temp": 20, "max_temp": 40, "max_wind": 30},
        "hiking": {"max_precip": 2, "min_temp": -10, "max_temp": 35, "max_wind": 45},
    }
    rules = thresholds.get(training_type, thresholds["running"])

    alternatives = {
        "running": "беговая дорожка или тренажёрный зал",
        "cycling": "велотренажёр или spinning",
        "walking": "ходьба в ТЦ или степпер",
        "outdoor_gym": "зал или домашняя тренировка",
        "swimming_outdoor": "бассейн",
        "hiking": "кардио в зале",
    }

    precip = today.get("precipitation_mm", 0) or 0
    precip_prob = today.get("precipitation_probability_pct", 0) or 0
    temp_max = today.get("temp_max_c", 20) or 20
    temp_min = today.get("temp_min_c", 10) or 10
    wind = today.get("wind_max_kmh", 0) or 0
    desc = today.get("description", "")

    problems: list[str] = []
    if precip > rules["max_precip"] or precip_prob > 70:
        problems.append(f"осадки {precip}мм (вероятность {precip_prob}%)")
    if temp_max < rules["min_temp"]:
        problems.append(f"холодно ({temp_min}°..{temp_max}°C)")
    if temp_max > rules["max_temp"]:
        problems.append(f"жарко ({temp_max}°C)")
    if wind > rules["max_wind"]:
        problems.append(f"ветер {wind} км/ч")

    if not problems:
        return {
            "suitable": True,
            "recommendation": (
                f"Погода подходит для {training_type}: {desc}, "
                f"{temp_min}°..{temp_max}°C."
            ),
            "alternative": None,
        }

    return {
        "suitable": False,
        "recommendation": (
            f"Не рекомендуется {training_type} на улице: {', '.join(problems)}."
        ),
        "alternative": alternatives.get(training_type, "тренировка в помещении"),
    }


@mcp.tool()
async def health_check() -> dict:
    """Проверка работоспособности weather-сервера."""
    return {"status": "ok"}
