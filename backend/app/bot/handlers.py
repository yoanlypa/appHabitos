"""Handlers de Telegram: parsean la entrada, llaman a un servicio y formatean.

Nada más que eso. La misma lógica que usa la API vive en `servicios/`, así
que el bot no calcula ni decide: solo traduce entre Telegram y los casos de
uso.

Los servicios son síncronos (SQLAlchemy) y los handlers async: para un bot
personal contra SQLite la consulta dura milisegundos, así que no compensa
sacarla a un hilo.
"""
from datetime import timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from app.bot import copias, formato
from app.dominio.parsing import TextoNoInterpretable
from app.dominio.parsing_citas import CitaNoInterpretable, interpretar_cita
from app.nucleo.db import sesion
from app.nucleo.transcripcion import (
    TAMANO_MAXIMO,
    ErrorDeTranscripcion,
    TranscripcionNoDisponible,
)
from app.nucleo.tiempo import hoy_local
from app.servicios.agenda import citas_del_dia, crear_cita
from app.servicios.apuntes import ApunteNoEncontrado, borrar_apunte, marcar_cobrado
from app.servicios.apuntes import anotar as anotar_apunte
from app.servicios.auth import generar_token
from app.servicios.avisos import activar_avisos, avisos_activos
from app.servicios.clientes import asignar_cliente, crear_cliente, pendientes_de_cobro
from app.servicios.notas import listar_notas
from app.servicios.notas import marcar_hecha as marcar_nota_hecha
from app.servicios.resumen import resumen_dia, resumen_mes
from app.servicios.trimestres import resumen_trimestre, trimestre_de
from app.servicios.voz import NadaQueAnotar, anotar_audio


