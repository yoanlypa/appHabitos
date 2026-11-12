"""El recordatorio de una cita el mismo día, por Telegram y por correo.

El aviso de las 21:00 ya contaba las citas de mañana, pero el día de la cita
nada: una cita a las 14:00 se olvidaba igual. Esto lo comprueba cada minuto,
como los hábitos, para que una cita creada o movida desde la web entre sola.

Cuándo toca lo decide `dominio/recordatorios.py`, a quién `servicios/avisos`.
Aquí solo se escribe el mensaje y se manda. Se apunta como avisada antes de
mandar: si algo falla, mejor perder un recordatorio que repetirlo cada minuto.

/correo dice a qué dirección se mandan también por correo, o la cambia.
"""
import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes

from app.bot import formato
from app.nucleo.db import sesion
from app.nucleo.tiempo import ahora_local
from app.servicios.avisos import (
    CorreoNoValido,
    citas_por_recordar,
    correo_de,
    correo_disponible,
    guardar_correo,
    mandar_correo,
    marcar_avisada,
)

log = logging.getLogger(__name__)


async def recordar(contexto: ContextTypes.DEFAULT_TYPE) -> None:
    ahora = ahora_local()
    with sesion() as db:
        envios = []
        for cita in citas_por_recordar(db, ahora):
            texto = formato.recordatorio_cita(cita)
            asunto = formato.asunto_recordatorio_cita(cita)
            envios.append((cita.user_id, texto, asunto))
            marcar_avisada(db, cita)

        for user_id, texto, asunto in envios:
            try:
                await contexto.bot.send_message(chat_id=user_id, text=texto)
            except TelegramError:
                log.warning("No se pudo recordar la cita por Telegram a %s", user_id, exc_info=True)
            # Por correo aparte: si Telegram falla, que llegue por el otro lado.
            await mandar_correo(db, user_id, asunto, texto)


async def correo(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
    """/correo, /correo nombre@ejemplo.com o /correo off."""
    user_id = update.effective_user.id
    argumento = " ".join(contexto.args).strip()
    with sesion() as db:
        if not argumento:
            actual = correo_de(db, user_id)
            texto = formato.estado_correo(actual, correo_disponible())
        else:
            quitar = argumento.lower() in ("off", "no", "quitar", "ninguno")
            try:
                nuevo = guardar_correo(db, user_id, None if quitar else argumento)
            except CorreoNoValido as exc:
                await update.message.reply_text(f"{exc}. Ejemplo: /correo nombre@gmail.com")
                return
            texto = formato.estado_correo(nuevo, correo_disponible())
    await update.message.reply_text(texto)


def registrar(app: Application) -> None:
    app.add_handler(CommandHandler("correo", correo))
    app.job_queue.run_repeating(recordar, interval=60, first=20, name="recordatorios_citas")
