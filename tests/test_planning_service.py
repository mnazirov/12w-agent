"""Tests for planning_service — daily plan generation."""
from __future__ import annotations

import pytest

from app.services.planning_service import DailyPlanResponse, format_plan_message


class TestDailyPlanResponse:
    """Test Pydantic model validation for daily plans."""

    def test_valid_plan(self, sample_plan_json: str) -> None:
        import json

        data = json.loads(sample_plan_json)
        plan = DailyPlanResponse.model_validate(data)

        assert len(plan.top_3) == 3
        assert plan.top_3[0].task == "Написать 500 слов для статьи"
        assert plan.top_3[0].implementation_intention != ""
        assert plan.top_3[0].starter_step != ""
        assert len(plan.extras) == 1
        assert plan.friction_tip != ""
        assert len(plan.timeblocks) == 3

    def test_minimal_plan(self) -> None:
        plan = DailyPlanResponse.model_validate({
            "top_3": [{"task": "Do something"}],
            "extras": [],
            "friction_tip": "",
            "timeblocks": [],
        })
        assert len(plan.top_3) == 1
        assert plan.top_3[0].task == "Do something"

    def test_empty_top3_rejected(self) -> None:
        with pytest.raises(Exception):
            DailyPlanResponse.model_validate({
                "top_3": [],
                "extras": [],
            })


class TestFormatPlanMessage:
    """Test plan formatting for Telegram."""

    def test_format_includes_tasks(self, sample_plan_json: str) -> None:
        import json

        data = json.loads(sample_plan_json)
        plan = DailyPlanResponse.model_validate(data)
        text = format_plan_message(plan)

        assert "Написать 500 слов" in text
        assert "Топ-3" in text
        assert "Стартовый шаг" in text
        assert "Снижение трения" in text


class TestGenerateDailyPlan:
    """Integration test stub for generate_daily_plan (requires mocked OpenAI)."""

    @pytest.mark.asyncio
    async def test_generate_with_mock(
        self, mock_openai_client, sample_plan_json: str
    ) -> None:
        """Verify that generate_daily_plan calls OpenAI and returns valid plan.

        NOTE: This is a stub — full integration requires a DB session.
        A complete test would use a test database or mock the repos layer.
        """
        # This test demonstrates the pattern; uncomment when DB fixtures are ready.
        # with mock_openai_client(sample_plan_json):
        #     plan = await generate_daily_plan(session, user_id=1)
        #     assert len(plan.top_3) == 3
        pass
