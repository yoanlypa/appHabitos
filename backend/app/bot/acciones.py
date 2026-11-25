"""Los botones de debajo de cada apunte: cobrar, cambiar el día, corregir,
meterlo en un trabajo, borrar.

Antes todo eso se hacía con el número del apunte (`/fecha 34 15/10`), y el
número hay que haberlo leído y acordarse de él. Con el apunte recién
anotado delante, lo natural es tocarlo. Los comandos con número siguen
valiendo: esto no los sustituye, les quita la necesidad.

Aquí no se decide nada: cada botón llama a un servicio que ya existía
(`marcar_cobrado`, `actualizar_apunte`, `borrar_apunte`) y repinta.

Los datos del botón son `ap:<acción>:<id>[:<extra>]`. Todo va por id y se
vuelve a comprobar que el apunte es de quien toca: un botón viejo de un
apunte ya borrado contesta "ya no está", no revienta.
"""
from datetime import timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

from app.bot import formato
from app.bot.trabajos import preguntar_cliente
from app.dominio.parsing import TextoNoInterpretable, interpretar_texto
from app.dominio.tickets import fecha_escrita
from app.nucleo.db import sesion
from app.nucleo.tiempo import hoy_local
from app.servicios.apuntes import (
    ApunteNoEncontrado,
    MovimientoNoValido,
    actualizar_apunte,
    asignar_trabajo,
    borrar_apunte,
    marcar_cobrado,
    obtener_apunte,
)
from app.servicios.clientes import pendientes_de_cobro
from app.servicios.notas import listar_notas
from app.servicios.notas import marcar_hecha as marcar_nota_hecha
from app.servicios.trabajos import (
    TrabajoNoEncontrado,
    TrabajoNoValido,
    crear_por_texto,
    en_curso,
)

# El apunte al que hay que ponerle el día que se escriba a continuación.
ESPERA_FECHA = "fecha_para_apunte"
# El apunte que hay que meter en el trabajo nuevo cuyo nombre se escriba.
ESPERA_TRABAJO = "trabajo_para_apunte"
# Cuántos botones caben en una lista sin que el mensaje sea un mando a distancia.
_BOTONES_EN_LISTA = 8


def botones_de(apunte) -> InlineKeyboardMarkup:
    """Lo que se puede hacer con un apunte, según lo que sea."""
    n = apunte.id
    if apunte.tipo == "nota":
        fila = []
        if not apunte.hecha:
            fila.append(InlineKeyboardButton("✓ Hecha", callback_data=f"ap:nh:{n}"))
        fila.append(InlineKeyboardButton("🗑 Borrar", callback_data=f"ap:del:{n}"))
        return InlineKeyboardMarkup([fila])

    primera = []
    if apunte.tipo == "trabajo" and apunte.pendiente:
        primera.append(InlineKeyboardButton("✅ Cobrado", callback_data=f"ap:cob:{n}"))
    # Cambiar de cobro a gasto es para lo tecleado ("gasolina 45" sin guion).
    # Lo que salió de un ticket o una factura tiene su propio camino
    # (/emitida), que además mueve el papel.
    if apunte.factura is None:
        if apunte.tipo == "gasto":
            primera.append(InlineKeyboardButton("↔️ Es un cobro", callback_data=f"ap:tipo:{n}"))
        elif not apunte.pendiente:
            primera.append(InlineKeyboardButton("↔️ Es un gasto", callback_data=f"ap:tipo:{n}"))
    segunda = [
        InlineKeyboardButton("📁 Trabajo", callback_data=f"ap:trab:{n}"),
        InlineKeyboardButton("📅 Otro día", callback_data=f"ap:fec:{n}"),
        InlineKeyboardButton("🗑 Borrar", callback_data=f"ap:del:{n}"),
    ]
    return InlineKeyboardMarkup([primera, segunda] if primera else [segunda])


def _botones_de_fecha(apunte_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Hoy", callback_data=f"ap:fd:{apunte_id}:0"),
                InlineKeyboardButton("Ayer", callback_data=f"ap:fd:{apunte_id}:1"),
                InlineKeyboardButton("Anteayer", callback_data=f"ap:fd:{apunte_id}:2"),
            ],
            [
                InlineKeyboardButton("✏️ Escribir el día", callback_data=f"ap:fo:{apunte_id}"),
                InlineKeyboardButton("« Volver", callback_data=f"ap:ver:{apunte_id}"),
            ],
        ]
    )


def _botones_de_obra(apunte, trabajos) -> InlineKeyboardMarkup:
    """Los trabajos en curso para elegir, más crear uno o sacarlo del suyo."""
    n = apunte.id
    filas = [
        [InlineKeyboardButton(formato.boton_de_obra(t), callback_data=f"ap:tj:{n}:{t.id}")]
        for t in trabajos[: _BOTONES_EN_LISTA - 1]
        if t.id != apunte.trabajo_id
    ]
    filas.append([InlineKeyboardButton("➕ Trabajo nuevo", callback_data=f"ap:tn:{n}")])
    ultima = []
    if apunte.trabajo_id is not None:
        ultima.append(InlineKeyboardButton("Sacar del trabajo", callback_data=f"ap:tj:{n}:0"))
    ultima.append(InlineKeyboardButton("« Volver", callback_data=f"ap:ver:{n}"))
    filas.append(ultima)
    return InlineKeyboardMarkup(filas)


