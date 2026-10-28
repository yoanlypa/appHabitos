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
    "responde SOLO un objeto JSON con estas claves (null en lo que no se lea "
    "con seguridad: un null es mejor que un dato inventado):\n"
    '- "total": lo que de verdad costó la compra, IVA incluido, número con punto '
    'decimal. OJO en gasolineras y pagos en efectivo: si pone "total cobrado" o '
    '"entregado" y luego "total suministrado", "cambio" o "a devolver", el '
    'total es lo SUMINISTRADO/consumido, no lo entregado.\n'
    '- "fecha": fecha del ticket, YYYY-MM-DD. "hora": HH:MM.\n'
    '- "comercio": nombre corto de la tienda. "razon_social": nombre legal '
    'completo (p. ej. "LEROY MERLIN MALAGA S.L.U."). "cif": CIF/NIF del '
    'emisor. "direccion": dirección del emisor.\n'
    '- "numero": número de factura o de ticket.\n'
    '- "lineas": lista de lo comprado, cada una {"descripcion", "cantidad", '
    '"precio_unitario", "importe"} con números con punto decimal.\n'
    '- "base_imponible": total sin IVA. "iva": cuota total de IVA en euros. '
    '"tipos_iva": lista de {"tipo", "base", "cuota"} (tipo en %, p. ej. 21).\n'
    '- "descuento": total de descuentos en euros, positivo.\n'
    '- "forma_pago": tarjeta, efectivo, bizum...\n'
    '- "documento": "gasto" si es una compra; "devolucion" solo si es un abono '
    'de una compra anterior (importes negativos, "abono", "factura '
    'rectificativa"). Un "cheque devolución" o "a devolver" por pagar con un '
    'billete grande es el CAMBIO, no una devolución: eso es "gasto".\n'
    '- "concepto": de 2 a 5 palabras sobre qué se compró (ej. "tacos de '
    'expansión", "gasolina").\n'
    '- "esquinas": las 4 esquinas del papel del ticket en la foto, como '
    "[[x, y], ...] con x e y entre 0 y 1 (fracción del ancho y del alto de la "
    "imagen, 0,0 arriba a la izquierda), en orden: arriba-izquierda, "
    "arriba-derecha, abajo-derecha, abajo-izquierda. Si una esquina se sale "
    "de la foto, pon el punto en el borde de la imagen.\n"
    'Si la imagen no es un ticket ni una factura, responde {"total": null}.'
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
        # Con las líneas de producto la respuesta crece; el tope evita que un
        # ticket de supermercado larguísimo dispare el coste.
        "max_tokens": 2500,
        "messages": [
            {"role": "system", "content": _INSTRUCCIONES},
            {
                "role": "user",
                "content": [{"type": "image_url", "image_url": {"url": url_datos, "detail": "high"}}],
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
