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

# Transcripción de las notas de voz del bot. Sin clave, el bot lo dice y no
# se pierde nada: el audio sigue estando en el chat de Telegram.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
MODELO_TRANSCRIPCION = os.getenv("MODELO_TRANSCRIPCION", "gpt-4o-mini-transcribe")
# Decírselo evita que una nota corta en español salga transcrita en otro
# idioma, que es el fallo típico de estos modelos con dos palabras sueltas.
IDIOMA_VOZ = os.getenv("IDIOMA_VOZ", "es")

# Ids de Telegram a los que avisar al arrancar si la base no se está
# guardando, separados por comas. No se pueden sacar de la base: justo cuando
# falla, está recién creada y no sabe quién la usa.
ALARMA_TELEGRAM_IDS = [
    int(trozo)
    for trozo in os.getenv("ALARMA_TELEGRAM_IDS", "").replace(" ", "").split(",")
    if trozo.isdigit()
]

# Desde qué webs se puede llamar a la API. En local, el servidor de Vite;
# en Railway, la URL del front. Separados por comas.
CORS_ORIGENES = [
    origen.strip()
    for origen in os.getenv("CORS_ORIGENES", "http://localhost:5173").split(",")
    if origen.strip()
]

# Lectura de tickets y facturas escaneados. Usa la misma OPENAI_API_KEY que
# la voz: un modelo con visión lee el total, la fecha y el comercio de la
# foto por menos de un céntimo, y acierta mucho más que un OCR clásico con
# un ticket arrugado o fotografiado de lado.
MODELO_TICKETS = os.getenv("MODELO_TICKETS", "gpt-4o-mini")
# Dónde se guardan las imágenes. Vacío = junto a la base SQLite (en Railway,
# dentro del volumen /data), que es justo donde tienen que estar para no
# perderse en un redespliegue.
RUTA_FACTURAS = os.getenv("RUTA_FACTURAS", "")