def _botones_de_borrado(apunte_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Sí, borrar", callback_data=f"ap:dely:{apunte_id}"),
                InlineKeyboardButton("No", callback_data=f"ap:ver:{apunte_id}"),
            ]
        ]
    )


def texto_de(apunte) -> str:
    """Cómo se ve un apunte ya anotado, con su cliente y su trabajo si los tiene."""
    if apunte.cliente is not None:
        texto = formato.apunte_creado_con_cliente(apunte, apunte.cliente)
    else:
        texto = formato.apunte_creado(apunte)
    if apunte.trabajo is not None:
        texto += f"\n   📁 {apunte.trabajo.titulo}"
    return texto


async def _repintar(consulta, texto: str, botones: InlineKeyboardMarkup | None = None) -> None:
    """Cambia el mensaje del botón. Si ya decía eso, no pasa nada.

    Telegram contesta con error al editar un mensaje para dejarlo igual (dos
    toques seguidos al mismo botón). El mensaje con un ticket es un
    documento: ahí el texto es el pie de foto y se edita de otra manera.
    """
    try:
        if getattr(consulta.message, "document", None) or getattr(consulta.message, "photo", None):
            await consulta.edit_message_caption(caption=texto, reply_markup=botones)
        else:
            await consulta.edit_message_text(texto, reply_markup=botones)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise


async def _cambiar_botones(consulta, botones: InlineKeyboardMarkup) -> None:
    try:
        await consulta.edit_message_reply_markup(reply_markup=botones)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise


