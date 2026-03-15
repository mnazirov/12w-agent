"""aiohttp OAuth callback endpoints for Google account connection."""

from __future__ import annotations

import logging

from aiohttp import web

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()

SUCCESS_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Успешно</title></head>
<body style="font-family:sans-serif;text-align:center;padding:50px">
<h1>✅ Google-аккаунт подключён</h1>
<p>Закройте эту вкладку и вернитесь в Telegram.</p>
</body></html>"""

ERROR_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Ошибка</title></head>
<body style="font-family:sans-serif;text-align:center;padding:50px">
<h1>❌ {title}</h1>
<p>{message}</p>
</body></html>"""


@routes.get("/oauth/google/callback")
async def google_oauth_callback(request: web.Request) -> web.Response:
    bot = request.app["bot"]
    auth_service = request.app.get("google_auth_service")
    if auth_service is None:
        return web.Response(
            text=ERROR_HTML.format(
                title="OAuth не настроен",
                message="Google OAuth отключён на сервере.",
            ),
            content_type="text/html",
            status=503,
        )

    # User denied consent.
    if "error" in request.query:
        error = request.query["error"]
        logger.info("Google OAuth denied: %s", error)
        state = request.query.get("state", "")
        telegram_id = auth_service.validate_state(state) if state else None
        if telegram_id:
            try:
                await bot.send_message(telegram_id, "❌ Подключение Google отменено.")
            except Exception:
                logger.debug("Could not notify user about OAuth denial", exc_info=True)

        return web.Response(
            text=ERROR_HTML.format(
                title="Подключение отменено",
                message="Вы отказали в доступе. Вернитесь в Telegram.",
            ),
            content_type="text/html",
            status=200,
        )

    code = request.query.get("code")
    state = request.query.get("state")
    if not code or not state:
        return web.Response(
            text=ERROR_HTML.format(
                title="Неверный запрос",
                message="Отсутствуют обязательные параметры.",
            ),
            content_type="text/html",
            status=400,
        )

    telegram_id = auth_service.validate_state(state)
    if telegram_id is None:
        return web.Response(
            text=ERROR_HTML.format(
                title="Ссылка недействительна",
                message="Ссылка устарела или повреждена. Выполните /connect_google заново.",
            ),
            content_type="text/html",
            status=400,
        )

    try:
        token_data = await auth_service.exchange_code(code)
    except ValueError:
        logger.exception("Google OAuth token exchange failed for telegram_id=%d", telegram_id)
        try:
            await bot.send_message(
                telegram_id,
                "❌ Ошибка подключения Google. Попробуйте /connect_google снова.",
            )
        except Exception:
            logger.debug("Could not notify user about token exchange failure", exc_info=True)
        return web.Response(
            text=ERROR_HTML.format(
                title="Ошибка авторизации",
                message="Не удалось получить доступ. Попробуйте снова.",
            ),
            content_type="text/html",
            status=500,
        )

    email = await auth_service.get_user_email(token_data["access_token"])

    try:
        await auth_service.save_tokens(telegram_id, token_data, email)
    except ValueError:
        logger.exception("Google OAuth save_tokens failed for telegram_id=%d", telegram_id)
        try:
            await bot.send_message(
                telegram_id,
                "❌ Ошибка: пользователь не найден. Сначала выполните /start.",
            )
        except Exception:
            logger.debug("Could not notify missing user during OAuth callback", exc_info=True)
        return web.Response(
            text=ERROR_HTML.format(
                title="Пользователь не найден",
                message="Сначала запустите бота командой /start.",
            ),
            content_type="text/html",
            status=400,
        )

    email_text = f" ({email})" if email else ""
    try:
        await bot.send_message(
            telegram_id,
            f"✅ Google-аккаунт подключён{email_text}!\n\n"
            "Теперь я могу работать с вашим календарём.",
        )
    except Exception:
        logger.exception("Failed to send OAuth success message to telegram_id=%d", telegram_id)

    return web.Response(text=SUCCESS_HTML, content_type="text/html")


@routes.get("/oauth/google/health")
async def health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})
