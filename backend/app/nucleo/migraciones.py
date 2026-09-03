"""Pone la base de datos al día al arrancar.

Antes se usaba `create_all()`, que crea las tablas que faltan pero **no**
toca las que ya existen: añadir una columna no llegaba nunca a producción.
Ahora manda Alembic.

El caso delicado son las bases creadas antes de todo esto (la de local y la
de Railway): tienen las tablas pero no la marca de versión, así que primero
se les pone la marca del esquema inicial y luego se aplican las migraciones
siguientes. Sin eso, Alembic intentaría crear tablas que ya están y fallaría.
"""
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.nucleo.db import engine

log = logging.getLogger(__name__)

# Esquema que existía antes de que hubiera migraciones.
REVISION_INICIAL = "505ff48a1983"

_RAIZ = Path(__file__).resolve().parents[2]


def _configuracion() -> Config:
    cfg = Config(str(_RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(_RAIZ / "alembic"))
    return cfg


def migrar() -> None:
    cfg = _configuracion()
    tablas = inspect(engine).get_table_names()

    if "apuntes" in tablas and "alembic_version" not in tablas:
        log.info("base anterior a Alembic: se marca como %s", REVISION_INICIAL)
        command.stamp(cfg, REVISION_INICIAL)

    command.upgrade(cfg, "head")
    log.info("base de datos al día")
