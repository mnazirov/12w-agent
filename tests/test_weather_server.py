"""Tests for Weather MCP server logic."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from weather_mcp import server as weather_server


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    responses: list[_FakeResponse] = []
    calls: list[tuple[str, dict | None]] = []

    def __init__(self, *args, **kwargs) -> None:
        _ = (args, kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, params: dict | None = None):
        self.calls.append((url, params))
        if not self.responses:
            raise RuntimeError("No fake response configured")
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def _reset_cache_and_http(monkeypatch):
    weather_server._cache.clear()
    _FakeAsyncClient.responses = []
    _FakeAsyncClient.calls = []
    monkeypatch.setattr(weather_server.httpx, "AsyncClient", _FakeAsyncClient)


def _geocode_ok(city: str = "Москва") -> _FakeResponse:
    return _FakeResponse(
        200,
        {
            "results": [
                {
                    "name": city,
                    "country": "Россия",
                    "latitude": 55.75,
                    "longitude": 37.62,
                    "timezone": "Europe/Moscow",
                }
            ]
        },
    )


def _forecast_ok(
    *,
    precipitation: float = 0.0,
    precipitation_probability: int = 0,
    wind: float | None = 10,
    temp_min: float = 15,
    temp_max: float = 22,
    weather_code: int = 1,
) -> _FakeResponse:
    return _FakeResponse(
        200,
        {
            "current_weather": {
                "temperature": 19.5,
                "weathercode": weather_code,
            },
            "daily": {
                "time": ["2026-03-16"],
                "temperature_2m_max": [temp_max],
                "temperature_2m_min": [temp_min],
                "precipitation_sum": [precipitation],
                "precipitation_probability_max": [precipitation_probability],
                "weather_code": [weather_code],
                "wind_speed_10m_max": [wind],
            },
        },
    )


@pytest.mark.asyncio
async def test_get_weather_forecast_valid_city_returns_expected_structure() -> None:
    _FakeAsyncClient.responses = [_geocode_ok(), _forecast_ok()]

    result = await weather_server.get_weather_forecast("Москва")

    assert {"city", "timezone", "current", "forecast"}.issubset(result.keys())
    day = result["forecast"][0]
    assert {
        "date",
        "temp_max_c",
        "temp_min_c",
        "precipitation_mm",
        "wind_max_kmh",
        "description",
    }.issubset(day.keys())


@pytest.mark.asyncio
async def test_get_weather_forecast_unknown_city_returns_error() -> None:
    _FakeAsyncClient.responses = [_FakeResponse(200, {"results": []})]

    result = await weather_server.get_weather_forecast("НеизвестныйГород")

    assert "error" in result
    assert "не найден" in result["error"].lower()


@pytest.mark.asyncio
async def test_get_weather_forecast_days_are_clamped() -> None:
    _FakeAsyncClient.responses = [_geocode_ok("A"), _forecast_ok()]
    await weather_server.get_weather_forecast("A", days=0)

    _FakeAsyncClient.responses = [_geocode_ok("B"), _forecast_ok()]
    await weather_server.get_weather_forecast("B", days=10)

    forecast_calls = [
        params for url, params in _FakeAsyncClient.calls if url == weather_server.FORECAST_URL
    ]
    assert forecast_calls[0]["forecast_days"] == 1
    assert forecast_calls[1]["forecast_days"] == 7


@pytest.mark.asyncio
async def test_get_weather_forecast_open_meteo_500_returns_error() -> None:
    _FakeAsyncClient.responses = [_geocode_ok(), _FakeResponse(500, {"error": "boom"})]

    result = await weather_server.get_weather_forecast("Москва")

    assert result == {"error": "Сервис погоды временно недоступен."}


@pytest.mark.asyncio
async def test_get_weather_forecast_with_training_type_returns_assessment() -> None:
    _FakeAsyncClient.responses = [_geocode_ok(), _forecast_ok()]

    result = await weather_server.get_weather_forecast("Москва", training_type="running")

    assert "training_assessment" in result
    assessment = result["training_assessment"]
    assert isinstance(assessment["suitable"], bool)
    assert isinstance(assessment["recommendation"], str)
    assert "alternative" in assessment


def test_assess_training_good_weather_is_suitable() -> None:
    assessment = weather_server._assess_training(
        {
            "precipitation_mm": 0,
            "precipitation_probability_pct": 0,
            "temp_min_c": 18,
            "temp_max_c": 22,
            "wind_max_kmh": 10,
            "description": "Ясно",
        },
        "running",
    )
    assert assessment["suitable"] is True


def test_assess_training_rain_is_not_suitable() -> None:
    assessment = weather_server._assess_training(
        {
            "precipitation_mm": 10,
            "precipitation_probability_pct": 90,
            "temp_min_c": 18,
            "temp_max_c": 22,
            "wind_max_kmh": 10,
            "description": "Дождь",
        },
        "running",
    )
    assert assessment["suitable"] is False
    assert assessment["alternative"]


def test_assess_training_cycling_too_cold_is_not_suitable() -> None:
    assessment = weather_server._assess_training(
        {
            "precipitation_mm": 0,
            "precipitation_probability_pct": 0,
            "temp_min_c": -22,
            "temp_max_c": -20,
            "wind_max_kmh": 5,
            "description": "Ясно",
        },
        "cycling",
    )
    assert assessment["suitable"] is False


def test_assess_training_handles_none_wind_without_type_error() -> None:
    assessment = weather_server._assess_training(
        {
            "precipitation_mm": 0,
            "precipitation_probability_pct": 0,
            "temp_min_c": 18,
            "temp_max_c": 22,
            "wind_max_kmh": None,
            "description": "Ясно",
        },
        "running",
    )
    assert isinstance(assessment["suitable"], bool)


@pytest.mark.asyncio
async def test_weather_cache_returns_second_call_without_http() -> None:
    _FakeAsyncClient.responses = [_geocode_ok(), _forecast_ok()]

    await weather_server.get_weather_forecast("Москва")
    await weather_server.get_weather_forecast("Москва")

    assert len(_FakeAsyncClient.calls) == 2
    forecast_calls = [
        call for call in _FakeAsyncClient.calls if call[0] == weather_server.FORECAST_URL
    ]
    assert len(forecast_calls) == 1


@pytest.mark.asyncio
async def test_weather_cache_expires_after_16_minutes(monkeypatch) -> None:
    class _FakeDateTime:
        current = datetime(2026, 3, 16, 10, 0, 0)

        @classmethod
        def now(cls):
            return cls.current

    monkeypatch.setattr(weather_server, "datetime", _FakeDateTime)

    _FakeAsyncClient.responses = [_geocode_ok(), _forecast_ok(), _geocode_ok(), _forecast_ok()]

    await weather_server.get_weather_forecast("Москва")
    _FakeDateTime.current += timedelta(minutes=16)
    await weather_server.get_weather_forecast("Москва")

    forecast_calls = [
        call for call in _FakeAsyncClient.calls if call[0] == weather_server.FORECAST_URL
    ]
    assert len(forecast_calls) == 2


def test_code_to_text_known_and_unknown() -> None:
    assert weather_server._code_to_text(0) == "Ясно"
    assert weather_server._code_to_text(777) == "Код 777"
