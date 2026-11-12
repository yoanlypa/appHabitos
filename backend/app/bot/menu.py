"""El menú: los comandos que Telegram enseña al escribir "/" y el teclado de abajo.

Sin esto, el bot solo sabía lo que uno recordara teclear. Dos piezas:

- **La lista de comandos** (`publicar_comandos`): se registra en Telegram al
  arrancar y sale en el botón de menú y al escribir "/". Solo los de cada
  día; los de arreglar cosas (/releer, /reparar) siguen en /start.
- **El teclado fijo** (`TECLADO`): seis botones bajo la caja de escribir con
  lo que se mira a diario. Un botón de este teclado manda su propio texto
  como mensaje, así que `tocado` los reconoce por la etiqueta exacta y los
  demás textos siguen siendo apuntes.

Si Telegram no deja publicar los comandos (sin red al arrancar), el bot
arranca igual: un menú que falta no puede tumbar lo que apunta el dinero.
"""
import logging

from telegram import BotCommand, ReplyKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from app.bot import formato, handlers

_log = logging.getLogger(__name__)

COMANDOS = [
    ("hoy", "Resumen y apuntes de hoy"),
    ("mes", "Resumen del mes"),
    ("deben", "Quién te debe dinero"),
    ("agenda", "Citas de hoy"),
    ("manana", "Citas de mañana"),
    ("notas", "Notas pendientes"),
    ("habitos", "Hábitos de hoy"),
    ("trimestre", "Lo que llevas este trimestre"),
    ("facturas", "Tickets del mes en PDF"),
    ("web", "Abrir la web"),
    ("correo", "Avisos de citas también por correo"),
    ("copia", "Copia de todo en CSV"),
    ("menu", "Sacar los botones de abajo"),
    ("start", "Ayuda: todo lo que entiendo"),
]

# Etiqueta del botón → lo que hace. Las etiquetas no pueden parecerse a un
# apunte: llevan su emoji delante y ninguna acaba en número.
_BOTONES = {
    "📊 Hoy": handlers.hoy,
    "📅 Mes": handlers.mes,
    "💰 Me deben": handlers.deben,
    "🗓 Agenda": handlers.agenda,
    "📝 Notas": handlers.notas,
    "🌐 Web": handlers.web,
}

TECLADO = ReplyKeyboardMarkup(
    [["📊 Hoy", "📅 Mes"], ["💰 Me deben", "🗓 Agenda"], ["📝 Notas", "🌐 Web"]],
    resize_keyboard=True,
    is_persistent=True,
    input_field_placeholder="Cambio de grifo Ana 120 · -45 gasolina",
)


async def publicar_comandos(app: Application) -> None:
    try:
        await app.bot.set_my_commands([BotCommand(nombre, texto) for nombre, texto in COMANDOS])
    except TelegramError as exc:
        _log.warning("No se han podido publicar los comandos del bot: %s", exc)


async def start(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(formato.ayuda(), reply_markup=TECLADO)


async def menu(update: Update, _contexto: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Ahí tienes los botones. Para anotar, escríbeme como siempre.", reply_markup=TECLADO
    )


async def tocado(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
    await _BOTONES[update.message.text.strip()](update, contexto)


def registrar(app: Application) -> None:
    """Antes del handler que anota cualquier texto: si no, "📊 Hoy" sería una nota."""
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Text(list(_BOTONES)), tocado)
    )
