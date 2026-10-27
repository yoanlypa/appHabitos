"""Dónde se guardan las imágenes de las facturas, en disco. Nada de negocio.

Existe por la misma lección que `almacenamiento.py`: en Railway, lo que no
está en el volumen se borra en el siguiente despliegue. Por eso, si no se
dice otra cosa con `RUTA_FACTURAS`, las imágenes van a una carpeta junto a
la base SQLite — que ya se comprueba que está en `/data`.

Las imágenes van en disco y no dentro de la base: un ticket son 200-400 KB,
y meter cientos en SQLite haría la copia de seguridad y cada consulta más
pesadas sin ganar nada.
"""
import os
import uuid
from pathlib import Path

from sqlalchemy.engine import make_url

from app.nucleo.config import DATABASE_URL, RUTA_FACTURAS

EXTENSIONES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "application/pdf": "pdf",
}
# Una foto de móvil sin comprimir ronda los 4-8 MB; la web la reduce antes
# de subirla, pero lo que llega por Telegram como documento puede ser mayor.
TAMANO_MAXIMO = 15 * 1024 * 1024


def carpeta() -> Path:
    if RUTA_FACTURAS:
        return Path(RUTA_FACTURAS)
    url = make_url(DATABASE_URL)
    if url.get_backend_name().startswith("sqlite") and url.database:
        return Path(url.database).resolve().parent / "facturas"
    return Path("facturas").resolve()


def guardar(datos: bytes, mime: str) -> str:
    """Guarda la imagen y devuelve su ruta relativa a la carpeta (la que va a la base).

    Relativa a propósito: si un día se mueve la carpeta, las filas siguen
    valiendo cambiando solo `RUTA_FACTURAS`.
    """
    extension = EXTENSIONES.get(mime, "bin")
    relativa = f"{uuid.uuid4().hex}.{extension}"
    destino = carpeta() / relativa
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(datos)
    return relativa


def ruta_absoluta(relativa: str) -> Path:
    return carpeta() / relativa


def borrar(relativa: str) -> None:
    """Borra el fichero si existe. Que ya no esté no es un error: el fin es el mismo."""
    try:
        os.remove(ruta_absoluta(relativa))
    except FileNotFoundError:
        pass
