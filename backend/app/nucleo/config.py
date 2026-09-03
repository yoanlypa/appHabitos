"""Configuración de la app: variables de entorno y sus valores por defecto.

No sabe que existe un negocio, solo lee configuración y la deja lista para
que `dominio/` y `servicios/` la usen.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def _normalizar_database_url(url: str) -> str:
    # Railway da a veces "postgres://", pero SQLAlchemy 2.x exige "postgresql://"
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


DATABASE_URL = _normalizar_database_url(
    os.getenv("DATABASE_URL", "sqlite:///./parte_del_dia.db")
)
TZ_LOCAL = os.getenv("TZ_LOCAL", "Europe/Madrid")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
HORA_AVISO = os.getenv("HORA_AVISO", "21:00")  # "HH:MM", hora local
