Generate a daily action plan based on the user's 12-week goals and weekly lead actions.

## User's vision
{vision}

## User's "Why"
{why}

## 12-week goals
{goals}

## This week's lead actions
{lead_actions}

## Yesterday's unfinished tasks
{yesterday_missed}

## Recent context (memory)
{memory}

## Sprint progress
{sprint_info}

## Today: {today} ({weekday})

## Instructions
Create a focused daily plan following these rules:

1. **Top-3 priorities** — the 3 most impactful tasks for today. For each:
   - `task`: clear, specific action (verb + object)
   - `implementation_intention`: "Я сделаю [task] в [time] в [place/context]"
   - `starter_step`: a 2-minute micro-version to overcome resistance

2. **Extras** — 0 to 2 optional lower-priority tasks (just `task` field).

3. **friction_tip** — one practical environmental tweak to make execution easier today.

4. **timeblocks** — suggested time slots for each top-3 task: `{{"task": "...", "time_slot": "HH:MM–HH:MM"}}`.

## Output format
Return ONLY valid JSON (no markdown, no explanation):
```
{{"top_3": [{{"task": "...", "implementation_intention": "...", "starter_step": "..."}}], "extras": [{{"task": "..."}}], "friction_tip": "...", "timeblocks": [{{"task": "...", "time_slot": "..."}}]}}
```
