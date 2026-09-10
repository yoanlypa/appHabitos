"""El aviso diario: a la hora fijada, manda el resumen y lo que toca mañana.

Aquí no se decide a quién se avisa ni qué se le cuenta — eso lo resuelve
`servicios/avisos.py`. Este archivo solo engancha el job al reloj de PTB,
arma el mensaje con las piezas ya calculadas y lo manda.
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
        # El mensaje se arma dentro de la sesión: las citas traen su cliente
        # por relación y fuera de aquí ya no se podría leer.
        mensajes = [
            (
                aviso.user_id,
                _componer(aviso),
            )
            for aviso in destinatarios
        ]

    for user_id, texto in mensajes:
        try:
            await contexto.bot.send_message(chat_id=user_id, text=texto)
        except TelegramError:
            # Si uno bloqueó el bot, el resto tiene que recibir su aviso igual.
            log.warning("No se pudo avisar a %s", user_id, exc_info=True)


def _componer(aviso) -> str:
    partes = []
    if aviso.hubo_apuntes:
        partes.append(formato.resumen("Resumen de hoy:", aviso.resumen))
    if aviso.citas_manana:
        partes.append(formato.lista_citas("Mañana:", aviso.citas_manana))
    if aviso.notas_pendientes:
        partes.append(formato.recordatorio_de_notas(aviso.notas_pendientes))
    return "\n\n".join(partes)


def programar(app: Application) -> None:
    app.job_queue.run_daily(enviar_aviso_diario, time=hora_del_aviso(), name="aviso_diario")