async def start(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(formato.ayuda())


async def anotar(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    """Cualquier mensaje de texto que no sea un comando es un apunte.

    Si el texto nombra a un cliente y no hay duda de cuál es, queda colgado
    de él sin preguntar. Si hay dos con ese nombre, se pregunta con botones:
    colgarlo de la Ana equivocada sería peor que dejarlo suelto.

    Lo que no lleve importe se guarda como nota, igual que lo dictado.
    Escribir no cuesta nada y es lo que se hace siempre que se puede: sería
    absurdo que el bot solo supiera guardar recordatorios por voz.
    """
    with sesion() as db:
        try:
            anotado = anotar_apunte(
                db,
                update.effective_user.id,
                update.message.text,
                origen="bot",
                admite_nota=True,
            )
        except TextoNoInterpretable as exc:
            await update.message.reply_text(f"No te he entendido: {exc}\n\n{formato.ayuda()}")
            return

        await _responder_anotado(update.message, anotado)


async def _responder_anotado(mensaje: Message, anotado, encabezado: str = "") -> None:
    """Contesta lo anotado, y pregunta por el cliente si había dos iguales.

    Lo comparten el texto y las notas de voz: la única diferencia es que la
    voz enseña antes lo que se entendió al escuchar.
    """
    apunte = anotado.apunte
    delante = f"{encabezado}\n\n" if encabezado else ""

    if apunte.cliente is not None:
        await mensaje.reply_text(
            delante + formato.apunte_creado_con_cliente(apunte, apunte.cliente)
        )
        return

    if not anotado.candidatos:
        await mensaje.reply_text(delante + formato.apunte_creado(apunte))
        return

    botones = [
        [
            InlineKeyboardButton(
                formato.descripcion_corta(c), callback_data=f"cli:{apunte.id}:{c.id}"
            )
        ]
        for c in anotado.candidatos
    ]
    botones.append([InlineKeyboardButton("Ninguno", callback_data=f"cli:{apunte.id}:0")])
    await mensaje.reply_text(
        f"{delante}{formato.apunte_creado(apunte)}\n\n"
        f"{formato.preguntar_cliente(anotado.candidatos[0].nombre.split()[0])}",
        reply_markup=InlineKeyboardMarkup(botones),
    )


# Extensión por tipo de audio: el transcriptor deduce el formato del nombre
# del fichero, y Telegram no lo manda. Las notas de voz siempre son OGG.
_EXTENSIONES = {
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/webm": "webm",
    "audio/flac": "flac",
}


def _nombre_de_fichero(audio) -> str:
    nombre = getattr(audio, "file_name", None)
    if nombre and "." in nombre:
        return nombre
    return "nota." + _EXTENSIONES.get(getattr(audio, "mime_type", None) or "", "ogg")


async def nota_de_voz(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
    """Una nota de voz se escucha y se anota igual que si se hubiera escrito.

    Dictar es lo natural cuando se apunta con las manos ocupadas, que es
    justo cuando se pierden los trabajos. Se responde siempre con lo que se
    entendió: si el transcriptor oyó mal, se ve al momento y se /borra.
    """
    audio = update.message.voice or update.message.audio
    if audio is None:
        return

    if audio.file_size and audio.file_size > TAMANO_MAXIMO:
        await update.message.reply_text(
            "Esa nota es demasiado larga para escucharla. Mándamela más corta."
        )
        return

    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        fichero = await contexto.bot.get_file(audio.file_id)
        datos = bytes(await fichero.download_as_bytearray())
    except TelegramError as exc:
        await update.message.reply_text(f"No he podido descargar el audio: {exc}")
        return

    with sesion() as db:
        try:
            escuchada = await anotar_audio(
                db,
                update.effective_user.id,
                datos,
                _nombre_de_fichero(audio),
                origen="bot",
            )
        except TranscripcionNoDisponible:
            await update.message.reply_text(
                "Todavía no sé escuchar: falta configurar OPENAI_API_KEY.\n"
                "Mientras tanto, escríbemelo y lo anoto igual."
            )
            return
        except (ErrorDeTranscripcion, NadaQueAnotar) as exc:
            await update.message.reply_text(
                f"No he podido escuchar esa nota: {exc}\n"
                "El audio sigue en el chat, no se ha perdido nada."
            )
            return

        await _responder_anotado(
            update.message, escuchada.anotado, encabezado=formato.escuchado(escuchada.texto)
        )


async def elegir_cliente(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    """Respuesta a los botones de "¿qué Ana?"."""
    consulta = update.callback_query
    await consulta.answer()

    _, apunte_id, cliente_id = consulta.data.split(":")
    with sesion() as db:
        try:
            apunte = asignar_cliente(
                db,
                consulta.from_user.id,
                int(apunte_id),
                int(cliente_id) or None,
            )
        except LookupError:
            await consulta.edit_message_text("Ese apunte ya no está.")
            return

        if apunte.cliente is None:
            await consulta.edit_message_text(formato.apunte_creado(apunte))
        else:
            await consulta.edit_message_text(
                formato.apunte_creado_con_cliente(apunte, apunte.cliente)
            )


async def cliente(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
    """Alta rápida: /cliente Ana Ruiz 600111222 (el teléfono es opcional)."""
    partes = list(contexto.args or [])
    if not partes:
        await update.message.reply_text("Dime el nombre: /cliente Ana Ruiz 600111222")
        return

    telefono = None
    if partes[-1].replace("+", "").isdigit() and len(partes[-1]) >= 7:
        telefono = partes.pop()
    nombre = " ".join(partes).strip()
    if not nombre:
        await update.message.reply_text("Falta el nombre: /cliente Ana Ruiz 600111222")
        return

    with sesion() as db:
        nuevo = crear_cliente(db, update.effective_user.id, nombre, telefono=telefono)
        await update.message.reply_text(f"Cliente dado de alta: {formato.descripcion_corta(nuevo)}")


async def hoy(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    with sesion() as db:
        r = resumen_dia(db, update.effective_user.id)
        await update.message.reply_text(formato.resumen("Hoy:", r))


async def mes(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    with sesion() as db:
        hoy_ = hoy_local()
        r = resumen_mes(db, update.effective_user.id, hoy_.year, hoy_.month)
        await update.message.reply_text(formato.resumen(f"Mes {hoy_.month:02d}/{hoy_.year}:", r))


async def cobrado(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
    if not contexto.args or not contexto.args[0].lstrip("#").isdigit():
        await update.message.reply_text("Dime cuál: /cobrado 12")
        return
    apunte_id = int(contexto.args[0].lstrip("#"))
    with sesion() as db:
        try:
            apunte = marcar_cobrado(db, update.effective_user.id, apunte_id)
        except ApunteNoEncontrado:
            await update.message.reply_text(f"No tengo ningún apunte con el número {apunte_id}.")
            return
        await update.message.reply_text(formato.apunte_cobrado(apunte))


async def avisos(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    opcion = contexto.args[0].lower() if contexto.args else ""

    with sesion() as db:
        if opcion not in ("on", "off"):
            estado = "activados" if avisos_activos(db, user_id) else "desactivados"
            await update.message.reply_text(
                f"Tus avisos están {estado}. Cámbialo con /avisos on o /avisos off."
            )
            return
        activar_avisos(db, user_id, opcion == "on")

    await update.message.reply_text(
        "Aviso diario activado." if opcion == "on" else "Aviso diario desactivado."
    )


async def web(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    with sesion() as db:
        token = generar_token(db, update.effective_user.id)
    await update.message.reply_text(
        f"Tu token para entrar en la web (no lo compartas):\n\n{token}"
    )


async def agenda(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    with sesion() as db:
        citas = citas_del_dia(db, update.effective_user.id)
        await update.message.reply_text(formato.lista_citas("Hoy:", citas))


async def manana(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    with sesion() as db:
        dia = hoy_local() + timedelta(days=1)
        citas = citas_del_dia(db, update.effective_user.id, dia)
        await update.message.reply_text(formato.lista_citas("Mañana:", citas))


async def cita(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
    texto = " ".join(contexto.args or [])
    with sesion() as db:
        try:
            interpretada = interpretar_cita(texto, hoy_local())
        except CitaNoInterpretable as exc:
            await update.message.reply_text(
                f"No te he entendido: {exc}\n\nPrueba: /cita mañana 10:00 Cambiar grifo"
            )
            return
        nueva = crear_cita(
            db,
            update.effective_user.id,
            interpretada.fecha,
            interpretada.titulo,
            hora=interpretada.hora,
        )
        await update.message.reply_text(formato.cita_creada(nueva))


async def notas(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    """El buzón: lo apuntado que sigue sin fecha ni precio.

    Solo listar. Ponerle fecha abre un modal con rango de días y texto
    editable, y eso es cosa de la web; aquí sería un baile de botones.
    """
    with sesion() as db:
        await update.message.reply_text(
            formato.lista_notas(listar_notas(db, update.effective_user.id))
        )


async def hecha(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
    """Marca una nota como cumplida: /hecha 42.

    No se borra: lo cumplido no es lo equivocado, y la web deja verlo y
    deshacerlo. Para lo equivocado ya está /borrar.
    """
    if not contexto.args or not contexto.args[0].lstrip("#").isdigit():
        await update.message.reply_text("Dime cuál: /hecha 12")
        return
    nota_id = int(contexto.args[0].lstrip("#"))
    with sesion() as db:
        try:
            nota = marcar_nota_hecha(db, update.effective_user.id, nota_id)
        except ApunteNoEncontrado:
            await update.message.reply_text(f"No tengo ninguna nota con el número {nota_id}.")
            return
        await update.message.reply_text(formato.nota_hecha(nota))


async def deben(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    with sesion() as db:
        await update.message.reply_text(
            formato.lista_deudas(pendientes_de_cobro(db, update.effective_user.id))
        )


async def borrar(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
    """Para el 1200 que iba a ser 120: /borrar 34."""
    if not contexto.args or not contexto.args[0].lstrip("#").isdigit():
        await update.message.reply_text("Dime cuál: /borrar 12")
        return
    apunte_id = int(contexto.args[0].lstrip("#"))
    with sesion() as db:
        try:
            apunte = borrar_apunte(db, update.effective_user.id, apunte_id)
        except ApunteNoEncontrado:
            await update.message.reply_text(f"No tengo ningún apunte con el número {apunte_id}.")
            return
        await update.message.reply_text(formato.apunte_borrado(apunte))


async def copia(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
    """Manda ahora mismo el histórico entero en CSV."""
    enviada = await copias.enviar_copia(contexto, update.effective_user.id)
    if not enviada:
        await update.message.reply_text("Todavía no hay nada que guardar.")


async def trimestre(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    with sesion() as db:
        hoy = hoy_local()
        r = resumen_trimestre(db, update.effective_user.id, hoy.year, trimestre_de(hoy))
        await update.message.reply_text(formato.resumen_trimestre(r))
