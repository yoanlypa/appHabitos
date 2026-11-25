"""Casa en el bot: lo que escribe, dicta o fotografía quien vive en la casa.

Yoa quería que su esposa fuera anotando lo que gasta. Ella no tiene negocio,
así que para ella el bot entero es Casa: todo lo que manda va ahí. Para Yoa
el bot sigue siendo del negocio y solo va a Casa lo que empieza por "casa"
("casa -45 súper", una foto con "casa" de texto). Así nunca se mezcla una
compra del súper con un gasto de obra.

Los handlers van ANTES que los del negocio y solo se quedan el mensaje si es
de Casa (`_DE_CASA`); si no, pasa de largo y se anota como siempre. La regla
de qué es gasto y qué es lista está en `servicios/casa.anotar_libre`.
"""
import logging
from decimal import Decimal

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.constants import ChatAction
from telegram.error import BadRequest, TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from app.bot import formato
from app.dominio.casa import quitar_prefijo_casa
from app.nucleo import recetas as cocina
from app.nucleo.config import URL_WEB
from app.nucleo.db import sesion
from app.nucleo.lectura_tickets import ErrorDeLectura, LecturaNoDisponible
from app.nucleo.tiempo import hora_de_la_cartera, hoy_local
from app.servicios import casa as servicio
from app.servicios.facturas import FacturaNoValida

log = logging.getLogger(__name__)


def _es_miembro(user_id: int) -> bool:
    with sesion() as db:
        return servicio.solo_casa(db, user_id)


class _DeCasa(filters.MessageFilter):
    """El mensaje es de Casa (`servicios/casa.es_de_casa`, la misma regla que la voz)."""

    def filter(self, message: Message) -> bool:
        if not message.from_user:
            return False
        with sesion() as db:
            return servicio.es_de_casa(db, message.from_user.id, message.text or message.caption)


class _Miembro(filters.MessageFilter):
    def filter(self, message: Message) -> bool:
        return bool(message.from_user) and _es_miembro(message.from_user.id)


_DE_CASA = _DeCasa()
_MIEMBRO = _Miembro()


def _nombre(update: Update) -> str:
    u = update.effective_user
    return (u.first_name or u.username or "Yo").strip()


def _botones_gasto(gasto) -> InlineKeyboardMarkup:
    otro = "💳 Fue con tarjeta" if gasto.efectivo else "💶 Fue en efectivo"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(otro, callback_data=f"ca:ef:{gasto.id}")],
        [InlineKeyboardButton("🗑 Borrar", callback_data=f"ca:bg:{gasto.id}"),
         InlineKeyboardButton("🛒 Ver lista", callback_data="ca:lista")],
    ])


def _teclado_lista(articulos) -> InlineKeyboardMarkup | None:
    faltan = [a for a in articulos if not a.hay][:40]
    if not faltan:
        return None
    filas = [[InlineKeyboardButton(f"☐ {a.texto}", callback_data=f"ca:hay:{a.id}")] for a in faltan]
    return InlineKeyboardMarkup(filas)


async def _responder(mensaje: Message, user_id: int, texto: str, origen: str, encabezado: str = "") -> None:
    with sesion() as db:
        try:
            hecho = servicio.anotar_libre(db, user_id, texto, origen)
        except servicio.DatoNoValido as exc:
            await mensaje.reply_text(f"{encabezado}No te he entendido: {exc}")
            return
        await pintar(mensaje, db, user_id, hecho, encabezado)


