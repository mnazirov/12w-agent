Generate a weekly review and scoring analysis.

## User's vision
{vision}

## User's "Why"
{why}

## 12-week goals
{goals}

## Week {week_number} of 12

## Weekly stats
- Planned tasks: {total_planned}
- Completed: {total_completed}
- Missed: {total_missed}
- Completion rate: {completion_pct}%

## Daily summaries this week
{daily_summaries}

## Instructions
Generate a weekly review following "12 Week Year" principles:

1. **score_pct** — the actual completion percentage of lead actions (integer).

2. **wins** — 2–3 specific things that went well (be concrete, reference actual tasks).

3. **improvements** — 2–3 areas to improve, with actionable suggestions.

4. **adjustments** — if score < 85%, suggest 1–2 plan adjustments for next week. If score >= 85%, congratulate and suggest maintaining the pace.

5. **vision_reminder** — a short, personalized reminder of why the user is doing this (tie to their vision/why).

6. **next_week_focus** — the single most important focus area for next week.

## Output format
Return ONLY valid JSON (no markdown, no explanation):
```
{{"score_pct": 75, "wins": ["..."], "improvements": ["..."], "adjustments": ["..."], "vision_reminder": "...", "next_week_focus": "..."}}
```
