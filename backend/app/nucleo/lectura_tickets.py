"""Pedirle a un modelo con visión que lea un ticket. No sabe qué es un gasto.

Está en `nucleo/` por lo mismo que `transcripcion.py`: es una conexión a un
servicio de fuera. Devuelve el JSON tal cual lo contesta el modelo; qué se
acepta de él lo decide `dominio/tickets.py`, que se puede probar sin red.

Asíncrono porque la API y el bot comparten proceso: tardar tres segundos en
bloqueante dejaría la web colgada mientras se lee una foto.
"""
import base64
import json

import httpx

from app.nucleo.config import MODELO_TICKETS, OPENAI_API_KEY

_URL = "https://api.openai.com/v1/chat/completions"

_INSTRUCCIONES = (
    "Eres un lector de tickets y facturas españoles. Mira la imagen y "
    "responde SOLO un objeto JSON con estas claves:\n"
    '- "total": importe TOTAL pagado, IVA incluido, como número con punto '
    "decimal (ej. 23.40). Si hay varios totales, el final que se pagó.\n"
    '- "fecha": fecha del ticket en formato YYYY-MM-DD.\n'
    '- "comercio": nombre de la tienda o empresa que emite el ticket, corto.\n'
    '- "iva": cuota total de IVA en euros como número, si aparece.\n'
    '- "concepto": de 2 a 5 palabras sobre qué se compró (ej. "tornillería y '
    'silicona", "gasolina").\n'
    "Usa null en cualquier clave que no se lea con seguridad. No inventes: un "
    "null es mejor que un número dudoso. Si la imagen no es un ticket ni una "
    'factura, responde {"total": null}.'
)


class LecturaNoDisponible(RuntimeError):
    """Falta la clave: no es un fallo pasajero, hay que configurar el entorno."""


class ErrorDeLectura(RuntimeError):
    """El servicio no pudo leer esta imagen (red, cuota, respuesta rara)."""


def hay_lectura() -> bool:
    return bool(OPENAI_API_KEY)


async def leer_ticket(imagen: bytes, mime: str) -> dict:
    if not OPENAI_API_KEY:
        raise LecturaNoDisponible("falta OPENAI_API_KEY en el entorno")
    if not imagen:
        raise ErrorDeLectura("la imagen llegó vacía")
    if not mime.startswith("image/"):
        raise ErrorDeLectura("solo sé leer fotos (JPG, PNG, WEBP)")

    url_datos = f"data:{mime};base64,{base64.b64encode(imagen).decode()}"
    cuerpo = {
        "model": MODELO_TICKETS,
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "messages": [
            {"role": "system", "content": _INSTRUCCIONES},
            {
                "role": "user",
                "content": [{"type": "image_url", "image_url": {"url": url_datos}}],
            },
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=60) as cliente:
            respuesta = await cliente.post(
                _URL, headers={"Authorization": f"Bearer {OPENAI_API_KEY}"}, json=cuerpo
            )
    except httpx.HTTPError as exc:
        raise ErrorDeLectura(f"no se pudo llamar al servicio: {exc}") from exc

    if respuesta.status_code != 200:
        raise ErrorDeLectura(
            f"el servicio respondió {respuesta.status_code}: {respuesta.text[:200]}"
        )

    try:
        contenido = respuesta.json()["choices"][0]["message"]["content"]
        datos = json.loads(contenido)
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise ErrorDeLectura("el servicio devolvió algo que no es JSON") from exc
    if not isinstance(datos, dict):
        raise ErrorDeLectura("el servicio devolvió algo que no es un objeto")
    return datos
