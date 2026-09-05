"""Handlers de Telegram: parsean la entrada, llaman a un servicio y formatean.

Nada más que eso. La misma lógica que usa la API vive en `servicios/`, así
que el bot no calcula ni decide: solo traduce entre Telegram y los casos de
uso.

Los servicios son síncronos (SQLAlchemy) y los handlers async: para un bot
personal contra SQLite la consulta dura milisegundos, así que no compensa
sacarla a un hilo.
"""
from datetime import timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.bot import copias, formato
from app.dominio.parsing import TextoNoInterpretable
from app.dominio.parsing_citas import CitaNoInterpretable, interpretar_cita
from app.nucleo.db import sesion
from app.nucleo.tiempo import hoy_local
from app.servicios.agenda import citas_del_dia, crear_cita
from app.servicios.apuntes import ApunteNoEncontrado, borrar_apunte, marcar_cobrado
from app.servicios.apuntes import anotar as anotar_apunte
from app.servicios.auth import generar_token
from app.servicios.avisos import activar_avisos, avisos_activos
from app.servicios.clientes import asignar_cliente, crear_cliente, pendientes_de_cobro
from app.servicios.resumen import resumen_dia, resumen_mes
from app.servicios.trimestres import resumen_trimestre, trimestre_de


async def start(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(formato.ayuda())


async def anotar(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    """Cualquier mensaje de texto que no sea un comando es un apunte.

    Si el texto nombra a un cliente y no hay duda de cuál es, queda colgado
    de él sin preguntar. Si hay dos con ese nombre, se pregunta con botones:
    colgarlo de la Ana equivocada sería peor que dejarlo suelto.
    """
    with sesion() as db:
        try:
            anotado = anotar_apunte(
                db, update.effective_user.id, update.message.text, origen="bot"
            )
        except TextoNoInterpretable as exc:
            await update.message.reply_text(f"No te he entendido: {exc}\n\n{formato.ayuda()}")
            return

        apunte = anotado.apunte
        if apunte.cliente is not None:
            await update.message.reply_text(
                formato.apunte_creado_con_cliente(apunte, apunte.cliente)
            )
            return

        if not anotado.candidatos:
            await update.message.reply_text(formato.apunte_creado(apunte))
            return

        botones = [
            [
                InlineKeyboardButton(
                    formato.descripcion_corta(c), callback_data=f"cli:{apunte.id}:{c.id}"
                )
            ]
            for c in anotado.candidatos
        ]
        botones.append(
            [InlineKeyboardButton("Ninguno", callback_data=f"cli:{apunte.id}:0")]
        )
        await update.message.reply_text(
            f"{formato.apunte_creado(apunte)}\n\n"
            f"{formato.preguntar_cliente(anotado.candidatos[0].nombre.split()[0])}",
            reply_markup=InlineKeyboardMarkup(botones),
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
