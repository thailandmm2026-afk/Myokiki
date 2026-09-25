#!/usr/bin/env python3
"""
Ki Ki Shop – Combined Web + Telegram Bot for Render
Uses WEBHOOK so /start, /admin, buttons work on one service.
Start:  python app.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
from typing import Optional

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("kiki-app")

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_loop: Optional[asyncio.AbstractEventLoop] = None
_tg_app = None


def _loop_thread():
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    _loop.run_forever()


def _run(coro):
    assert _loop is not None
    fut = asyncio.run_coroutine_threadsafe(coro, _loop)
    return fut.result(timeout=120)


def _public_base_url() -> str:
    url = (
        os.getenv("WEBHOOK_URL")
        or os.getenv("RENDER_EXTERNAL_URL")
        or os.getenv("PUBLIC_URL")
        or ""
    ).strip().rstrip("/")
    if not url:
        host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
        if host:
            url = f"https://{host}"
    return url


def setup_telegram():
    global _tg_app
    import bot as bot_module

    _tg_app = bot_module.build_application()

    async def _start():
        await _tg_app.initialize()
        await _tg_app.start()
        base = _public_base_url()
        if base:
            hook = f"{base}/telegram-webhook"
            await _tg_app.bot.set_webhook(
                url=hook,
                allowed_updates=["message", "callback_query"],
                drop_pending_updates=True,
            )
            log.info("Webhook set → %s", hook)
        else:
            log.warning("No WEBHOOK_URL – polling fallback")
            await _tg_app.updater.start_polling(drop_pending_updates=True)
        me = await _tg_app.bot.get_me()
        log.info("Bot online as @%s id=%s", me.username, me.id)

    _run(_start())


def main():
    t = threading.Thread(target=_loop_thread, name="ptb-loop", daemon=True)
    t.start()
    for _ in range(50):
        if _loop is not None and _loop.is_running():
            break
        time.sleep(0.05)

    try:
        setup_telegram()
    except Exception:
        log.exception("Telegram setup failed – web will still start")

    import web_app

    if not web_app.BOT_TOKEN:
        web_app.BOT_TOKEN = os.getenv("BOT_TOKEN", "")

    @web_app.app.route("/telegram-webhook", methods=["POST"])
    def telegram_webhook():
        from flask import request, jsonify
        from telegram import Update

        if _tg_app is None or _loop is None:
            return jsonify({"ok": False, "error": "bot not ready"}), 503
        try:
            data = request.get_json(force=True, silent=True) or {}
            update = Update.de_json(data, _tg_app.bot)
            if update:
                asyncio.run_coroutine_threadsafe(
                    _tg_app.process_update(update), _loop
                )
            return jsonify({"ok": True})
        except Exception as e:
            log.exception("webhook")
            return jsonify({"ok": False, "error": str(e)}), 500

    @web_app.app.route("/health")
    def health():
        from flask import jsonify
        return jsonify({"ok": True, "bot": _tg_app is not None, "webhook": _public_base_url() or None})

    log.info("Web on %s:%s DB=%s", web_app.HOST, web_app.PORT, web_app.DB_PATH)
    web_app.init_web_db()
    web_app.app.run(
        host=web_app.HOST,
        port=web_app.PORT,
        debug=False,
        threaded=True,
        use_reloader=False,
    )


if __name__ == "__main__":
    main()
