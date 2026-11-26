"""Los trabajos (las obras) desde Telegram: crearlos, verlos y cerrarlos.

Hasta ahora un trabajo solo se podía crear en la web, y meter en él un
gasto también. Pero el gasto se hace en la obra, con el móvil y el bot
abierto: es ahí donde hay que poder decir "esto es de la reforma de Ana".

- `/trabajo Reforma baño Ana Ruiz` crea uno que empieza hoy. El cliente se
  reconoce como al anotar: uno solo, puesto; dos Anas, se pregunta.
- `/trabajos` (o `/trabajo` sin nada) lista los que están en curso; tocando
  uno se ve su ficha con sus cuentas, y se puede marcar terminado o
  facturado.
- El botón "📁 Trabajo" bajo cada cobro o gasto lo mete en uno
  (`bot/acciones.py`).

Aquí no se calcula nada: las cuentas y qué está "en curso" salen de
`servicios/trabajos.py`, lo mismo que ve la web.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from app.bot import formato
from app.nucleo.db import sesion
from app.nucleo.tiempo import hoy_local
from app.servicios.trabajos import (
    TrabajoNoEncontrado,
    TrabajoNoValido,
    actualizar_trabajo,
    crear_por_texto,
    en_curso,
    ficha_trabajo,
    listar_trabajos,
)

_EN_LISTA = 8


def _botones_de_lista(listados) -> InlineKeyboardMarkup | None:
    if not listados:
        return None
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(formato.boton_de_obra(l.trabajo), callback_data=f"tr:ver:{l.trabajo.id}")]
            for l in listados[:_EN_LISTA]
        ]
    )


def _botones_de_ficha(trabajo) -> InlineKeyboardMarkup:
    n = trabajo.id
    primera = []
    if trabajo.fecha_fin is None or trabajo.fecha_fin > hoy_local():
        primera.append(InlineKeyboardButton("✅ Terminado hoy", callback_data=f"tr:fin:{n}"))
    primera.append(
        InlineKeyboardButton(
            "🧾 Quitar facturado" if trabajo.facturado else "🧾 Facturado", callback_data=f"tr:fac:{n}"
        )
    )
    return InlineKeyboardMarkup(
        [primera, [InlineKeyboardButton("« Trabajos en curso", callback_data="tr:lis:0")]]
    )


def _en_curso_listados(db, user_id: int):
    """Los listados (con cuentas) solo de los trabajos en curso."""
    vivos = {t.id for t in en_curso(db, user_id)}
    return [l for l in listar_trabajos(db, user_id) if l.trabajo.id in vivos]


async def preguntar_cliente(mensaje: Message, nuevo) -> None:
    """Si el nombre del trabajo nombra a dos clientes, de cuál es."""
    t = nuevo.trabajo
    botones = [
        [InlineKeyboardButton(formato.descripcion_corta(c), callback_data=f"tr:cli:{t.id}:{c.id}")]
        for c in nuevo.candidatos
    ]
    botones.append([InlineKeyboardButton("Ninguno", callback_data=f"tr:cli:{t.id}:0")])
    nombre = nuevo.candidatos[0].nombre.split()[0]
    await mensaje.reply_text(
        f"¿De qué {nombre} es «{t.titulo}»?", reply_markup=InlineKeyboardMarkup(botones)
    )


async def trabajo(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
    """/trabajo Nombre crea uno; /trabajo a secas enseña los que hay en curso."""
    texto = " ".join(contexto.args or []).strip()
    if not texto:
        await trabajos(update, contexto)
        return
    with sesion() as db:
        try:
            nuevo = crear_por_texto(db, update.effective_user.id, texto)
        except TrabajoNoValido as exc:
            await update.message.reply_text(f"No he podido crear el trabajo: {exc}")
            return
        await update.message.reply_text(
            formato.trabajo_creado(nuevo.trabajo), reply_markup=_botones_de_ficha(nuevo.trabajo)
        )
        if nuevo.candidatos:
            await preguntar_cliente(update.message, nuevo)


async def trabajos(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    with sesion() as db:
        listados = _en_curso_listados(db, update.effective_user.id)
        await update.message.reply_text(
            formato.lista_trabajos(listados), reply_markup=_botones_de_lista(listados)
        )


async def _repintar(consulta, texto: str, botones=None) -> None:
    try:
        await consulta.edit_message_text(texto, reply_markup=botones)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise


async def tocar(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    consulta = update.callback_query
    await consulta.answer()
    partes = consulta.data.split(":")
    accion, trabajo_id = partes[1], int(partes[2])
    user_id = consulta.from_user.id

    with sesion() as db:
        try:
            if accion == "lis":
                listados = _en_curso_listados(db, user_id)
                await _repintar(consulta, formato.lista_trabajos(listados), _botones_de_lista(listados))
                return
            if accion == "fin":
                actualizar_trabajo(db, user_id, trabajo_id, fecha_fin=hoy_local())
            elif accion == "fac":
                actual = ficha_trabajo(db, user_id, trabajo_id).trabajo
                actualizar_trabajo(db, user_id, trabajo_id, facturado=not actual.facturado)
            elif accion == "cli":
                cliente_id = int(partes[3]) or None
                actualizar_trabajo(db, user_id, trabajo_id, cliente_id=cliente_id)
            ficha = ficha_trabajo(db, user_id, trabajo_id)
            await _repintar(consulta, formato.ficha_trabajo(ficha), _botones_de_ficha(ficha.trabajo))
        except TrabajoNoEncontrado:
            await _repintar(consulta, "Ese trabajo ya no está.")
        except TrabajoNoValido as exc:
            await consulta.message.reply_text(f"No he podido: {exc}")


def registrar(app: Application) -> None:
    app.add_handler(CommandHandler("trabajo", trabajo))
    app.add_handler(CommandHandler("trabajos", trabajos))
    app.add_handler(CallbackQueryHandler(tocar, pattern=r"^tr:"))
