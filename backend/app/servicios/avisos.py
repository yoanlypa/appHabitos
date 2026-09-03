"""Casos de uso de los avisos diarios: quién los quiere y a quién toca avisar.

Dos decisiones de negocio viven aquí, no en el bot:

1. Se avisa a quien haya anotado algo hoy. Si no has apuntado nada, no hay
   nada que contarte y el bot se calla — un recordatorio vacío cada noche
   es la mejor forma de que alguien silencie el bot.
2. Los avisos están activos salvo que los apagues. Así funcionan desde el
   primer día sin tener que configurar nada, y `Ajuste` solo guarda fila
   para quien ha cambiado algo.
"""
from sqlalchemy.orm import Session

from app.dominio.models import Ajuste, Apunte
from app.nucleo.tiempo import hoy_local
from app.servicios.resumen import ResumenPeriodo, resumen_dia


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


def destinatarios_del_aviso(db: Session) -> list[tuple[int, ResumenPeriodo]]:
    """Quién debe recibir el aviso de hoy, con su resumen ya calculado."""
    hoy = hoy_local()
    con_apuntes = [
        fila[0]
        for fila in db.query(Apunte.user_id).filter(Apunte.fecha == hoy).distinct().all()
    ]
    apagados = {
        fila[0]
        for fila in db.query(Ajuste.user_id).filter(Ajuste.avisos_activos.is_(False)).all()
    }
    return [
        (user_id, resumen_dia(db, user_id, hoy))
        for user_id in con_apuntes
        if user_id not in apagados
    ]
