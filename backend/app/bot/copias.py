"""La copia de seguridad: todo, en un ZIP, por Telegram.

Existe por algo que ya pasó: la base vivía dentro del contenedor y Railway
lo destruye en cada despliegue, así que los apuntes desaparecieron sin que
nadie se enterara hasta abrir la app y verla vacía.

El sitio más seguro para estos datos no es el servidor: es el Telegram de
quien los apuntó, que se sincroniza solo entre sus dispositivos y no
depende de que un volumen esté bien configurado.

Va todo (apuntes, clientes, trabajos, citas, hábitos y Casa) en un ZIP que
lleva dentro también el CSV de los apuntes para abrirlo con Excel. Qué lleva
y cómo se restaura: `servicios/copia_completa.py`.
"""
import logging
from io import BytesIO

from telegram.error import TelegramError
from telegram.ext import Application, ContextTypes

from app.nucleo.db import sesion
from app.nucleo.tiempo import hora_del_aviso, hoy_local
from app.servicios.copia_completa import generar, usuarios_con_datos

log = logging.getLogger(__name__)

# Domingo. `run_daily` usa la convención de Python: 0 es lunes.
DOMINGO = (6,)


def _fichero(datos: bytes, user_id: int) -> BytesIO:
    fichero = BytesIO(datos)
    fichero.name = f"parte-del-dia-{user_id}-{hoy_local().isoformat()}.zip"
    return fichero


def _plural(n: int, uno: str, varios: str) -> str:
    return f"{n} {uno if n == 1 else varios}"


def descripcion(cuenta: dict[str, int]) -> str:
    """'120 apuntes, 8 trabajos y 15 clientes': lo que lleva, sin los ceros."""
    nombres = {
        "apuntes": ("apunte", "apuntes"),
        "trabajos": ("trabajo", "trabajos"),
        "clientes": ("cliente", "clientes"),
        "citas": ("cita", "citas"),
        "habitos": ("hábito", "hábitos"),
        "gastos_casa": ("gasto de Casa", "gastos de Casa"),
        "compra": ("cosa de la compra", "cosas de la compra"),
    }
    partes = [_plural(cuenta[k], *nombres[k]) for k in nombres if cuenta.get(k)]
    if len(partes) <= 1:
        return "".join(partes)
    return ", ".join(partes[:-1]) + " y " + partes[-1]


async def enviar_copia(contexto: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    with sesion() as db:
        copia = generar(db, user_id)
    if copia is None:
        return False
    datos, cuenta = copia

    try:
        await contexto.bot.send_document(
            chat_id=user_id,
            document=_fichero(datos, user_id),
            caption=(
                f"Copia de seguridad: {descripcion(cuenta)}. Guárdala: si algún día "
                "pierdes datos, reenvíamela y vuelvo a meter lo que falte. "
                "Dentro va también el CSV de los apuntes para abrirlo con Excel."
            ),
        )
        return True
    except TelegramError:
        log.warning("No se pudo enviar la copia a %s", user_id, exc_info=True)
        return False


async def copia_semanal(contexto: ContextTypes.DEFAULT_TYPE) -> None:
    """A todo el que tenga algo guardado, una vez por semana.

    No solo a quien recibe el aviso de esa noche, como antes: un domingo sin
    apuntar era una semana sin copia. Tampoco se calla con `/avisos off`: no
    es un recordatorio, es lo que salva los datos el día que se pierden.
    """
    with sesion() as db:
        usuarios = usuarios_con_datos(db)

    for user_id in usuarios:
        await enviar_copia(contexto, user_id)


def programar(app: Application) -> None:
    app.job_queue.run_daily(
        copia_semanal, time=hora_del_aviso(), days=DOMINGO, name="copia_semanal"
    )
