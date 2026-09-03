"""Casos de uso sobre apuntes: crear, listar y marcar cobrado.

Única capa que toca la base de datos, y solo a través de `dominio/`. `api/`
y `bot/` llaman aquí; si un handler hiciera esto directamente, la lógica
estaría mal colocada.
"""
from datetime import date

from sqlalchemy.orm import Session

from app.dominio.models import Apunte
from app.dominio.parsing import interpretar_texto
from app.nucleo.tiempo import hoy_local


class ApunteNoEncontrado(LookupError):
    """No existe un apunte con ese id para ese usuario."""


def crear_apunte(
    db: Session, user_id: int, texto: str, origen: str, cliente_id: int | None = None
) -> Apunte:
    interpretado = interpretar_texto(texto)
    apunte = Apunte(
        user_id=user_id,
        fecha=hoy_local(),
        tipo=interpretado.tipo,
        concepto=interpretado.concepto,
        importe=interpretado.importe,
        pendiente=interpretado.pendiente,
        origen=origen,
        cliente_id=cliente_id,
    )
    db.add(apunte)
    db.commit()
    db.refresh(apunte)
    return apunte


def listar_apuntes(db: Session, user_id: int, fecha: date | None = None) -> list[Apunte]:
    """Los apuntes de un día, el más reciente primero (que es como se miran)."""
    return (
        db.query(Apunte)
        .filter(Apunte.user_id == user_id, Apunte.fecha == (fecha or hoy_local()))
        .order_by(Apunte.id.desc())
        .all()
    )


def marcar_cobrado(db: Session, user_id: int, apunte_id: int) -> Apunte:
    apunte = (
        db.query(Apunte)
        .filter(Apunte.id == apunte_id, Apunte.user_id == user_id)
        .first()
    )
    if apunte is None:
        raise ApunteNoEncontrado(f"apunte {apunte_id} no existe para el usuario {user_id}")
    apunte.pendiente = False
    db.commit()
    db.refresh(apunte)
    return apunte
