Analyze the user's evening check-in and provide structured feedback.

## User's vision
{vision}

## 12-week goals
{goals}

## Today's plan
{todays_plan}

## Completed tasks
{completed}

## Missed tasks
{missed}

## User's obstacle description
{obstacles_text}

## Instructions
Provide a supportive evening analysis:

1. **summary** — 1–2 sentence warm acknowledgment of what was done. Be genuine, not generic.

2. **controllable_factors** — list factors within user's control that led to missed tasks (e.g. "не выделил конкретное время", "отвлёкся на соцсети").

3. **uncontrollable_factors** — list factors outside user's control (e.g. "внеплановая встреча от начальника").

4. **woop** — for each missed task, generate a WOOP micro-plan:
   - `wish`: what the user wanted to achieve
   - `outcome`: best possible outcome if done
   - `obstacle`: the main internal obstacle
   - `plan`: "Если [obstacle], то я [specific action]" (implementation intention)

5. **lesson_prompt** — one reflection question to help the user extract a lesson (e.g. "Что ты узнал о себе сегодня?").

6. **tomorrow_suggestion** — one concrete adjustment for tomorrow.

## Output format
Return ONLY valid JSON (no markdown, no explanation):
```
{{"summary": "...", "controllable_factors": ["..."], "uncontrollable_factors": ["..."], "woop": [{{"wish": "...", "outcome": "...", "obstacle": "...", "plan": "..."}}], "lesson_prompt": "...", "tomorrow_suggestion": "..."}}
```
