"""Punto de entrada del bot: registra los handlers y escucha por polling.

Polling y no webhook a propósito: no necesita URL pública ni compartir
puerto con la API, así que en Railway es un proceso más del mismo repo
(ver `Procfile`). Si algún día hace falta webhook, solo cambia este archivo.
"""
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from app.bot import avisos, handlers
from app.nucleo.config import TELEGRAM_BOT_TOKEN
from app.nucleo.db import crear_tablas


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
    # Lo último: cualquier texto que no sea un comando se anota como apunte.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.anotar))

    avisos.programar(app)
    return app


def main() -> None:
    crear_tablas()
    construir_app().run_polling()


if __name__ == "__main__":
    main()
