"""Caso de uso de las notas de voz: se dictan y quedan anotadas.

Transcribir y anotar van juntos aquí, y no en el bot, por la regla de
siempre: el día que la web mande audios tiene que pasar exactamente lo
mismo. El bot solo baja el fichero de Telegram y pinta la respuesta.

Es asíncrono porque la transcripción tarda segundos y el proceso es el
mismo que sirve la API. Lo de la base de datos sigue siendo síncrono: son
milisegundos contra SQLite.
"""
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.nucleo.transcripcion import transcribir
from app.servicios.apuntes import ApunteAnotado, anotar


@dataclass
class VozAnotada:
    """Lo anotado y lo que se entendió al escuchar.

    El texto se devuelve siempre para poder enseñarlo: si el transcriptor
    oyó "120" donde se dijo "20", hay que verlo en el momento y no al
    cuadrar el mes.
    """

    texto: str
    anotado: ApunteAnotado

    @property
    def apunte(self):
        return self.anotado.apunte

    @property
    def candidatos(self) -> list:
        return self.anotado.candidatos


class NadaQueAnotar(ValueError):
    """El audio se transcribió pero no dice nada aprovechable."""


async def anotar_audio(
    db: Session, user_id: int, audio: bytes, nombre: str, origen: str
) -> VozAnotada:
    texto = await transcribir(audio, nombre)
    if not texto.strip():
        raise NadaQueAnotar("no se ha entendido nada en el audio")
    # admite_nota: lo dictado no se rechaza nunca. Quien escribe puede
    # corregir la frase; quien habla ya la ha dicho.
    return VozAnotada(texto=texto, anotado=anotar(db, user_id, texto, origen, admite_nota=True))