async def pintar(mensaje: Message, db, user_id: int, hecho, encabezado: str = "") -> None:
    """La respuesta a lo anotado en Casa, escrito o dictado."""
    if hecho.gasto:
        quien = None
        if len(servicio.miembros(db, hecho.gasto.hogar_id)) > 1:
            quien = servicio.miembro_de(db, hecho.gasto.user_id).nombre
        await mensaje.reply_text(encabezado + formato.gasto_casa(hecho.gasto, quien), reply_markup=_botones_gasto(hecho.gasto))
    elif hecho.entrada:
        await mensaje.reply_text(encabezado + formato.entrada_cartera(hecho.entrada, servicio.cartera_de(db, user_id)),
                                 reply_markup=_deshacer(hecho.entrada.id))
    elif hecho.recuento:
        await mensaje.reply_text(encabezado + formato.recuento(hecho.recuento), reply_markup=_deshacer(hecho.recuento.movimiento.id))
    else:
        await mensaje.reply_text(encabezado + formato.articulos_anadidos(hecho.articulos))


async def texto(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    _, resto = quitar_prefijo_casa(update.message.text)
    if not resto:
        with sesion() as db:
            yo = servicio.asegurar_casa(db, update.effective_user.id, _nombre(update))
            await update.message.reply_text(formato.ayuda_casa(yo.titular))
        return
    await _responder(update.message, update.effective_user.id, resto, "bot")


async def foto(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
    """El ticket del súper: gasto de casa y lo comprado tachado de la lista."""
    mensaje = update.message
    if mensaje.photo:
        fichero_tg, mime = mensaje.photo[-1], "image/jpeg"
    elif mensaje.document:
        fichero_tg = mensaje.document
        mime = "application/pdf" if (mensaje.document.file_name or "").lower().endswith(".pdf") else (mensaje.document.mime_type or "")
    else:
        return
    _, texto_foto = quitar_prefijo_casa(mensaje.caption)
    await mensaje.chat.send_action(ChatAction.TYPING)
    try:
        fichero = await contexto.bot.get_file(fichero_tg.file_id)
        datos = bytes(await fichero.download_as_bytearray())
    except TelegramError as exc:
        await mensaje.reply_text(f"No he podido descargar la foto: {exc}")
        return
    with sesion() as db:
        try:
            leido = await servicio.escanear_ticket(db, update.effective_user.id, datos, mime, texto_foto)
        except LecturaNoDisponible:
            await mensaje.reply_text("Todavía no sé leer tickets. Escríbeme el importe: «45 súper».")
            return
        except (ErrorDeLectura, FacturaNoValida, servicio.DatoNoValido) as exc:
            await mensaje.reply_text(f"No he podido leer el ticket: {exc}")
            return
        partes = []
        if leido.gasto:
            partes.append(formato.gasto_casa(leido.gasto))
            if leido.fecha_supuesta:
                partes.append("No he visto la fecha: lo he puesto hoy.")
        else:
            partes.append("No he sabido leer el total. Escríbemelo: «45 súper».")
        if leido.tachados:
            partes.append("✅ Tachado de la lista: " + ", ".join(a.texto for a in leido.tachados))
        botones = _botones_gasto(leido.gasto) if leido.gasto else None
        await mensaje.reply_text("\n\n".join(partes), reply_markup=botones)


def _deshacer(mov_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Deshacer", callback_data=f"ca:dm:{mov_id}")]])


# --- Comandos ---------------------------------------------------------------


async def start(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(formato.ayuda_casa(titular=False))


async def lista(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    with sesion() as db:
        servicio.asegurar_casa(db, update.effective_user.id, _nombre(update))
        articulos = servicio.listar_articulos(db, update.effective_user.id)
        await update.message.reply_text(formato.lista_compra(articulos), reply_markup=_teclado_lista(articulos))


async def resumen(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    hoy = hoy_local()
    with sesion() as db:
        yo = servicio.asegurar_casa(db, update.effective_user.id, _nombre(update))
        r = servicio.resumen(db, update.effective_user.id, hoy.replace(day=1), hoy)
        texto_resumen = formato.resumen_casa("Casa este mes", r)
        if not r.total:
            texto_resumen += "\n\n" + formato.ayuda_casa(yo.titular)
        await update.message.reply_text(texto_resumen)


async def cartera(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
    """/cartera enseña las dos; /cartera 35 es contar lo que te queda."""
    user_id = update.effective_user.id
    if contexto.args:
        await _responder(update.message, user_id, "me quedan " + " ".join(contexto.args), "bot")
        return
    with sesion() as db:
        servicio.asegurar_casa(db, user_id, _nombre(update))
        await update.message.reply_text(formato.carteras(servicio.carteras(db, user_id)))


async def saco(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
    if not contexto.args:
        await update.message.reply_text("Dime cuánto: /saco 200")
        return
    with sesion() as db:
        servicio.asegurar_casa(db, update.effective_user.id, _nombre(update))
    await _responder(update.message, update.effective_user.id, "saco " + " ".join(contexto.args), "bot")


async def preguntar_carteras(contexto: ContextTypes.DEFAULT_TYPE) -> None:
    """El domingo, a quien usa su cartera: ¿cuánto te queda? Con lo que debería
    haber, para que si cuadra baste un toque."""
    from app.servicios.avisos import avisos_activos

    with sesion() as db:
        pendientes = [c for c in servicio.por_contar(db) if c.esperado is not None and avisos_activos(db, c.user_id)]
    for c in pendientes:
        centimos = int(c.esperado * 100)
        botones = None
        if centimos >= 0:
            botones = InlineKeyboardMarkup([[InlineKeyboardButton(
                f"✅ Sí, me quedan {formato.euros(c.esperado)}", callback_data=f"ca:rc:{centimos}")]])
        try:
            await contexto.bot.send_message(chat_id=c.user_id, text=formato.pregunta_cartera(c), reply_markup=botones)
        except TelegramError:
            log.warning("No se pudo preguntar la cartera a %s", c.user_id, exc_info=True)


async def invitar(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    with sesion() as db:
        servicio.asegurar_casa(db, update.effective_user.id, _nombre(update))
        try:
            codigo = servicio.crear_invitacion(db, update.effective_user.id)
        except servicio.SoloTitular as exc:
            await update.message.reply_text(f"No puedo: {exc}.")
            return
    texto_inv = (
        "Para que entre en Casa, pásale esto. Vale una vez y durante "
        f"{servicio.DIAS_INVITACION} días.\n\n"
        f"Por Telegram: que le escriba a este bot\n<code>/unirme {codigo}</code>"
    )
    botones = None
    if URL_WEB:
        enlace = f"{URL_WEB}/#invitacion={codigo}"
        texto_inv += f"\n\nSin Telegram, con este enlace:\n{enlace}"
        botones = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Abrir el enlace", url=enlace)]])
    await update.message.reply_text(texto_inv, parse_mode="HTML", reply_markup=botones)


async def unirme(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
    if not contexto.args:
        await update.message.reply_text("Escribe el código que te han pasado: /unirme ABCD2345")
        return
    with sesion() as db:
        try:
            yo = servicio.unirse(db, contexto.args[0], update.effective_user.id, _nombre(update))
        except (servicio.InvitacionNoValida, servicio.YaEnOtraCasa) as exc:
            await update.message.reply_text(f"No he podido: {exc}.")
            return
        otros = [m.nombre for m in servicio.miembros(db, yo.hogar_id) if m.id != yo.id]
    await update.message.reply_text(
        f"¡Hecho, {yo.nombre}! Ya compartes Casa con {', '.join(otros)}.\n\n" + formato.ayuda_casa(titular=False)
    )


async def recetas(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
    preferencias = " ".join(contexto.args or [])
    await update.message.chat.send_action(ChatAction.TYPING)
    with sesion() as db:
        servicio.asegurar_casa(db, update.effective_user.id, _nombre(update))
        try:
            lista_recetas = await servicio.sugerir_recetas(db, update.effective_user.id, preferencias)
        except servicio.DatoNoValido:
            await update.message.reply_text(
                "No sé qué tienes en casa. Dímelo así: /recetas pollo, arroz, pimientos\n"
                "o marca en /lista lo que compres y lo tendré en cuenta."
            )
            return
        except cocina.RecetasNoDisponibles:
            await update.message.reply_text("Las recetas necesitan la clave de OpenAI, que aún no está puesta.")
            return
        except cocina.ErrorDeRecetas:
            await update.message.reply_text("No he podido pensar recetas ahora. Prueba otra vez en un rato.")
            return
    await update.message.reply_text(formato.recetas(lista_recetas))


async def tocar(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    consulta = update.callback_query
    partes = consulta.data.split(":")
    user_id = update.effective_user.id
    with sesion() as db:
        try:
            if partes[1] == "hay":
                articulo = servicio.marcar(db, user_id, int(partes[2]), True)
                await consulta.answer(f"✅ {articulo.texto}")
                articulos = servicio.listar_articulos(db, user_id)
                try:
                    await consulta.edit_message_text(formato.lista_compra(articulos), reply_markup=_teclado_lista(articulos))
                except BadRequest:
                    pass
            elif partes[1] == "lista":
                await consulta.answer()
                articulos = servicio.listar_articulos(db, user_id)
                await consulta.message.reply_text(formato.lista_compra(articulos), reply_markup=_teclado_lista(articulos))
            elif partes[1] == "ef":
                gasto = servicio.cambiar_pago(db, user_id, int(partes[2]))
                await consulta.answer("💶 En efectivo" if gasto.efectivo else "💳 Con tarjeta")
                await consulta.edit_message_text(formato.gasto_casa(gasto), reply_markup=_botones_gasto(gasto))
            elif partes[1] == "rc":
                r = servicio.contar_cartera(db, user_id, Decimal(int(partes[2])) / 100)
                await consulta.answer("Contado")
                await consulta.edit_message_text(formato.recuento(r), reply_markup=_deshacer(r.movimiento.id))
            elif partes[1] == "dm":
                servicio.deshacer_movimiento(db, user_id, int(partes[2]))
                await consulta.answer("Deshecho")
                await consulta.edit_message_text("↩️ Deshecho: tu cartera está como antes.")
            elif partes[1] == "bg":
                servicio.borrar_gasto(db, user_id, int(partes[2]))
                await consulta.answer("Borrado")
                await consulta.edit_message_text("🗑 Gasto de casa borrado.")
        except (servicio.NoEncontrado, servicio.SinCasa):
            await consulta.answer("Eso ya no está.")
        except servicio.DatoNoValido as exc:
            await consulta.answer(str(exc))


def registrar(app: Application) -> None:
    """Antes que los handlers del negocio: si no, el texto de ella sería un apunte de Yoa."""
    app.add_handler(CommandHandler("start", start, filters=_MIEMBRO))
    app.add_handler(CommandHandler("menu", start, filters=_MIEMBRO))
    app.add_handler(CommandHandler("lista", lista))
    app.add_handler(CommandHandler("casa", resumen))
    app.add_handler(CommandHandler("invitar", invitar))
    app.add_handler(CommandHandler("unirme", unirme))
    app.add_handler(CommandHandler("recetas", recetas))
    app.add_handler(CommandHandler("cartera", cartera))
    app.add_handler(CommandHandler("saco", saco))
    app.add_handler(CallbackQueryHandler(tocar, pattern=r"^ca:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & _DE_CASA, texto))
    # La voz no tiene handler aquí: la escucha `handlers.nota_de_voz` para
    # todos, y `servicios/voz` la manda a Casa con la misma regla que el texto.
    app.add_handler(
        MessageHandler((filters.PHOTO | filters.Document.IMAGE | filters.Document.PDF) & _DE_CASA, foto)
    )
    # El domingo por la tarde, antes del resumen de las 21:00: ¿cuánto queda?
    app.job_queue.run_daily(preguntar_carteras, time=hora_de_la_cartera(), days=(6,), name="carteras")
