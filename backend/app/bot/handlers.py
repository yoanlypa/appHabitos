"""Handlers de Telegram: parsean la entrada, llaman a un servicio y formatean.

Nada más que eso. La misma lógica que usa la API vive en `servicios/`, así
que el bot no calcula ni decide: solo traduce entre Telegram y los casos de
uso.

Los servicios son síncronos (SQLAlchemy) y los handlers async: para un bot
personal contra SQLite la consulta dura milisegundos, así que no compensa
sacarla a un hilo.
"""
from datetime import timedelta

from telegram import Update
from telegram.ext import ContextTypes

from app.bot import formato
from app.dominio.parsing import TextoNoInterpretable
from app.dominio.parsing_citas import CitaNoInterpretable, interpretar_cita
from app.nucleo.db import sesion
from app.nucleo.tiempo import hoy_local
from app.servicios.agenda import citas_del_dia, crear_cita
from app.servicios.apuntes import ApunteNoEncontrado, crear_apunte, marcar_cobrado
from app.servicios.auth import generar_token
from app.servicios.avisos import activar_avisos, avisos_activos
from app.servicios.clientes import pendientes_de_cobro
from app.servicios.resumen import resumen_dia, resumen_mes


async def start(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(formato.ayuda())


async def anotar(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    """Cualquier mensaje de texto que no sea un comando es un apunte."""
    with sesion() as db:
        try:
            apunte = crear_apunte(
                db, update.effective_user.id, update.message.text, origen="bot"
            )
        except TextoNoInterpretable as exc:
            await update.message.reply_text(f"No te he entendido: {exc}\n\n{formato.ayuda()}")
            return
        await update.message.reply_text(formato.apunte_creado(apunte))


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
