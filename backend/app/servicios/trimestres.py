"""Resumen por trimestre, que es como se paga en España.

Da los totales del periodo y una estimación **orientativa** del pago
fraccionado del IRPF (modelo 130: el 20% del rendimiento neto). No pretende
sustituir a una gestoría: aquí no se sabe qué gastos son deducibles, si hay
retenciones practicadas por los clientes, ni el acumulado de trimestres
anteriores. Sirve para no llegar a la fecha sin idea de la cifra.

Se cuenta lo **cobrado**, no lo facturado: es lo que refleja el dinero que
ha entrado de verdad, y para quien trabaja así es la cuenta que importa.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.dominio.models import Apunte

# Porcentaje del modelo 130 para actividades en estimación directa.
PORCENTAJE_130 = Decimal("0.20")


@dataclass
class ResumenTrimestre:
    anio: int
    trimestre: int
    desde: date
    hasta: date
    cobrado: Decimal
    pendiente: Decimal
    gastos: Decimal
    neto: Decimal
    estimacion_130: Decimal


def limites(anio: int, trimestre: int) -> tuple[date, date]:
    if trimestre not in (1, 2, 3, 4):
        raise ValueError("el trimestre va de 1 a 4")
    primer_mes = 3 * (trimestre - 1) + 1
    desde = date(anio, primer_mes, 1)
    if trimestre == 4:
        hasta = date(anio, 12, 31)
    else:
        hasta = date(anio, primer_mes + 3, 1) - timedelta(days=1)
    return desde, hasta


def trimestre_de(fecha: date) -> int:
    return (fecha.month - 1) // 3 + 1


def resumen_trimestre(db: Session, user_id: int, anio: int, trimestre: int) -> ResumenTrimestre:
    desde, hasta = limites(anio, trimestre)
    apuntes = (
        db.query(Apunte)
        .filter(Apunte.user_id == user_id, Apunte.fecha >= desde, Apunte.fecha <= hasta)
        .all()
    )

    cobrado = sum(
        (a.importe for a in apuntes if a.tipo == "trabajo" and not a.pendiente), Decimal("0")
    )
    pendiente = sum(
        (a.importe for a in apuntes if a.tipo == "trabajo" and a.pendiente), Decimal("0")
    )
    gastos = sum((a.importe for a in apuntes if a.tipo == "gasto"), Decimal("0"))
    neto = cobrado - gastos

    estimacion = max(neto, Decimal("0")) * PORCENTAJE_130
    return ResumenTrimestre(
        anio=anio,
        trimestre=trimestre,
        desde=desde,
        hasta=hasta,
        cobrado=cobrado,
        pendiente=pendiente,
        gastos=gastos,
        neto=neto,
        estimacion_130=estimacion.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
    )
