"""/banco: conectar la cuenta del banco y ver qué llega.

Sin conexión, da el botón para dar permiso en el banco (se confirma en su
app y se vuelve a `/banco/vuelta`). Con conexión, enseña las cuentas que se
ven, cuánto le queda al permiso y los últimos movimientos, y un botón para
volver a conectar. Todo lo decide `servicios/banco.py`.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes

from app.bot import formato
from app.nucleo import banco as enable
from app.nucleo.db import sesion
from app.servicios import banco as servicio


async def banco(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    reconectar = (contexto.args or [""])[0].lower() in ("conectar", "renovar", "otra")
    await update.message.chat.send_action(ChatAction.TYPING)
    with sesion() as db:
        try:
            if not reconectar:
                resumen = await servicio.ver(db, user_id)
                if resumen is not None:
                    await update.message.reply_text(
                        formato.resumen_banco(resumen)
                        + "\n\nPara volver a dar permiso: /banco renovar"
                    )
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


def registrar(app: Application) -> None:
    app.add_handler(CommandHandler("banco", banco))
