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


def resumen_rango(db: Session, user_id: int, desde: date, hasta: date) -> ResumenPeriodo:
    """Totales entre dos fechas, las dos incluidas: el año, el mes pasado, lo que sea.

    Para los periodos de Finanzas. Usa la misma suma que el día y el mes, así
    que el total de un año es exactamente la suma de sus meses.
    """
    apuntes = (
        db.query(Apunte)
        .filter(Apunte.user_id == user_id, Apunte.fecha >= desde, Apunte.fecha <= hasta)
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


def resumen_por_meses(db: Session, user_id: int, anio: int) -> list[ResumenPeriodo]:
    """Los doce meses de un año, de enero a diciembre, para el gráfico de Finanzas.

    Una sola consulta repartida por mes con la misma suma que todo lo demás:
    si el gráfico sumara por su cuenta, el día que no cuadrase con el total
    del año nadie sabría cuál de los dos creerse. Los meses sin nada salen a
    cero, que también es un dato (y el eje no se queda con huecos).
    """
    apuntes = (
        db.query(Apunte)
        .filter(
            Apunte.user_id == user_id,
            Apunte.fecha >= date(anio, 1, 1),
            Apunte.fecha <= date(anio, 12, 31),
        )
        .all()
    )
    por_mes: list[list[Apunte]] = [[] for _ in range(12)]
    for a in apuntes:
        por_mes[a.fecha.month - 1].append(a)
    return [_resumir(del_mes) for del_mes in por_mes]
