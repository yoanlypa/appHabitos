"""El aviso diario: a la hora fijada, manda a cada uno su resumen del día.

Aquí no se decide a quién se avisa ni qué se le cuenta — eso lo resuelve
`servicios/avisos.py`. Este archivo solo engancha el job al reloj de PTB y
manda los mensajes.
"""
import logging

from telegram.error import TelegramError
from telegram.ext import Application, ContextTypes

from app.bot import formato
from app.nucleo.db import sesion
from app.nucleo.tiempo import hora_del_aviso
from app.servicios.avisos import destinatarios_del_aviso

log = logging.getLogger(__name__)


async def enviar_aviso_diario(contexto: ContextTypes.DEFAULT_TYPE) -> None:
    with sesion() as db:
        destinatarios = destinatarios_del_aviso(db)

    for user_id, resumen in destinatarios:
        try:
            await contexto.bot.send_message(
                chat_id=user_id, text=formato.resumen("Resumen de hoy:", resumen)
            )
        except TelegramError:
            # Si uno bloqueó el bot, el resto tiene que recibir su aviso igual.
            log.warning("No se pudo avisar a %s", user_id, exc_info=True)


def programar(app: Application) -> None:
    app.job_queue.run_daily(enviar_aviso_diario, time=hora_del_aviso(), name="aviso_diario")
