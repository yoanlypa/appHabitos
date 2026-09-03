"""Casos de uso del aviso diario: quién lo quiere y qué se le cuenta.

Tres decisiones de negocio viven aquí, no en el bot:

1. Se avisa a quien tenga algo que contar: apuntes de hoy, o citas para
   mañana. Un recordatorio vacío cada noche es la mejor forma de que
   alguien silencie el bot.
2. El aviso lleva las citas de mañana además del dinero de hoy, porque el
   momento en que sirve saber a qué hora hay que estar en un sitio es la
   noche anterior, no la mañana siguiente con el coche arrancado.
3. Los avisos están activos salvo que los apagues. Así funcionan desde el
   primer día sin configurar nada, y `Ajuste` solo guarda fila para quien
   ha cambiado algo.
"""
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.orm import Session

from app.dominio.models import Ajuste, Apunte, Cita
from app.nucleo.tiempo import hoy_local
from app.servicios.agenda import citas_del_dia
from app.servicios.resumen import ResumenPeriodo, resumen_dia


@dataclass
class AvisoDelDia:
    user_id: int
    resumen: ResumenPeriodo
    citas_manana: list[Cita]
    hubo_apuntes: bool


def avisos_activos(db: Session, user_id: int) -> bool:
    ajuste = db.query(Ajuste).filter(Ajuste.user_id == user_id).first()
    return True if ajuste is None else ajuste.avisos_activos


def activar_avisos(db: Session, user_id: int, activos: bool) -> bool:
    ajuste = db.query(Ajuste).filter(Ajuste.user_id == user_id).first()
    if ajuste is None:
        ajuste = Ajuste(user_id=user_id)
        db.add(ajuste)
    ajuste.avisos_activos = activos
    db.commit()
    return activos


def destinatarios_del_aviso(db: Session) -> list[AvisoDelDia]:
    """Quién debe recibir el aviso de esta noche, ya con su contenido."""
    hoy = hoy_local()
    manana = hoy + timedelta(days=1)

    con_apuntes = {
        fila[0]
        for fila in db.query(Apunte.user_id).filter(Apunte.fecha == hoy).distinct().all()
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
        )
        for user_id in sorted((con_apuntes | con_citas) - apagados)
    ]
