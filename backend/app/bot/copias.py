"""La copia de seguridad: el histórico entero, en CSV, por Telegram.

Existe por algo que ya pasó: la base vivía dentro del contenedor y Railway
lo destruye en cada despliegue, así que los apuntes desaparecieron sin que
nadie se enterara hasta abrir la app y verla vacía.

El sitio más seguro para estos datos no es el servidor: es el Telegram de
quien los apuntó, que se sincroniza solo entre sus dispositivos y no
depende de que un volumen esté bien configurado.
"""
import logging
from io import BytesIO

from telegram.error import TelegramError
from telegram.ext import Application, ContextTypes

from app.nucleo.db import sesion
from app.nucleo.tiempo import hora_del_aviso, hoy_local
from app.servicios.avisos import destinatarios_del_aviso
from app.servicios.export import exportar_todo

log = logging.getLogger(__name__)

# Domingo. `run_daily` usa la convención de Python: 0 es lunes.
DOMINGO = (6,)


def _fichero(csv: str, user_id: int) -> BytesIO:
    # utf-8-sig para que Excel abra las tildes bien; sin BOM sale "Reforma baÃ±o".
    datos = BytesIO(csv.encode("utf-8-sig"))
    datos.name = f"parte-del-dia-{user_id}-{hoy_local().isoformat()}.csv"
    return datos


async def enviar_copia(contexto: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    with sesion() as db:
        csv = exportar_todo(db, user_id)

    lineas = csv.strip().count("\n")  # la cabecera no cuenta como apunte
    if lineas < 1:
        return False

    try:
        await contexto.bot.send_document(
            chat_id=user_id,
            document=_fichero(csv, user_id),
            caption=(
                f"Copia de seguridad: {lineas} apuntes. Guárdala: si algún día "
                "pierdes datos, reenvíamela y vuelvo a meter lo que falte."
            ),
        )
        return True
    except TelegramError:
        log.warning("No se pudo enviar la copia a %s", user_id, exc_info=True)
        return False


async def copia_semanal(contexto: ContextTypes.DEFAULT_TYPE) -> None:
    """A quien use la app se le manda su histórico una vez por semana."""
    with sesion() as db:
        usuarios = [aviso.user_id for aviso in destinatarios_del_aviso(db)]

    for user_id in usuarios:
        await enviar_copia(contexto, user_id)


def programar(app: Application) -> None:
    app.job_queue.run_daily(
        copia_semanal, time=hora_del_aviso(), days=DOMINGO, name="copia_semanal"
    )
