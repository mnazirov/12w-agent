"""
Client-side analytics pipeline orchestrator.

Composes MCP tools and OpenAI into a 4-step pipeline:
1. collect_week_data   (MCP) — raw data
2. analyze_patterns    (MCP) — statistical analysis
   get_previous_reports(MCP) — historical context
3. OpenAI              (AI)  — generate insights
4. save_weekly_report  (MCP) — persist enriched report
"""

import json
import logging

from app.services.mcp_client import MCPMotivationClient

logger = logging.getLogger(__name__)

_INSIGHTS_SYSTEM = """\
You are an analytics coach for the 12 Week Year methodology.
Given a weekly activity analysis and (optionally) previous week data,
write a brief Russian-language insight (3-5 sentences).

Include:
1. One specific observation about the user's pattern (best day, peak time, gaps).
2. Comparison with previous week if data exists (better/worse/same).
3. One concrete recommendation for next week.

Rules:
- Russian language only.
- No greetings.
- No English technical terms.
- 1 emoji max.
- Be specific: mention days, numbers, actions.
- If performance is low, be honest but supportive (CBT/ACT tone).
"""


def _build_insights_prompt(analysis: dict, previous: dict | None) -> str:
    """Build user prompt for AI insights generation."""
    real = analysis.get("real_actions_breakdown", {})
    lines = [
        f"Completion score: {analysis.get('completion_score', 0):.0%}",
        f"Active days: {analysis.get('active_days', 0)}/{analysis.get('period_days', 7)}",
        f"Plans: {real.get('plan', 0)}, Checkins: {real.get('checkin', 0)}, "
        f"Reviews: {real.get('review', 0)}",
        f"Streak: {analysis.get('current_streak', 0)} days",
        f"Peak time: {analysis.get('peak_time_block', 'unknown')}",
        f"Best day: {analysis.get('best_day', {}).get('date', 'none')} "
        f"({analysis.get('best_day', {}).get('score', 0)} actions)",
        f"Max consecutive missed: {analysis.get('max_consecutive_missed', 0)}",
        f"Recommendations: {analysis.get('recommendations', [])}",
    ]

    if previous and previous.get("reports"):
        last = previous["reports"][0]
        lines += [
            "",
            "Previous week:",
            f"  Score: {last.get('completion_score', '?')}",
            f"  Real actions: {last.get('real_actions_total', '?')}",
            f"  Active days: {last.get('active_days', '?')}",
            f"  Streak then: {last.get('current_streak', '?')}",
        ]
    else:
        lines.append("\nNo previous week data (first report).")

    return "\n".join(lines)


async def run_analytics_pipeline(
    mcp_client: MCPMotivationClient,
    openai_service,
    user_id: int,
    days: int = 7,
    vision: str | None = None,
) -> dict:
    """Run the full 4-step analytics pipeline with client-side orchestration.

    Returns dict with all results and pipeline metadata.
    Raises no exceptions — returns error info in result on failure.
    """
    pipeline_steps = []
    result = {"user_id": user_id, "success": False}

    # ── Step 1: Collect raw data (MCP) ─────────────────────────
    logger.info("Pipeline step 1: collect_week_data (user %s)", user_id)
    raw_data = await mcp_client.collect_week_data(user_id, days)
    if "error" in raw_data:
        result["error"] = f"Step 1 failed: {raw_data['error']}"
        return result
    raw_data_json = json.dumps(raw_data)
    pipeline_steps.append("collect_week_data")

    # ── Step 2: Analyze patterns (MCP) ─────────────────────────
    logger.info("Pipeline step 2: analyze_patterns (user %s)", user_id)
    analysis = await mcp_client.analyze_patterns(raw_data_json)
    if "error" in analysis:
        result["error"] = f"Step 2 failed: {analysis['error']}"
        return result
    pipeline_steps.append("analyze_patterns")

    # ── Step 2.5: Get previous reports (MCP) ───────────────────
    logger.info("Pipeline step 2.5: get_previous_reports (user %s)", user_id)
    previous = await mcp_client.get_previous_reports(user_id, limit=1)
    if "error" in previous:
        previous = None  # non-critical, continue without comparison
    else:
        pipeline_steps.append("get_previous_reports")

    # ── Step 3: AI insights (OpenAI) ───────────────────────────
    logger.info("Pipeline step 3: OpenAI insights (user %s)", user_id)
    user_prompt = _build_insights_prompt(analysis, previous)
    if vision:
        user_prompt += f"\n\nUser vision: {vision[:300]}"

    try:
        ai_insights = await openai_service.chat(
            system=_INSIGHTS_SYSTEM,
            user=user_prompt,
            max_tokens=400,
        )
    except Exception as exc:
        logger.error("Pipeline step 3 failed: %s", exc)
        ai_insights = None

    if ai_insights:
        analysis["ai_insights"] = ai_insights
        pipeline_steps.append("openai_insights")

    # ── Step 4: Save report (MCP) ──────────────────────────────
    logger.info("Pipeline step 4: save_weekly_report (user %s)", user_id)
    enriched_json = json.dumps(analysis)
    saved = await mcp_client.save_weekly_report(user_id, enriched_json)
    if "error" in saved:
        result["error"] = f"Step 4 failed: {saved['error']}"
        result["analysis"] = analysis  # return analysis even if save failed
        return result
    pipeline_steps.append("save_weekly_report")

    # ── Compose result ─────────────────────────────────────────
    result = saved  # includes snapshot_id, period_label, etc.
    result["success"] = True
    result["ai_insights"] = ai_insights
    result["previous_week"] = (
        previous["reports"][0] if previous and previous.get("reports") else None
    )
    result["pipeline"] = {
        "steps_completed": len(pipeline_steps),
        "steps": pipeline_steps,
    }

    logger.info(
        "Pipeline complete for user %s: %d steps, score %.0f%%",
        user_id,
        len(pipeline_steps),
        analysis.get("completion_score", 0) * 100,
    )
    return result
