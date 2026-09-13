"""Hábitos por Telegram: marcarlos con un toque y el recordatorio a su hora.

Aquí no se decide nada. Qué toca hoy, las rachas y a quién hay que recordar
lo dicen `servicios/habitos.py` y `dominio/habitos.py`; el bot enseña
botones y manda mensajes.

/habitos enseña los de hoy con un botón cada uno. Tocarlo marca o desmarca,
y el mensaje se rehace en el sitio con la racha nueva, sin llenar el chat de
confirmaciones.

Los recordatorios los comprueba un trabajo cada minuto, en vez de programar
uno por hábito. Así un hábito creado o cambiado desde la web entra solo, sin
que el bot tenga que enterarse, y un reinicio no pierde ni repite ninguno:
lo que ya se mandó hoy lo recuerda la base (`recordado_el`), no la memoria.

El botón del recordatorio solo marca, nunca desmarca. Si ya se había marcado
desde la web, tocarlo no puede deshacerlo.
"""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from app.bot import formato
from app.nucleo.db import sesion
from app.nucleo.tiempo import ahora_local
from app.servicios import habitos as servicio
from app.servicios.habitos import DiaNoMarcable, HabitoNoEncontrado

log = logging.getLogger(__name__)

DESDE_LISTA = "lista"
DESDE_AVISO = "aviso"


def _teclado(resumenes) -> InlineKeyboardMarkup | None:
    filas = [
        [
            InlineKeyboardButton(
                formato.boton_habito(resumen),
                callback_data=f"hab:{resumen.habito.id}:{DESDE_LISTA}",
            )
        ]
        for resumen in resumenes
        if resumen.toca_hoy
    ]
    return InlineKeyboardMarkup(filas) if filas else None


async def _editar(consulta, texto: str, teclado) -> None:
    try:
        await consulta.edit_message_text(texto, reply_markup=teclado)
    except BadRequest as exc:
        # Telegram se queja si el mensaje no ha cambiado: no es un fallo.
        if "not modified" not in str(exc).lower():
            raise


async def habitos(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    with sesion() as db:
        resumenes = servicio.listar(db, update.effective_user.id)
        texto = formato.lista_habitos(resumenes)
        teclado = _teclado(resumenes)
    await update.message.reply_text(texto, reply_markup=teclado)


async def tocar(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    consulta = update.callback_query
    _, habito_id, desde = consulta.data.split(":")
    user_id = consulta.from_user.id

    with sesion() as db:
        try:
            if desde == DESDE_AVISO:
                resumen = servicio.marcar(db, user_id, int(habito_id), hecho=True)
            else:
                resumen = servicio.alternar_hoy(db, user_id, int(habito_id))
        except HabitoNoEncontrado:
            await consulta.answer("Ese hábito ya no existe.", show_alert=True)
            return
        except DiaNoMarcable as exc:
            await consulta.answer(f"No se puede: {exc}.", show_alert=True)
            return

        if desde == DESDE_AVISO:
            texto, teclado = formato.habito_marcado(resumen), None
        else:
            resumenes = servicio.listar(db, user_id)
            texto, teclado = formato.lista_habitos(resumenes), _teclado(resumenes)
        hecho = resumen.hecho_hoy

    await consulta.answer("Hecho" if hecho else "Desmarcado")
    await _editar(consulta, texto, teclado)


async def recordar(contexto: ContextTypes.DEFAULT_TYPE) -> None:
    ahora = ahora_local()
    with sesion() as db:
        envios = []
        for habito in servicio.recordatorios_debidos(db, ahora):
            resumen = servicio.resumen(db, habito.user_id, habito.id)
            envios.append((habito.user_id, habito.id, formato.recordatorio_habito(resumen)))
            # Se apunta antes de mandar: si Telegram falla, mejor perder un
            # recordatorio que repetirlo cada minuto durante media hora.
            servicio.marcar_recordado(db, habito, ahora.date())

    for user_id, habito_id, texto in envios:
        boton = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Hecho ✓", callback_data=f"hab:{habito_id}:{DESDE_AVISO}")]]
        )
        try:
            await contexto.bot.send_message(chat_id=user_id, text=texto, reply_markup=boton)
        except TelegramError:
            log.warning("No se pudo mandar el recordatorio del hábito %s", habito_id, exc_info=True)


def registrar(app: Application) -> None:
    app.add_handler(CommandHandler("habitos", habitos))
    app.add_handler(CallbackQueryHandler(tocar, pattern=r"^hab:"))
    app.job_queue.run_repeating(recordar, interval=60, first=15, name="recordatorios_habitos")
