"""Restaurar una copia: se le reenvía al bot el CSV y vuelve lo que falte.

Es el camino de vuelta de `bot/copias.py`. Como en todo el bot, aquí no se
decide nada: se baja el fichero, se lee con `dominio/copia_csv.py`, se
planifica con `servicios/restauracion.py` y se pinta.

Siempre en dos pasos: primero se enseña qué entraría y luego se confirma con
un botón. Reenviar una copia vieja por despiste devolvería lo que se borró a
propósito después de hacerla, y eso tiene que verse antes de que pase.

Las filas leídas esperan en `user_data` entre un paso y otro. Si el proceso
se reinicia en medio se pierden, y se pide que se reenvíe el fichero: es
preferible a guardar en la base algo que aún no se ha confirmado.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import Application, CallbackQueryHandler, ContextTypes, MessageHandler, filters

from app.bot import formato
from app.dominio.copia_csv import CopiaNoValida, decodificar, leer_copia
from app.nucleo.db import sesion
from app.servicios.restauracion import planificar, restaurar

# Años de apuntes en CSV no llegan ni a un mega. El límite es para no bajar
# por error un fichero enorme que no es una copia.
TAMANO_MAXIMO = 5 * 1024 * 1024
_PENDIENTE = "restauracion_pendiente"


async def recibir_copia(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
    documento = update.message.document
    if documento.file_size and documento.file_size > TAMANO_MAXIMO:
        await update.message.reply_text("Ese fichero es demasiado grande para ser una de mis copias.")
        return

    try:
        fichero = await contexto.bot.get_file(documento.file_id)
        datos = bytes(await fichero.download_as_bytearray())
    except TelegramError as exc:
        await update.message.reply_text(f"No he podido descargar el fichero: {exc}")
        return

    try:
        filas = leer_copia(decodificar(datos))
    except CopiaNoValida as exc:
        await update.message.reply_text(formato.copia_no_valida(exc))
        return

    with sesion() as db:
        plan = planificar(db, update.effective_user.id, filas)

    if not plan.nuevas:
        await update.message.reply_text(formato.copia_ya_estaba(plan))
        return

    contexto.user_data[_PENDIENTE] = filas
    botones = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(f"Restaurar {len(plan.nuevas)}", callback_data="rest:si"),
                InlineKeyboardButton("Cancelar", callback_data="rest:no"),
            ]
        ]
    )
    await update.message.reply_text(formato.plan_de_restauracion(plan), reply_markup=botones)


async def confirmar(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
    consulta = update.callback_query
    await consulta.answer()
    # Se saca siempre, se confirme o no: un segundo toque no puede restaurar dos veces.
    filas = contexto.user_data.pop(_PENDIENTE, None)

    if consulta.data == "rest:no":
        await consulta.edit_message_text("Cancelado. No he tocado nada.")
        return
    if filas is None:
        await consulta.edit_message_text(
            "Ya no tengo esa copia a mano (puede que me haya reiniciado). "
            "Reenvíamela y la vuelvo a mirar."
        )
        return

    with sesion() as db:
        cuantos = restaurar(db, consulta.from_user.id, filas)
    await consulta.edit_message_text(formato.copia_restaurada(cuantos))


def registrar(app: Application) -> None:
    app.add_handler(MessageHandler(filters.Document.FileExtension("csv"), recibir_copia))
    app.add_handler(CallbackQueryHandler(confirmar, pattern=r"^rest:"))
