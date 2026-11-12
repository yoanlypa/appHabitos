"""Mandar un correo. No sabe qué es una cita ni a quién hay que avisar.

Por la API HTTPS de Resend y no por SMTP: Railway bloquea los puertos de
SMTP en el plan Hobby, así que con Gmail la conexión ni se abre.

Asíncrono por lo mismo que la voz: la API y el bot comparten proceso, y una
llamada lenta en bloqueante dejaría la web sin responder.
"""
import httpx

from app.nucleo.config import CORREO_REMITENTE, RESEND_API_KEY

_URL = "https://api.resend.com/emails"


class CorreoNoDisponible(RuntimeError):
    """Falta la clave: no es un fallo pasajero, hay que configurar el entorno."""


class ErrorDeCorreo(RuntimeError):
    """El servicio no aceptó el correo (red, clave, destinatario no permitido)."""


def hay_correo() -> bool:
    return bool(RESEND_API_KEY)


async def enviar_correo(para: str, asunto: str, texto: str) -> None:
    if not RESEND_API_KEY:
        raise CorreoNoDisponible("falta RESEND_API_KEY en el entorno")
    try:
        async with httpx.AsyncClient(timeout=20) as cliente:
            respuesta = await cliente.post(
                _URL,
                headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
                json={"from": CORREO_REMITENTE, "to": [para], "subject": asunto, "text": texto},
            )
    except httpx.HTTPError as exc:
        raise ErrorDeCorreo(f"no se pudo llamar al servicio de correo: {exc}") from exc
    if respuesta.status_code >= 300:
        # El cuerpo dice el motivo real (clave mala, destinatario no permitido
        # sin dominio verificado...) y sin él no hay forma de saber qué arreglar.
        raise ErrorDeCorreo(f"el servicio de correo respondió {respuesta.status_code}: {respuesta.text[:300]}")