async def tocar(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
    consulta = update.callback_query
    await consulta.answer()
    partes = consulta.data.split(":")
    accion, apunte_id = partes[1], int(partes[2])
    user_id = consulta.from_user.id

    with sesion() as db:
        try:
            if accion == "cob":
                apunte = marcar_cobrado(db, user_id, apunte_id)
                await _repintar(consulta, formato.apunte_cobrado(apunte), botones_de(apunte))
            elif accion == "tipo":
                apunte = obtener_apunte(db, user_id, apunte_id)
                otro = "trabajo" if apunte.tipo == "gasto" else "gasto"
                apunte = actualizar_apunte(db, user_id, apunte_id, tipo=otro)
                await _repintar(consulta, formato.tipo_cambiado(apunte), botones_de(apunte))
            elif accion == "fec":
                apunte = obtener_apunte(db, user_id, apunte_id)
                await _cambiar_botones(consulta, _botones_de_fecha(apunte.id))
            elif accion == "fd":
                dia = hoy_local() - timedelta(days=int(partes[3]))
                apunte = actualizar_apunte(db, user_id, apunte_id, fecha=dia)
                await _repintar(consulta, formato.fecha_cambiada(apunte), botones_de(apunte))
            elif accion == "fo":
                apunte = obtener_apunte(db, user_id, apunte_id)
                contexto.user_data[ESPERA_FECHA] = apunte.id
                await consulta.message.reply_text(formato.pedir_fecha(apunte))
            elif accion == "del":
                apunte = obtener_apunte(db, user_id, apunte_id)
                await _repintar(consulta, formato.confirmar_borrado(apunte), _botones_de_borrado(apunte.id))
            elif accion == "dely":
                apunte = borrar_apunte(db, user_id, apunte_id)
                if contexto.user_data.get(ESPERA_FECHA) == apunte_id:
                    contexto.user_data.pop(ESPERA_FECHA, None)
                await _repintar(consulta, formato.apunte_borrado(apunte))
            elif accion == "ver":
                apunte = obtener_apunte(db, user_id, apunte_id)
                await _repintar(consulta, texto_de(apunte), botones_de(apunte))
            elif accion == "trab":
                apunte = obtener_apunte(db, user_id, apunte_id)
                trabajos = en_curso(db, user_id)
                await _repintar(
                    consulta,
                    f"{texto_de(apunte)}\n\n{formato.elegir_obra(apunte, bool(trabajos))}",
                    _botones_de_obra(apunte, trabajos),
                )
            elif accion == "tj":
                trabajo_id = int(partes[3]) or None
                (apunte,) = asignar_trabajo(db, user_id, [apunte_id], trabajo_id)
                await _repintar(consulta, texto_de(apunte), botones_de(apunte))
            elif accion == "tn":
                apunte = obtener_apunte(db, user_id, apunte_id)
                contexto.user_data[ESPERA_TRABAJO] = apunte.id
                await consulta.message.reply_text(formato.pedir_nombre_trabajo(apunte))
            elif accion == "nh":
                nota = marcar_nota_hecha(db, user_id, apunte_id)
                await _repintar(consulta, formato.nota_hecha(nota))
        except ApunteNoEncontrado:
            await _repintar(consulta, "Ese apunte ya no está.")
        except TrabajoNoEncontrado:
            await consulta.message.reply_text("Ese trabajo ya no está. Toca otra vez «📁 Trabajo».")
        except MovimientoNoValido as exc:
            await consulta.message.reply_text(f"No he podido: {exc}")


async def fecha_escrita_para(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> bool:
    """Si se estaba esperando el día de un apunte y esto lo es, lo mueve.

    Devuelve si el mensaje era eso. Solo se da por respuesta un texto que sea
    una fecha y nada más: si en vez del día se escribe otro apunte ("-45
    gasolina"), se deja de esperar y ese texto se anota como siempre. Un
    apunte no puede perderse por haber tocado antes un botón.
    """
    apunte_id = contexto.user_data.pop(ESPERA_FECHA, None)
    if apunte_id is None:
        return False
    fecha, resto = fecha_escrita(update.message.text, hoy_local())
    if fecha is None or resto.strip():
        return False
    with sesion() as db:
        try:
            apunte = actualizar_apunte(db, update.effective_user.id, apunte_id, fecha=fecha)
        except ApunteNoEncontrado:
            await update.message.reply_text("Ese apunte ya no está.")
            return True
        await update.message.reply_text(
            formato.fecha_cambiada(apunte), reply_markup=botones_de(apunte)
        )
    return True


def _es_un_apunte(texto: str) -> bool:
    """Si el texto, tal cual, se anotaría como cobro o gasto (lleva importe)."""
    if "\n" in texto.strip():
        return True  # varias líneas: una lista, o una nota larga; no un nombre
    try:
        interpretar_texto(texto)
    except TextoNoInterpretable:
        return False
    return True


async def trabajo_escrito_para(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> bool:
    """Si se tocó "➕ Trabajo nuevo", este texto es su nombre... salvo que sea un apunte.

    Misma regla que "Escribir el día": un apunte no puede comerse por haber
    tocado antes un botón. Si lo escrito lleva importe ("-45 gasolina"), se
    deja de esperar y se anota como siempre; el nombre de un trabajo que
    acabe en número se crea con /trabajo.
    """
    apunte_id = contexto.user_data.pop(ESPERA_TRABAJO, None)
    if apunte_id is None:
        return False
    texto = update.message.text or ""
    if not texto.strip() or _es_un_apunte(texto):
        return False
    user_id = update.effective_user.id
    with sesion() as db:
        try:
            apunte = obtener_apunte(db, user_id, apunte_id)
            nuevo = crear_por_texto(db, user_id, texto)
            (apunte,) = asignar_trabajo(db, user_id, [apunte.id], nuevo.trabajo.id)
        except ApunteNoEncontrado:
            await update.message.reply_text("Ese apunte ya no está.")
            return True
        except TrabajoNoValido as exc:
            await update.message.reply_text(f"No he podido crear el trabajo: {exc}")
            return True
        await update.message.reply_text(
            f"{formato.trabajo_creado(nuevo.trabajo, con_ayuda=False)}\n\n{texto_de(apunte)}",
            reply_markup=botones_de(apunte),
        )
        if nuevo.candidatos:
            await preguntar_cliente(update.message, nuevo)
    return True


# --- Listas que se resuelven tocando ------------------------------------------


def botones_de_deudas(pendientes: list) -> InlineKeyboardMarkup | None:
    if not pendientes:
        return None
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(formato.boton_cobrar(a), callback_data=f"lc:{a.id}")]
            for a in pendientes[:_BOTONES_EN_LISTA]
        ]
    )


def botones_de_notas(notas: list) -> InlineKeyboardMarkup | None:
    if not notas:
        return None
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(formato.boton_nota(n), callback_data=f"ln:{n.id}")]
            for n in notas[:_BOTONES_EN_LISTA]
        ]
    )


async def cobrar_de_la_lista(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    """Un toque en /deben: cobrado, y la lista se queda con los que faltan."""
    consulta = update.callback_query
    await consulta.answer()
    with sesion() as db:
        try:
            marcar_cobrado(db, consulta.from_user.id, int(consulta.data.split(":")[1]))
        except ApunteNoEncontrado:
            pass  # ya no está: la lista repintada lo dirá sola
        pendientes = pendientes_de_cobro(db, consulta.from_user.id)
        await _repintar(consulta, formato.lista_deudas(pendientes), botones_de_deudas(pendientes))


async def nota_de_la_lista(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    consulta = update.callback_query
    await consulta.answer()
    with sesion() as db:
        try:
            marcar_nota_hecha(db, consulta.from_user.id, int(consulta.data.split(":")[1]))
        except ApunteNoEncontrado:
            pass
        notas = listar_notas(db, consulta.from_user.id)
        await _repintar(consulta, formato.lista_notas(notas), botones_de_notas(notas))


def registrar(app: Application) -> None:
    app.add_handler(CallbackQueryHandler(tocar, pattern=r"^ap:"))
    app.add_handler(CallbackQueryHandler(cobrar_de_la_lista, pattern=r"^lc:"))
    app.add_handler(CallbackQueryHandler(nota_de_la_lista, pattern=r"^ln:"))
