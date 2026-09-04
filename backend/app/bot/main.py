"""Punto de entrada del bot: registra los handlers y escucha por polling.

Polling y no webhook a propósito: no necesita URL pública ni compartir
puerto con la API. Si algún día hace falta webhook, solo cambia este archivo.

Se puede arrancar de dos formas: `main()` para tenerlo solo a él (en local),
o `en_marcha()` para levantarlo dentro del event loop de otro proceso, que
es como corre en Railway junto a la API (ver `app/api_y_bot.py`).
"""
import logging
from contextlib import asynccontextmanager

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.bot import avisos, handlers
from app.nucleo.config import TELEGRAM_BOT_TOKEN
from app.nucleo.migraciones import migrar


def construir_app() -> Application:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Falta TELEGRAM_BOT_TOKEN en el entorno")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", handlers.start))
    app.add_handler(CommandHandler("hoy", handlers.hoy))
    app.add_handler(CommandHandler("mes", handlers.mes))
    app.add_handler(CommandHandler("cobrado", handlers.cobrado))
    app.add_handler(CommandHandler("web", handlers.web))
    app.add_handler(CommandHandler("avisos", handlers.avisos))
    app.add_handler(CommandHandler("agenda", handlers.agenda))
    app.add_handler(CommandHandler("manana", handlers.manana))
    app.add_handler(CommandHandler("cita", handlers.cita))
    app.add_handler(CommandHandler("deben", handlers.deben))
    app.add_handler(CommandHandler("cliente", handlers.cliente))
    app.add_handler(CallbackQueryHandler(handlers.elegir_cliente, pattern=r"^cli:"))
    # Lo último: cualquier texto que no sea un comando se anota como apunte.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.anotar))

    avisos.programar(app)
    return app


@asynccontextmanager
async def en_marcha():
    """Escucha Telegram mientras dure el bloque, sin adueñarse del event loop.

    `run_polling()` monta su propio bucle y bloquea, que es justo lo que no
    se puede hacer dentro de uvicorn: aquí se arranca y se para a mano.
    """
    app = construir_app()
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    try:
        yield app
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


def main() -> None:
    # Sin esto el bot arranca mudo y no hay forma de saber si está vivo ni por
    # qué dejó de estarlo. Bajo httpx a WARNING: si no, escribe una línea por
    # cada consulta del polling, cada pocos segundos.
    logging.basicConfig(
        format="%(asctime)s %(name)s %(levelname)s: %(message)s", level=logging.INFO
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    migrar()
    construir_app().run_polling()


if __name__ == "__main__":
    main()
