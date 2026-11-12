"""Casos de uso del aviso diario: quién lo quiere y qué se le cuenta.

Tres decisiones de negocio viven aquí, no en el bot:

1. Se avisa a quien tenga algo que contar: apuntes de hoy, o citas para
   mañana. Un recordatorio vacío cada noche es la mejor forma de que
   alguien silencie el bot.
2. El aviso lleva las citas de mañana además del dinero de hoy, porque el
   momento en que sirve saber a qué hora hay que estar en un sitio es la
   noche anterior, no la mañana siguiente con el coche arrancado.
3. El buzón de notas solo se cuenta, nunca dispara el aviso: una nota que
   lleva ahí tres semanas haría sonar el bot todas las noches para siempre,
   y eso es exactamente lo que hace que se silencie.
4. Los avisos están activos salvo que los apagues (y eso apaga también los
   recordatorios de hábitos y de citas: el interruptor es para todo). Así funcionan desde el
   primer día sin configurar nada, y `Ajuste` solo guarda fila para quien
   ha cambiado algo.
"""
import logging
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from sqlalchemy.orm import Session

from app.dominio.models import Ajuste, Apunte, Cita
from app.dominio.recordatorios import toca_avisar
from app.nucleo import correo as servicio_correo
from app.nucleo.config import AVISO_CITA_MINUTOS, AVISO_CITA_SIN_HORA
from app.nucleo.tiempo import hoy_local
from app.servicios.agenda import citas_del_dia
from app.servicios.notas import contar_notas
from app.servicios.resumen import ResumenPeriodo, resumen_dia


@dataclass
class AvisoDelDia:
    user_id: int
    resumen: ResumenPeriodo
    citas_manana: list[Cita]
    hubo_apuntes: bool
    notas_pendientes: int = 0


def avisos_activos(db: Session, user_id: int) -> bool:
    ajuste = db.query(Ajuste).filter(Ajuste.user_id == user_id).first()
    return True if ajuste is None else ajuste.avisos_activos


def _ajuste(db: Session, user_id: int) -> Ajuste:
    ajuste = db.query(Ajuste).filter(Ajuste.user_id == user_id).first()
    if ajuste is None:
        ajuste = Ajuste(user_id=user_id, avisos_activos=True)
        db.add(ajuste)
    return ajuste


def activar_avisos(db: Session, user_id: int, activos: bool) -> bool:
    _ajuste(db, user_id).avisos_activos = activos
    db.commit()
    return activos


def destinatarios_del_aviso(db: Session) -> list[AvisoDelDia]:
    """Quién debe recibir el aviso de esta noche, ya con su contenido."""
    hoy = hoy_local()
    manana = hoy + timedelta(days=1)

    # Las notas no cuentan como "hoy pasó algo": son apuntes, pero sin dinero.
    # Si contaran, apuntar un recordatorio dispararía el aviso de la noche con
    # un resumen de 0,00 €, que es exactamente el mensaje vacío que se evita.
    con_apuntes = {
        fila[0]
        for fila in db.query(Apunte.user_id)
        .filter(Apunte.fecha == hoy, Apunte.tipo != "nota")
        .distinct()
        .all()
    }
    con_citas = {
        fila[0]
        for fila in db.query(Cita.user_id)
        .filter(Cita.fecha == manana, Cita.hecha.is_(False))
        .distinct()
        .all()
    }
    apagados = {
        fila[0]
        for fila in db.query(Ajuste.user_id).filter(Ajuste.avisos_activos.is_(False)).all()
    }

    return [
        AvisoDelDia(
            user_id=user_id,
            resumen=resumen_dia(db, user_id, hoy),
            citas_manana=citas_del_dia(db, user_id, manana),
            hubo_apuntes=user_id in con_apuntes,
            notas_pendientes=contar_notas(db, user_id),
        )
        for user_id in sorted((con_apuntes | con_citas) - apagados)
    ]


# ---------- Correo ----------

log = logging.getLogger(__name__)

_RE_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CorreoNoValido(ValueError):
    """Lo escrito no parece una dirección de correo."""


def correo_de(db: Session, user_id: int) -> str | None:
    ajuste = db.query(Ajuste).filter(Ajuste.user_id == user_id).first()
    return ajuste.correo if ajuste else None


def guardar_correo(db: Session, user_id: int, correo: str | None) -> str | None:
    """Guarda a dónde mandar los avisos por correo. Vacío o None lo quita."""
    limpio = (correo or "").strip().lower() or None
    if limpio is not None and not _RE_CORREO.match(limpio):
        raise CorreoNoValido(f"«{correo}» no parece una dirección de correo")
    _ajuste(db, user_id).correo = limpio
    db.commit()
    return limpio


def correo_disponible() -> bool:
    """Si el servidor sabe mandar correos (está la clave de Resend)."""
    return servicio_correo.hay_correo()


async def mandar_correo(db: Session, user_id: int, asunto: str, texto: str) -> bool:
    """Lo manda si ese usuario tiene correo y el servidor sabe mandar. Nunca levanta.

    Un correo que no sale no puede tirar el recordatorio de Telegram, que va
    por otro lado: se apunta en el log y se sigue.
    """
    para = correo_de(db, user_id)
    if not para or not servicio_correo.hay_correo():
        return False
    try:
        await servicio_correo.enviar_correo(para, asunto, texto)
    except servicio_correo.ErrorDeCorreo:
        log.warning("No se pudo mandar el correo a %s", user_id, exc_info=True)
        return False
    return True


async def probar_correo(db: Session, user_id: int) -> str:
    """Manda un correo de prueba y devuelve a dónde. Levanta con el motivo si no puede.

    Es lo que se usa al configurarlo: aquí sí interesa el error tal cual,
    porque es justo lo que hay que arreglar (la clave, o que Resend solo deja
    mandar a la dirección de la cuenta).
    """
    para = correo_de(db, user_id)
    if not para:
        raise CorreoNoValido("todavía no has puesto a qué correo avisarte")
    await servicio_correo.enviar_correo(
        para,
        "Parte del día: correo de prueba",
        "Si lees esto, los avisos de tus citas también te llegarán por correo.\n",
    )
    return para


# ---------- Recordatorio de citas el mismo día ----------


def _hora(texto: str) -> time:
    horas, minutos = texto.split(":")
    return time(int(horas), int(minutos))


def citas_por_recordar(db: Session, ahora: datetime) -> list[Cita]:
    """Las citas de hoy a las que toca recordar ahora mismo.

    La regla de cuándo está en `dominio/recordatorios.py`. Aquí se añade lo
    que depende de la base: no a quien apagó los avisos con /avisos off.
    `ahora` en hora local.
    """
    en_punto = ahora.replace(tzinfo=None)
    hoy = en_punto.date()
    antelacion = timedelta(minutes=AVISO_CITA_MINUTOS)
    sin_hora = _hora(AVISO_CITA_SIN_HORA)
    candidatas = (
        db.query(Cita).filter(Cita.fecha == hoy, Cita.hecha.is_(False)).order_by(Cita.hora).all()
    )
    activos: dict[int, bool] = {}
    debidas = []
    for cita in candidatas:
        if not toca_avisar(en_punto, cita.fecha, cita.hora, cita.hecha, cita.avisada_el, antelacion, sin_hora):
            continue
        if cita.user_id not in activos:
            activos[cita.user_id] = avisos_activos(db, cita.user_id)
        if activos[cita.user_id]:
            debidas.append(cita)
    return debidas


def marcar_avisada(db: Session, cita: Cita) -> None:
    cita.avisada_el = cita.fecha
    db.commit()
