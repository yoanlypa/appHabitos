"""/banco y los pagos nuevos de la cuenta: se pregunta por cada uno.

- `/banco`: sin conexión, el botón para dar permiso en el banco. Con ella,
  lo que se ve de la cuenta y, además, lee ya lo nuevo y pregunta por ello.
  `/banco renovar` vuelve a pedir permiso.
- Cada 2 horas un trabajo lee lo nuevo de todas las cuentas conectadas y
  manda una pregunta por movimiento: 🏠 Casa, 💼 Negocio, ✓ Ya estaba
  apuntado, Ignorar (y, si entra dinero, los trabajos pendientes de ese
  importe). Nunca se decide por él.
- Tocar un botón apunta y cambia el mensaje por lo apuntado, con los botones
  de siempre (meterlo en un trabajo, pasarlo a efectivo, borrarlo).

Aquí no se decide nada: todo está en `servicios/banco.py`.
"""
import logging
from datetime import timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import BadRequest, TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from app.bot import acciones, formato
from app.bot import casa as casa_bot
from app.nucleo import banco as enable
from app.nucleo.db import sesion
from app.servicios import banco as servicio
from app.servicios.apuntes import ApunteNoEncontrado, MovimientoNoValido
from app.servicios.casa import DatoNoValido

log = logging.getLogger(__name__)

CADA = timedelta(hours=2)


def botones_de_pregunta(pregunta) -> InlineKeyboardMarkup:
    n = pregunta.movimiento.id
    filas = []
    if pregunta.movimiento.es_gasto:
        filas.append(
            [
                InlineKeyboardButton("🏠 Casa", callback_data=f"bk:casa:{n}"),
                InlineKeyboardButton("💼 Negocio", callback_data=f"bk:neg:{n}"),
            ]
        )
    else:
        for apunte in pregunta.cobros:
            filas.append(
                [InlineKeyboardButton(f"✅ Cobro: {apunte.concepto}"[:60], callback_data=f"bk:cob:{n}:{apunte.id}")]
            )
        filas.append([InlineKeyboardButton("💼 Cobro nuevo del negocio", callback_data=f"bk:neg:{n}")])
    ultima = []
    if pregunta.parecido:
        ultima.append(InlineKeyboardButton("✓ Ya estaba apuntado", callback_data=f"bk:ya:{n}"))
    ultima.append(InlineKeyboardButton("Ignorar", callback_data=f"bk:ign:{n}"))
    filas.append(ultima)
    return InlineKeyboardMarkup(filas)


async def preguntar(bot, db, user_id: int | None = None) -> int:
    """Manda una pregunta por cada movimiento nuevo. Devuelve cuántas salieron.

    Si Telegram falla con alguien, sus movimientos se quedan "nuevos" y se
    vuelven a intentar en la siguiente vuelta: no se pierde ninguno.
    """
    enviadas = 0
    for movimiento in servicio.por_preguntar(db, user_id):
        pregunta = servicio.pregunta_de(db, movimiento)
        try:
            await bot.send_message(
                chat_id=movimiento.user_id,
                text=formato.pregunta_banco(pregunta),
                reply_markup=botones_de_pregunta(pregunta),
            )
        except TelegramError:
            log.warning("No se pudo preguntar por un movimiento a %s", movimiento.user_id, exc_info=True)
            continue
        servicio.marcar_preguntado(db, movimiento)
        enviadas += 1
    return enviadas


async def revisar(contexto: ContextTypes.DEFAULT_TYPE) -> None:
    """Cada 2 horas: lee lo nuevo de cada cuenta conectada y pregunta."""
    with sesion() as db:
        for conexion in servicio.activas(db):
            try:
                await servicio.leer_nuevos(db, conexion)
            except (enable.BancoNoDisponible, enable.ErrorDeBanco):
                log.warning("No se pudo leer la cuenta de %s", conexion.user_id, exc_info=True)
        for conexion in servicio.avisar_de_caducidad(db):
            try:
                await contexto.bot.send_message(chat_id=conexion.user_id, text=formato.caducidad_banco(conexion))
            except TelegramError:
                log.warning("No se pudo avisar de la caducidad a %s", conexion.user_id, exc_info=True)
        await preguntar(contexto.bot, db)


async def banco(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    reconectar = (contexto.args or [""])[0].lower() in ("conectar", "renovar", "otra")
    await update.message.chat.send_action(ChatAction.TYPING)
    with sesion() as db:
        try:
            conexion = None if reconectar else servicio.activa(db, user_id)
            if conexion is not None and not servicio.caducada(conexion):
                await servicio.leer_nuevos(db, conexion)
                resumen = await servicio.ver(db, user_id)
                await update.message.reply_text(
                    formato.resumen_banco(resumen) + "\n\nPara volver a dar permiso: /banco renovar"
                )
                await preguntar(contexto.bot, db, user_id)
                return
            url = await servicio.iniciar(db, user_id)
        except enable.BancoNoDisponible as exc:
            await update.message.reply_text(f"La conexión con el banco no está configurada: {exc}.")
            return
        except enable.ErrorDeBanco as exc:
            await update.message.reply_text(f"El banco no ha contestado bien: {exc}")
            return
    await update.message.reply_text(
        "Toca el botón, confirma en la app de tu banco y vuelve aquí. "
        "El enlace vale una hora y solo sirve para ti.\n\n"
        "Solo se leen los movimientos: la app no puede mover dinero.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏦 Conectar con el banco", url=url)]]),
    )


async def _repintar(consulta, texto: str, botones=None) -> None:
    try:
        await consulta.edit_message_text(texto, reply_markup=botones)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise


_ACCIONES = {"casa": "casa", "neg": "negocio", "cob": "cobro", "ya": "ya_estaba", "ign": "ignorado"}


async def tocar(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    consulta = update.callback_query
    await consulta.answer()
    partes = consulta.data.split(":")
    accion, movimiento_id = _ACCIONES.get(partes[1]), int(partes[2])
    cobro_id = int(partes[3]) if len(partes) > 3 else None
    with sesion() as db:
        try:
            d = servicio.decidir(db, consulta.from_user.id, movimiento_id, accion, cobro_id)
        except servicio.MovimientoNoEncontrado:
            await _repintar(consulta, "Ese movimiento ya no está.")
            return
        except (ValueError, DatoNoValido, MovimientoNoValido, ApunteNoEncontrado) as exc:
            await consulta.message.reply_text(f"No he podido apuntarlo: {exc}")
            return
        m = d.movimiento
        if d.gasto is not None:
            await _repintar(consulta, formato.gasto_casa(d.gasto), casa_bot.botones_gasto(d.gasto))
        elif d.apunte is not None:
            texto = formato.apunte_cobrado(d.apunte) if m.estado == "cobro" else acciones.texto_de(d.apunte)
            await _repintar(consulta, texto, acciones.botones_de(d.apunte))
        else:
            await _repintar(consulta, formato.movimiento_apartado(m, m.estado == "ya_estaba"))


def registrar(app: Application) -> None:
    app.add_handler(CommandHandler("banco", banco))
    app.add_handler(CallbackQueryHandler(tocar, pattern=r"^bk:"))


def programar(app: Application) -> None:
    app.job_queue.run_repeating(revisar, interval=CADA, first=timedelta(minutes=2), name="banco")
