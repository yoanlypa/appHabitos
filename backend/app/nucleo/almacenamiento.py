"""¿Dónde está escribiendo la base de datos y va a sobrevivir al próximo despliegue?

Existe por un fallo real: en Railway el contenedor se destruye en cada
redespliegue, así que una base SQLite guardada dentro de él desaparece con
todo lo apuntado. Y no avisa: la app arranca igual, sólo que vacía.

Esto lo detecta y lo dice en voz alta — en el log al arrancar y en `/salud`.
"""
import logging
import ntpath
import os
import posixpath
from dataclasses import dataclass

from sqlalchemy.engine import make_url

from app.nucleo.config import DATABASE_URL

log = logging.getLogger(__name__)

# Punto de montaje del volumen en Railway. Lo que caiga fuera de aquí se
# borra en el siguiente despliegue.
MONTAJE = os.getenv("RUTA_DATOS", "/data")


@dataclass
class EstadoAlmacenamiento:
    motor: str
    ruta: str | None
    persistente: bool
    existe: bool
    tamano_bytes: int | None
    aviso: str | None


def estado() -> EstadoAlmacenamiento:
    url = make_url(DATABASE_URL)
    motor = url.get_backend_name()

    if not motor.startswith("sqlite"):
        # Postgres y compañía viven fuera del contenedor: siempre persisten.
        return EstadoAlmacenamiento(
            motor=motor, ruta=None, persistente=True, existe=True,
            tamano_bytes=None, aviso=None,
        )

    ruta = url.database or ""
    # El razonamiento sobre /data es de Linux, que es donde corre esto en
    # Railway; os.path daría otra respuesta al desarrollar en Windows.
    absoluta = posixpath.isabs(ruta) or ntpath.isabs(ruta)
    dentro_del_volumen = posixpath.isabs(ruta) and (
        ruta == MONTAJE or ruta.startswith(MONTAJE.rstrip("/") + "/")
    )
    existe = os.path.exists(ruta) if ruta else False
    tamano = os.path.getsize(ruta) if existe else None

    aviso = None
    if not absoluta:
        aviso = (
            f"La base está en una ruta relativa ({ruta!r}), o sea dentro del "
            f"contenedor: se borrará en el próximo despliegue. En Railway hay "
            f"que montar un volumen en {MONTAJE} y poner "
            f"DATABASE_URL=sqlite:////data/parte_del_dia.db (cuatro barras)."
        )
    elif not dentro_del_volumen:
        aviso = (
            f"La base está en {ruta}, fuera del volumen ({MONTAJE}): se "
            f"perderá en el próximo despliegue."
        )
    elif not os.path.isdir(MONTAJE):
        aviso = (
            f"DATABASE_URL apunta a {MONTAJE} pero ese directorio no existe: "
            f"falta montar el volumen en Railway."
        )

    return EstadoAlmacenamiento(
        motor=motor,
        ruta=ruta,
        persistente=aviso is None,
        existe=existe,
        tamano_bytes=tamano,
        aviso=aviso,
    )


def avisar_si_es_efimera() -> None:
    """Deja constancia en el log al arrancar. Se llama antes de migrar."""
    actual = estado()
    if actual.aviso:
        log.error("LOS DATOS NO SE VAN A GUARDAR: %s", actual.aviso)
    else:
        log.info("Base de datos en %s (persistente)", actual.ruta or actual.motor)
