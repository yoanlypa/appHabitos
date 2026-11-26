"""Restaurar una copia: se le reenvía al bot el ZIP (o el CSV) y vuelve lo que falte.

El ZIP es la copia completa (`servicios/copia_completa.py`): apuntes con sus
trabajos y clientes, citas, hábitos y Casa. El CSV es la copia antigua, solo
de apuntes, y se sigue aceptando: las copias viejas también tienen que valer.

Un CSV que no es una copia del bot (no trae su cabecera) no se rechaza: se
pasa a `bot/importar.py`, que lo lee como una lista de movimientos.

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

from app.bot import formato, importar
from app.dominio import copia_completa
from app.dominio.copia_csv import CopiaNoValida, decodificar, es_copia, leer_copia
from app.nucleo.db import sesion
from app.servicios import copia_completa as servicio_copia
from app.servicios.restauracion import planificar, restaurar

# Años de apuntes en CSV no llegan ni a un mega. El límite es para no bajar
# por error un fichero enorme que no es una copia.
TAMANO_MAXIMO = 5 * 1024 * 1024
# La copia completa comprimida tampoco llega a eso, pero se le da margen.
TAMANO_MAXIMO_ZIP = 20 * 1024 * 1024
_PENDIENTE = "restauracion_pendiente"
_PENDIENTE_COMPLETA = "restauracion_completa_pendiente"


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
        texto = decodificar(datos)
    except CopiaNoValida as exc:
        await update.message.reply_text(formato.copia_no_valida(exc))
        return
    if not es_copia(texto):
        # No es una de las copias del bot. Puede ser una lista de movimientos
        # hecha a mano o sacada de otra app: eso es importar, no restaurar.
        await importar.proponer_csv(update.message, contexto, update.effective_user.id, datos)
        return
    try:
        filas = leer_copia(texto)
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


async def recibir_copia_completa(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
    documento = update.message.document
    if documento.file_size and documento.file_size > TAMANO_MAXIMO_ZIP:
        await update.message.reply_text("Ese fichero es demasiado grande para ser una de mis copias.")
        return
    try:
        fichero = await contexto.bot.get_file(documento.file_id)
        datos = bytes(await fichero.download_as_bytearray())
    except TelegramError as exc:
        await update.message.reply_text(f"No he podido descargar el fichero: {exc}")
        return

    try:
        copia = copia_completa.leer(datos)
    except CopiaNoValida as exc:
        await update.message.reply_text(formato.copia_completa_no_valida(exc))
        return

    user_id = update.effective_user.id
    with sesion() as db:
        plan = servicio_copia.planificar(db, user_id, copia)

    de_otro = copia.user_id is not None and copia.user_id != user_id
    if not plan.hay_algo:
        await update.message.reply_text(formato.copia_completa_ya_estaba(plan))
        return

    contexto.user_data[_PENDIENTE_COMPLETA] = copia
    botones = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Restaurar", callback_data="restc:si"),
                InlineKeyboardButton("Cancelar", callback_data="restc:no"),
            ]
        ]
    )
    await update.message.reply_text(
        formato.plan_de_restauracion_completa(plan, copia.creada, de_otro), reply_markup=botones
    )


async def confirmar_completa(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
    consulta = update.callback_query
    await consulta.answer()
    # Se saca siempre: un segundo toque no puede restaurar dos veces.
    copia = contexto.user_data.pop(_PENDIENTE_COMPLETA, None)

    if consulta.data == "restc:no":
        await consulta.edit_message_text("Cancelado. No he tocado nada.")
        return
    if copia is None:
        await consulta.edit_message_text(
            "Ya no tengo esa copia a mano (puede que me haya reiniciado). "
            "Reenvíamela y la vuelvo a mirar."
        )
        return

    with sesion() as db:
        plan = servicio_copia.restaurar(db, consulta.from_user.id, copia)
    await consulta.edit_message_text(formato.copia_completa_restaurada(plan))


def registrar(app: Application) -> None:
    app.add_handler(MessageHandler(filters.Document.FileExtension("csv"), recibir_copia))
    app.add_handler(MessageHandler(filters.Document.FileExtension("zip"), recibir_copia_completa))
    app.add_handler(CallbackQueryHandler(confirmar, pattern=r"^rest:"))
    app.add_handler(CallbackQueryHandler(confirmar_completa, pattern=r"^restc:"))
