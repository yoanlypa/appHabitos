"""Casos de uso de la agenda: las citas.

Un autónomo de servicios vive de estar en el sitio correcto a la hora
correcta, así que esto tiene tanto peso como el dinero.

Las citas se ordenan poniendo primero las que tienen hora: si has quedado a
las 9 con una y "por la tarde" con otra, la de las 9 va antes.
"""
from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.dominio.models import Cita, Cliente
from app.nucleo.tiempo import hoy_local

# El último día de una cita: el de fin si lo tiene, y si no el de inicio.
# Sin esto, un trabajo del martes al jueves solo saldría el martes, que es
# el día en el que menos falta hace mirarlo.
_ULTIMO_DIA = func.coalesce(Cita.fecha_fin, Cita.fecha)


class CitaNoEncontrada(LookupError):
    """No existe esa cita para ese usuario."""


class RangoAlReves(ValueError):
    """La fecha de fin es anterior a la de inicio."""


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


def _comprobar_rango(fecha: date, fecha_fin: date | None) -> date | None:
    """Un solo día se guarda con `fecha_fin` vacía, no repitiendo la fecha.

    Así solo hay una forma de escribir lo mismo y las consultas no tienen
    que mirar dos columnas para saber si algo dura un día.
    """
    if fecha_fin is None or fecha_fin == fecha:
        return None
    if fecha_fin < fecha:
        raise RangoAlReves(f"la cita acabaría el {fecha_fin}, antes de empezar el {fecha}")
    return fecha_fin


def crear_cita(
    db: Session,
    user_id: int,
    fecha: date,
    titulo: str,
    hora: time | None = None,
    direccion: str | None = None,
    cliente_id: int | None = None,
    notas: str | None = None,
    fecha_fin: date | None = None,
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
        fecha_fin=_comprobar_rango(fecha, fecha_fin),
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
    """Lo que toca ese día, incluidas las citas de varios días que lo pisan."""
    dia = fecha or hoy_local()
    citas = (
        db.query(Cita)
        .filter(Cita.user_id == user_id, Cita.fecha <= dia, _ULTIMO_DIA >= dia)
        .all()
    )
    return _ordenadas(citas)


def citas_del_mes(db: Session, user_id: int, anio: int, mes: int) -> list[Cita]:
    """Todo lo que toca algún día del mes, aunque empezara el mes pasado."""
    desde = date(anio, mes, 1)
    hasta = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)
    citas = (
        db.query(Cita)
        .filter(Cita.user_id == user_id, Cita.fecha < hasta, _ULTIMO_DIA >= desde)
        .all()
    )
    return sorted(_ordenadas(citas), key=lambda c: c.fecha)


def proximas_citas(db: Session, user_id: int, limite: int = 10) -> list[Cita]:
    """De hoy en adelante y sin hacer: lo que tienes por delante.

    Una reforma que empezó ayer y acaba pasado sigue siendo lo que tienes
    por delante, así que se mira el último día, no el primero.
    """
    citas = (
        db.query(Cita)
        .filter(
            Cita.user_id == user_id,
            _ULTIMO_DIA >= hoy_local(),
            Cita.hecha.is_(False),
        )
        .order_by(Cita.fecha)
        .limit(limite * 3)
        .all()
    )
    ordenadas = sorted(_ordenadas(citas), key=lambda c: c.fecha)
    return ordenadas[:limite]


_SIN_TOCAR = object()  # None es un valor válido: "quítale la hora", "un solo día"


def actualizar_cita(
    db: Session,
    user_id: int,
    cita_id: int,
    titulo: str | None = None,
    fecha: date | None = None,
    fecha_fin=_SIN_TOCAR,
    hora=_SIN_TOCAR,
    direccion=_SIN_TOCAR,
    notas=_SIN_TOCAR,
    cliente_id=_SIN_TOCAR,
) -> Cita:
    """Corrige una cita: el texto, el día, el rango, la hora.

    Los campos que se pueden vaciar usan un centinela en vez de `None`,
    porque "no me toques la hora" y "quítale la hora" son cosas distintas y
    con `None` para las dos no habría forma de distinguirlas.
    """
    cita = _suya(db, user_id, cita_id)

    if titulo is not None and titulo.strip():
        cita.titulo = titulo.strip()
    if fecha is not None:
        cita.fecha = fecha
    if fecha_fin is not _SIN_TOCAR:
        cita.fecha_fin = fecha_fin
    if hora is not _SIN_TOCAR:
        cita.hora = hora
    if direccion is not _SIN_TOCAR:
        cita.direccion = direccion or None
    if notas is not _SIN_TOCAR:
        cita.notas = notas or None
    if cliente_id is not _SIN_TOCAR:
        cita.cliente_id = cliente_id

    # Se comprueba al final, con los dos valores ya puestos: mover solo el
    # día de inicio de una cita de varios días puede dejarla del revés.
    cita.fecha_fin = _comprobar_rango(cita.fecha, cita.fecha_fin)

    db.commit()
    db.refresh(cita)
    return cita


def marcar_hecha(db: Session, user_id: int, cita_id: int, hecha: bool = True) -> Cita:
    cita = _suya(db, user_id, cita_id)
    cita.hecha = hecha
    db.commit()
    db.refresh(cita)
    return cita


def borrar_cita(db: Session, user_id: int, cita_id: int) -> None:
    db.delete(_suya(db, user_id, cita_id))
    db.commit()
