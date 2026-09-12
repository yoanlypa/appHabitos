"""Que el bot lo diga en voz alta si los datos no se están guardando.

Pasó dos veces: la base se creaba dentro del contenedor y cada despliegue la
borraba. `/salud` lo decía y el log lo escribía, pero nadie mira un log. El
único sitio que se mira seguro es el chat.

Dos avisos, porque cada uno tapa el hueco del otro:

- Al arrancar, a los ids de `ALARMA_TELEGRAM_IDS`. No se pueden sacar de la
  base: justo cuando falla, la base está recién creada y no sabe quién la
  usa. Llega aunque no se escriba nada.
- En el primer mensaje de cada persona desde que arrancó el proceso. No
  necesita configurar nada, así que funciona aunque también se haya perdido
  esa variable.

Una sola vez por persona por arranque: un aviso pegado a cada respuesta se
deja de leer al tercer mensaje, y entonces ya no avisa de nada.
"""
import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import Application, ContextTypes, TypeHandler

from app.bot import formato
from app.nucleo.almacenamiento import estado
from app.nucleo.config import ALARMA_TELEGRAM_IDS

log = logging.getLogger(__name__)

_YA_AVISADOS = "alarma_almacenamiento_avisados"


def texto_de_alarma() -> str | None:
    """El aviso si la base no es persistente; None si todo está bien."""
    actual = estado()
    if actual.persistente:
        return None
    return formato.alarma_almacenamiento(actual.aviso or "")


async def avisar_al_arrancar(contexto: ContextTypes.DEFAULT_TYPE) -> None:
    texto = texto_de_alarma()
    if texto is None:
        return
    for chat_id in ALARMA_TELEGRAM_IDS:
        try:
            await contexto.bot.send_message(chat_id=chat_id, text=texto)
        except TelegramError:
            log.warning("No se pudo mandar la alarma de almacenamiento a %s", chat_id, exc_info=True)


async def avisar_en_el_primer_mensaje(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
    usuario = update.effective_user
    chat = update.effective_chat
    if usuario is None or chat is None:
        return

    avisados = contexto.bot_data.setdefault(_YA_AVISADOS, set())
    if usuario.id in avisados:
        return
    texto = texto_de_alarma()
    if texto is None:
        return

    avisados.add(usuario.id)
    try:
        await contexto.bot.send_message(chat_id=chat.id, text=texto)
    except TelegramError:
        log.warning("No se pudo mandar la alarma de almacenamiento a %s", usuario.id, exc_info=True)


def programar(app: Application) -> None:
    # Grupo -1: corre antes que los handlers normales y no les quita el
    # mensaje, así que el aviso llega y el apunte se anota igual.
    app.add_handler(TypeHandler(Update, avisar_en_el_primer_mensaje), group=-1)
    # Unos segundos de margen para que el bot esté conectado del todo.
    app.job_queue.run_once(avisar_al_arrancar, when=5, name="alarma_almacenamiento")
