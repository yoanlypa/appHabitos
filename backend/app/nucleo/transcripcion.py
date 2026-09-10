"""Pasar un audio a texto. No sabe qué es un apunte ni quién le habla.

Está en `nucleo/` por la misma razón que `db.py`: es una conexión a algo de
fuera, no una regla de negocio. Lo que se hace con el texto se decide en
`servicios/`.

Es asíncrono a propósito. La API y el bot comparten proceso en producción,
así que una llamada de varios segundos hecha en bloqueante dejaría la web
sin responder mientras se transcribe una nota de voz.
"""
import httpx

from app.nucleo.config import IDIOMA_VOZ, MODELO_TRANSCRIPCION, OPENAI_API_KEY

_URL = "https://api.openai.com/v1/audio/transcriptions"
# Una nota de voz de un minuto son unos 100 KB; el margen es para las largas.
# Telegram tampoco deja descargar ficheros de más de 20 MB con getFile.
TAMANO_MAXIMO = 20 * 1024 * 1024


class TranscripcionNoDisponible(RuntimeError):
    """Falta la clave: no es un fallo pasajero, hay que configurar el entorno."""


class ErrorDeTranscripcion(RuntimeError):
    """El servicio no pudo transcribir este audio (red, cuota, formato)."""


def hay_transcripcion() -> bool:
    return bool(OPENAI_API_KEY)


async def transcribir(audio: bytes, nombre: str = "nota.ogg") -> str:
    """Devuelve lo que se dice en el audio, o levanta si no se ha podido.

    El nombre del fichero importa: el servicio deduce el formato de la
    extensión, y el de las notas de voz de Telegram es OGG/Opus, que se
    manda tal cual sin convertir nada.
    """
    if not OPENAI_API_KEY:
        raise TranscripcionNoDisponible("falta OPENAI_API_KEY en el entorno")
    if not audio:
        raise ErrorDeTranscripcion("el audio llegó vacío")
    if len(audio) > TAMANO_MAXIMO:
        raise ErrorDeTranscripcion("el audio es demasiado largo")

    datos = {"model": MODELO_TRANSCRIPCION, "response_format": "text"}
    if IDIOMA_VOZ:
        datos["language"] = IDIOMA_VOZ

    try:
        async with httpx.AsyncClient(timeout=90) as cliente:
            respuesta = await cliente.post(
                _URL,
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                data=datos,
                files={"file": (nombre, audio, "application/octet-stream")},
            )
    except httpx.HTTPError as exc:
        raise ErrorDeTranscripcion(f"no se pudo llamar al servicio: {exc}") from exc

    if respuesta.status_code != 200:
        # El cuerpo trae el motivo real (cuota agotada, clave revocada,
        # formato no admitido) y sin él no hay forma de saber qué arreglar.
        raise ErrorDeTranscripcion(
            f"el servicio respondió {respuesta.status_code}: {respuesta.text[:200]}"
        )

    return respuesta.text.strip()
