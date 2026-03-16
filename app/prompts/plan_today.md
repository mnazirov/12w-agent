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

## Контекст сегодняшнего дня
Ниже может быть предоставлена информация о календаре и погоде.
Используй её при составлении плана:

{day_context}

### Если есть данные календаря
- Не ставь задачи на занятые слоты.
- После встреч длиннее 1 часа ставь 15-минутный перерыв.
- Если день плотно занят встречами (>5 часов), сократи дополнительные задачи до 1-2.
- Если встреч нет, распределяй время свободно.

### Если есть данные погоды
- Если тренировка рекомендована outdoor (✅), ставь на улице и используй погоду как мотивацию.
- Если тренировка НЕ рекомендована outdoor (⛔), замени на indoor-альтернативу и кратко объясни причину.
- Лучшее время для outdoor: утром летом (до жары), днём зимой (теплее).

### Если данных нет
- Если контекст дня не предоставлен, планируй как обычно.
- Не упоминай погоду и календарь, если их данных нет.

### Комбинация: встречи + тренировка
1. Определи свободные слоты по календарю.
2. Выбери слот для тренировки с учётом погоды (outdoor/indoor).
3. Если слотов мало, предложи сокращённую тренировку (20 минут) или перенос на завтра.

## Ошибки инструментов
- Если в контексте есть инструкция для пользователя (например, /connect_google), сообщи её коротко и по делу.
- Не придумывай технические ошибки серверов.

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
