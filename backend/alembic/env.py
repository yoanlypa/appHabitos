"""Alembic conectado a la configuración de la app.

La URL no se escribe en alembic.ini: se lee de `nucleo/config.py`, que es
quien sabe del entorno. Así una migración en local y otra en Railway usan
cada una su base sin tocar ficheros.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.types import TypeDecorator

from app.nucleo.config import DATABASE_URL
from app.nucleo.db import Base

# Importar los modelos registra las tablas en Base.metadata, que es de donde
# autogenerate saca los cambios.
import app.dominio.models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def render_item(tipo, obj, autogen_context):
    """Escribe los tipos propios como el tipo real que guardan.

    `Centimos` es nuestro y vive en `dominio/models.py`; si Alembic lo
    escribiera tal cual, la migración tendría que importar la aplicación
    para poder ejecutarse. Como por debajo es un INTEGER, se escribe así.
    """
    if tipo == "type" and isinstance(obj, TypeDecorator):
        # `impl` puede ser la clase (Integer) o ya una instancia, según cómo
        # se declarase el decorador.
        impl = obj.impl if isinstance(obj.impl, type) else type(obj.impl)
        return f"sa.{impl.__name__}()"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite no sabe hacer ALTER de casi nada: batch mode recrea la
            # tabla por detrás. Sin esto, cualquier cambio de columna falla.
            render_as_batch=True,
            render_item=render_item,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
