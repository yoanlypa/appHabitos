"""Preparación común de los tests.

La base de datos se apunta a un fichero temporal **antes** de importar nada
de la aplicación: `nucleo/db.py` crea el motor al importarse, así que si se
hiciera después ya estaría mirando a la base de verdad.
"""
import os
import tempfile

_TEMPORAL = tempfile.mkdtemp(prefix="parte-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TEMPORAL}/pruebas.db".replace(os.sep, "/")
os.environ.setdefault("TZ_LOCAL", "Europe/Madrid")

import pytest  # noqa: E402

from app.dominio.models import Ajuste, Apunte, Cita, Cliente, TokenAcceso  # noqa: E402
from app.nucleo.db import sesion  # noqa: E402
from app.nucleo.migraciones import migrar  # noqa: E402

USUARIO = 6529038645  # un id de Telegram real: no cabe en un INT de 32 bits


@pytest.fixture(scope="session", autouse=True)
def _base_de_datos():
    migrar()


@pytest.fixture
def db():
    """Una sesión limpia por test: lo que escriba uno no lo ve el siguiente."""
    with sesion() as s:
        yield s
        for modelo in (Apunte, Cita, Cliente, Ajuste, TokenAcceso):
            s.query(modelo).delete()
        s.commit()
