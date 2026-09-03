"""Casos de uso de resumen: totales del día y del mes por usuario."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.dominio.models import Apunte
from app.nucleo.tiempo import hoy_local


@dataclass
class ResumenPeriodo:
    cobrado: Decimal
    pendiente: Decimal
    gastos: Decimal

    @property
    def neto(self) -> Decimal:
        return self.cobrado - self.gastos


def _resumir(apuntes: list[Apunte]) -> ResumenPeriodo:
    cobrado = Decimal("0")
    pendiente = Decimal("0")
    gastos = Decimal("0")
    for a in apuntes:
        if a.tipo == "trabajo" and a.pendiente:
            pendiente += a.importe
        elif a.tipo == "trabajo":
            cobrado += a.importe
        elif a.tipo == "gasto":
            gastos += a.importe
    return ResumenPeriodo(cobrado=cobrado, pendiente=pendiente, gastos=gastos)


def resumen_dia(db: Session, user_id: int, fecha: date | None = None) -> ResumenPeriodo:
    apuntes = (
        db.query(Apunte)
        .filter(Apunte.user_id == user_id, Apunte.fecha == (fecha or hoy_local()))
        .all()
    )
    return _resumir(apuntes)


def resumen_mes(db: Session, user_id: int, anio: int, mes: int) -> ResumenPeriodo:
    desde = date(anio, mes, 1)
    hasta = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)
    apuntes = (
        db.query(Apunte)
        .filter(Apunte.user_id == user_id, Apunte.fecha >= desde, Apunte.fecha < hasta)
        .all()
    )
    return _resumir(apuntes)
