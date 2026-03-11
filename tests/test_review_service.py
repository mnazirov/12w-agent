"""Tests for review_service — weekly scoring and review."""
from __future__ import annotations

import json

import pytest

from app.services.review_service import WeeklyReviewResponse, format_review_message


class TestWeeklyReviewResponse:
    """Test Pydantic model validation for weekly reviews."""

    def test_valid_review(self, sample_review_json: str) -> None:
        data = json.loads(sample_review_json)
        review = WeeklyReviewResponse.model_validate(data)

        assert review.score_pct == 78
        assert len(review.wins) == 2
        assert len(review.improvements) == 2
        assert len(review.adjustments) == 1
        assert review.vision_reminder != ""
        assert review.next_week_focus != ""

    def test_minimal_review(self) -> None:
        review = WeeklyReviewResponse.model_validate({
            "score_pct": 100,
            "wins": ["Всё сделал"],
        })
        assert review.score_pct == 100
        assert review.improvements == []

    def test_score_boundaries(self) -> None:
        review_low = WeeklyReviewResponse(score_pct=0)
        review_high = WeeklyReviewResponse(score_pct=100)
        assert review_low.score_pct == 0
        assert review_high.score_pct == 100


class TestFormatReviewMessage:
    """Test formatting of weekly review for Telegram."""

    def test_format_includes_score(self, sample_review_json: str) -> None:
        data = json.loads(sample_review_json)
        review = WeeklyReviewResponse.model_validate(data)
        stats = {"planned": 18, "completed": 14, "missed": 4, "score_pct": 78}
        text = format_review_message(review, stats)

        assert "78%" in text
        assert "14/18" in text
        assert "Что получилось" in text
        assert "Что улучшить" in text

    def test_format_perfect_week(self) -> None:
        review = WeeklyReviewResponse(
            score_pct=100,
            wins=["Всё сделал"],
            vision_reminder="Ты молодец",
        )
        stats = {"planned": 15, "completed": 15, "missed": 0, "score_pct": 100}
        text = format_review_message(review, stats)
        assert "100%" in text
