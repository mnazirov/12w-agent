"""Tests for checkin_service — evening check-in analysis."""
from __future__ import annotations

import json

import pytest

from app.services.checkin_service import CheckinAnalysis, WoopItem, format_checkin_analysis


class TestCheckinAnalysis:
    """Test Pydantic model validation for check-in analysis."""

    def test_valid_analysis(self, sample_checkin_json: str) -> None:
        data = json.loads(sample_checkin_json)
        analysis = CheckinAnalysis.model_validate(data)

        assert analysis.summary != ""
        assert len(analysis.controllable_factors) >= 1
        assert len(analysis.woop) == 1
        assert analysis.woop[0].wish == "Прочитать 30 минут"
        assert "Если" in analysis.woop[0].plan  # implementation intention
        assert analysis.lesson_prompt != ""
        assert analysis.tomorrow_suggestion != ""

    def test_minimal_analysis(self) -> None:
        analysis = CheckinAnalysis.model_validate({
            "summary": "Хороший день!",
        })
        assert analysis.summary == "Хороший день!"
        assert analysis.controllable_factors == []
        assert analysis.woop == []

    def test_woop_item_structure(self) -> None:
        woop = WoopItem.model_validate({
            "wish": "Пробежка",
            "outcome": "Здоровье",
            "obstacle": "Лень",
            "plan": "Если лень, то надену кроссовки",
        })
        assert woop.wish == "Пробежка"
        assert woop.plan.startswith("Если")


class TestFormatCheckinAnalysis:
    """Test formatting of check-in analysis for Telegram."""

    def test_format_includes_woop(self, sample_checkin_json: str) -> None:
        data = json.loads(sample_checkin_json)
        analysis = CheckinAnalysis.model_validate(data)
        text = format_checkin_analysis(analysis)

        assert "WOOP" in text
        assert "Желание" in text
        assert "Препятствие" in text
        assert "Что в твоих силах" in text

    def test_format_all_done(self) -> None:
        analysis = CheckinAnalysis(
            summary="Всё сделано!",
        )
        text = format_checkin_analysis(analysis)
        assert "Всё сделано!" in text
