"""Importar varios movimientos de golpe: se enseñan, y entran al confirmar.

Cuatro puertas y un solo pasillo. Los movimientos pueden venir de un mensaje
con un apunte por línea, de un CSV o un Excel, o de una captura con varios
pagos (el historial de la app del parking); todos acaban en `proponer()`,
que enseña lo leído con sus botones, y en `confirmar()`, que los guarda.

Siempre en dos pasos. Con un apunte suelto el bot anota y enseña lo que ha
entendido, porque corregir uno es un toque; con once leídos de una foto, un
importe mal leído se pierde entre los demás. Aquí se mira antes.

Lo leído espera en `user_data` entre un paso y otro, cada lista con su
número: mandar dos capturas seguidas son dos listas, y confirmar una no
puede llevarse la otra. Si el proceso se reinicia en medio se pierden y se
pide que se manden otra vez, como al restaurar una copia.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import Application, CallbackQueryHandler, ContextTypes, MessageHandler, filters

from app.bot import formato
from app.dominio.copia_csv import CopiaNoValida, decodificar
from app.dominio.importacion import (
    ImportacionNoValida,
    Movimiento,
    filas_de_csv,
    leer_tabla,
)
from app.nucleo.db import sesion
from app.nucleo.hojas import HojaNoLegible, filas_de_xlsx
from app.nucleo.lectura_tickets import ErrorDeLectura, LecturaNoDisponible
from app.nucleo.tiempo import hoy_local
from app.servicios.importacion import (
    borrar_importados,
    con_tipo,
    falta_el_tipo,
    importar,
    leer_captura,
    planificar,
)

TAMANO_MAXIMO = 5 * 1024 * 1024
_PENDIENTES = "importaciones_pendientes"
_HECHAS = "importaciones_hechas"
_CONTADOR = "importaciones_contador"
# No se guardan listas sin confirmar para siempre: con las últimas basta.
_GUARDADAS = 6


def _guardar(contexto: ContextTypes.DEFAULT_TYPE, cajon: str, valor) -> int:
    numero = contexto.user_data.get(_CONTADOR, 0) + 1
    contexto.user_data[_CONTADOR] = numero
    guardadas = contexto.user_data.setdefault(cajon, {})
    guardadas[numero] = valor
    for viejo in sorted(guardadas)[:-_GUARDADAS]:
        del guardadas[viejo]
    return numero


async def proponer(
    mensaje: Message, contexto: ContextTypes.DEFAULT_TYPE, user_id: int, movimientos: list[Movimiento]
) -> None:
    """Enseña lo leído y pregunta. No escribe nada en la base."""
    if falta_el_tipo(movimientos):
        numero = _guardar(contexto, _PENDIENTES, movimientos)
        botones = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Son gastos", callback_data=f"imp:gasto:{numero}"),
                    InlineKeyboardButton("Son cobros", callback_data=f"imp:trabajo:{numero}"),
                ],
                [InlineKeyboardButton("Cancelar", callback_data=f"imp:no:{numero}")],
            ]
        )
        await mensaje.reply_text(
            formato.preguntar_tipo_de_importacion(movimientos), reply_markup=botones
        )
        return

    with sesion() as db:
        plan = planificar(db, user_id, movimientos)
    numero = _guardar(contexto, _PENDIENTES, movimientos)
    await mensaje.reply_text(
        formato.plan_de_importacion(plan), reply_markup=_botones_del_plan(plan, numero)
    )


def _botones_del_plan(plan, numero: int) -> InlineKeyboardMarkup:
    filas = []
    if plan.nuevos:
        filas.append(
            [InlineKeyboardButton(f"✅ Añadir {len(plan.nuevos)}", callback_data=f"imp:si:{numero}")]
        )
    if plan.repetidos:
        # Lo apartado por parecer repetido no se tira: se puede meter igual.
        filas.append(
            [
                InlineKeyboardButton(
                    f"Añadir los {plan.total}, repetidos también", callback_data=f"imp:todo:{numero}"
                )
            ]
        )
    filas.append([InlineKeyboardButton("Cancelar", callback_data=f"imp:no:{numero}")])
    return InlineKeyboardMarkup(filas)


async def confirmar(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
    consulta = update.callback_query
    await consulta.answer()
    _, accion, numero = consulta.data.split(":")
    numero = int(numero)
    user_id = consulta.from_user.id

    if accion == "deshacer":
        # Se saca siempre: un segundo toque no puede borrar otra cosa.
        ids = contexto.user_data.get(_HECHAS, {}).pop(numero, None)
        if ids is None:
            await consulta.edit_message_text(formato.importacion_caducada_para_deshacer())
            return
        with sesion() as db:
            cuantos = borrar_importados(db, user_id, ids)
        await consulta.edit_message_text(formato.importacion_deshecha(cuantos))
        return

    # Se saca siempre, se confirme o no: un segundo toque no importa dos veces.
    movimientos = contexto.user_data.get(_PENDIENTES, {}).pop(numero, None)
    if accion == "no":
        await consulta.edit_message_text("Cancelado. No he añadido nada.")
        return
    if movimientos is None:
        await consulta.edit_message_text(formato.importacion_caducada())
        return

    if accion in ("gasto", "trabajo"):
        # Ya se sabe qué son: ahora sí se puede mirar cuáles faltan y enseñarlo.
        movimientos = con_tipo(movimientos, accion)
        with sesion() as db:
            plan = planificar(db, user_id, movimientos)
        numero = _guardar(contexto, _PENDIENTES, movimientos)
        await consulta.edit_message_text(
            formato.plan_de_importacion(plan), reply_markup=_botones_del_plan(plan, numero)
        )
        return

    with sesion() as db:
        apuntes = importar(db, user_id, movimientos, origen="bot", todo=accion == "todo")
        ya_estaban = len(movimientos) - len(apuntes)
        botones = None
        if apuntes:
            hecha = _guardar(contexto, _HECHAS, [a.id for a in apuntes])
            botones = InlineKeyboardMarkup(
                [[InlineKeyboardButton("↩️ Deshacer", callback_data=f"imp:deshacer:{hecha}")]]
            )
        await consulta.edit_message_text(
            formato.importacion_hecha(apuntes, ya_estaban), reply_markup=botones
        )


async def _descargar(mensaje: Message, contexto: ContextTypes.DEFAULT_TYPE) -> bytes | None:
    documento = mensaje.document
    if documento.file_size and documento.file_size > TAMANO_MAXIMO:
        await mensaje.reply_text("Ese fichero es demasiado grande para ser una lista de movimientos.")
        return None
    try:
        fichero = await contexto.bot.get_file(documento.file_id)
        return bytes(await fichero.download_as_bytearray())
    except TelegramError as exc:
        await mensaje.reply_text(f"No he podido descargar el fichero: {exc}")
        return None


async def proponer_tabla(
    mensaje: Message, contexto: ContextTypes.DEFAULT_TYPE, user_id: int, filas: list[list[str]]
) -> None:
    try:
        movimientos = leer_tabla(filas, hoy_local())
    except ImportacionNoValida as exc:
        await mensaje.reply_text(formato.copia_no_valida(exc))
        return
    await proponer(mensaje, contexto, user_id, movimientos)


async def proponer_csv(
    mensaje: Message, contexto: ContextTypes.DEFAULT_TYPE, user_id: int, datos: bytes
) -> None:
    """Un CSV que no es una copia del bot: se intenta leer como tabla de movimientos."""
    try:
        filas = filas_de_csv(decodificar(datos))
    except CopiaNoValida as exc:
        await mensaje.reply_text(formato.copia_no_valida(exc))
        return
    await proponer_tabla(mensaje, contexto, user_id, filas)


async def recibir_excel(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
    datos = await _descargar(update.message, contexto)
    if datos is None:
        return
    try:
        filas = filas_de_xlsx(datos)
    except HojaNoLegible as exc:
        await update.message.reply_text(formato.copia_no_valida(exc))
        return
    await proponer_tabla(update.message, contexto, update.effective_user.id, filas)


async def proponer_captura(
    mensaje: Message, contexto: ContextTypes.DEFAULT_TYPE, user_id: int, imagen: bytes, mime: str
) -> bool:
    """Lee una captura como lista de pagos y la propone. Devuelve si había algo.

    Con un solo movimiento no es una lista: eso es un ticket, y lo dice quien
    llama con su propio mensaje.
    """
    await mensaje.chat.send_action(ChatAction.TYPING)
    try:
        movimientos = await leer_captura(imagen, mime)
    except (LecturaNoDisponible, ErrorDeLectura):
        return False
    if len(movimientos) < 2:
        return False
    await proponer(mensaje, contexto, user_id, movimientos)
    return True


def registrar(app: Application) -> None:
    app.add_handler(MessageHandler(filters.Document.FileExtension("xlsx"), recibir_excel))
    app.add_handler(CallbackQueryHandler(confirmar, pattern=r"^imp:"))
