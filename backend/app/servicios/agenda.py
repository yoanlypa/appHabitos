"""Casos de uso de la agenda: las citas.

Un autónomo de servicios vive de estar en el sitio correcto a la hora
correcta, así que esto tiene tanto peso como el dinero.

Las citas se ordenan poniendo primero las que tienen hora: si has quedado a
las 9 con una y "por la tarde" con otra, la de las 9 va antes.
"""
from dataclasses import dataclass
from datetime import date, time

from sqlalchemy.orm import Session

from app.dominio.models import Cita, Cliente
from app.nucleo.tiempo import hoy_local


class CitaNoEncontrada(LookupError):
    """No existe esa cita para ese usuario."""


@dataclass
class DiaConCitas:
    fecha: date
    citas: list[Cita]


def _ordenadas(citas: list[Cita]) -> list[Cita]:
    # (0, hora) para las que tienen hora y (1, 00:00) para las que no: así las
    # sin hora caen al final del día en vez de a primera hora.
    return sorted(citas, key=lambda c: (c.hora is None, c.hora or time.min, c.id))


def _suya(db: Session, user_id: int, cita_id: int) -> Cita:
    cita = db.query(Cita).filter(Cita.id == cita_id, Cita.user_id == user_id).first()
    if cita is None:
        raise CitaNoEncontrada(f"la cita {cita_id} no existe para {user_id}")
    return cita


def crear_cita(
    db: Session,
    user_id: int,
    fecha: date,
    titulo: str,
    hora: time | None = None,
    direccion: str | None = None,
    cliente_id: int | None = None,
    notas: str | None = None,
) -> Cita:
    if cliente_id is not None:
        existe = (
            db.query(Cliente)
            .filter(Cliente.id == cliente_id, Cliente.user_id == user_id)
            .first()
        )
        if existe is None:
            raise LookupError(f"el cliente {cliente_id} no existe para {user_id}")

    cita = Cita(
        user_id=user_id,
        fecha=fecha,
        hora=hora,
        titulo=titulo.strip(),
        direccion=(direccion or None),
        cliente_id=cliente_id,
        notas=(notas or None),
    )
    db.add(cita)
    db.commit()
    db.refresh(cita)
    return cita


def citas_del_dia(db: Session, user_id: int, fecha: date | None = None) -> list[Cita]:
    citas = (
        db.query(Cita)
        .filter(Cita.user_id == user_id, Cita.fecha == (fecha or hoy_local()))
        .all()
    )
    return _ordenadas(citas)


def citas_del_mes(db: Session, user_id: int, anio: int, mes: int) -> list[Cita]:
    desde = date(anio, mes, 1)
    hasta = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)
    citas = (
        db.query(Cita)
        .filter(Cita.user_id == user_id, Cita.fecha >= desde, Cita.fecha < hasta)
        .all()
    )
    return sorted(_ordenadas(citas), key=lambda c: c.fecha)


def proximas_citas(db: Session, user_id: int, limite: int = 10) -> list[Cita]:
    """De hoy en adelante y sin hacer: lo que tienes por delante."""
    citas = (
        db.query(Cita)
        .filter(
            Cita.user_id == user_id,
            Cita.fecha >= hoy_local(),
            Cita.hecha.is_(False),
        )
        .order_by(Cita.fecha)
        .limit(limite * 3)
        .all()
    )
    ordenadas = sorted(_ordenadas(citas), key=lambda c: c.fecha)
    return ordenadas[:limite]


def marcar_hecha(db: Session, user_id: int, cita_id: int, hecha: bool = True) -> Cita:
    cita = _suya(db, user_id, cita_id)
    cita.hecha = hecha
    db.commit()
    db.refresh(cita)
    return cita


def borrar_cita(db: Session, user_id: int, cita_id: int) -> None:
    db.delete(_suya(db, user_id, cita_id))
    db.commit()
