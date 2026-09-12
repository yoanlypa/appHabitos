"""Volver a meter una copia de seguridad sin duplicar lo que ya está.

Existe porque los datos se han perdido dos veces (la base vivía dentro del
contenedor) y la copia semanal por Telegram no tenía camino de vuelta.

Cuándo un apunte de la copia "ya está": misma fecha, tipo, concepto e
importe. `pendiente` no entra en la comparación a propósito: si un trabajo
se cobró después de hacer la copia sigue siendo el mismo trabajo, y
restaurarlo como pendiente sería inventarse una deuda. Lo que hay en la base
manda; de la copia solo entra lo que falta.

Se cuenta, no se busca uno a uno: dos "gasolina 45" el mismo día son dos
repostajes. Si la copia tiene dos y la base uno, falta uno. Así, restaurar la
misma copia dos veces no duplica nada.

Lo que no puede evitar es devolver lo que se borró a propósito después de
hacer la copia, porque en la copia está y en la base no. Por eso va en dos
pasos: `planificar()` para enseñar lo que entraría, y `restaurar()` cuando
se confirma.

La copia es el CSV de los apuntes: no lleva clientes ni citas. Lo restaurado
vuelve sin cliente asignado, y las notas vuelven sin marcar como hechas.
"""
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.dominio.copia_csv import FilaCopia
from app.dominio.models import Apunte

_CENTIMO = Decimal("0.01")


@dataclass
class PlanDeRestauracion:
    nuevas: list[FilaCopia] = field(default_factory=list)
    ya_estaban: int = 0

    @property
    def total(self) -> int:
        return self.ya_estaban + len(self.nuevas)


def _clave(fecha: date, tipo: str, concepto: str, importe: Decimal) -> tuple:
    # Se redondea al céntimo: de la base sale 120 y de la copia 120.00, y son
    # el mismo importe.
    return (fecha, tipo, concepto.strip(), Decimal(importe).quantize(_CENTIMO))


def planificar(db: Session, user_id: int, filas: list[FilaCopia]) -> PlanDeRestauracion:
    """Qué entraría si se restaura ahora. No escribe nada."""
    if not filas:
        return PlanDeRestauracion()

    desde = min(fila.fecha for fila in filas)
    hasta = max(fila.fecha for fila in filas)
    en_la_base = Counter(
        _clave(a.fecha, a.tipo, a.concepto, a.importe)
        for a in db.query(Apunte).filter(
            Apunte.user_id == user_id, Apunte.fecha >= desde, Apunte.fecha <= hasta
        )
    )

    plan = PlanDeRestauracion()
    for fila in filas:
        clave = _clave(fila.fecha, fila.tipo, fila.concepto, fila.importe)
        if en_la_base[clave] > 0:
            en_la_base[clave] -= 1
            plan.ya_estaban += 1
        else:
            plan.nuevas.append(fila)
    return plan


def restaurar(db: Session, user_id: int, filas: list[FilaCopia]) -> int:
    """Mete lo que falta. Devuelve cuántos apuntes han entrado.

    Se vuelve a planificar aquí en vez de fiarse de la vista previa: entre
    enseñarla y confirmar se puede haber apuntado algo, y lo que ya esté no
    puede acabar duplicado.
    """
    plan = planificar(db, user_id, filas)
    for fila in plan.nuevas:
        db.add(
            Apunte(
                user_id=user_id,
                fecha=fila.fecha,
                tipo=fila.tipo,
                concepto=fila.concepto,
                importe=fila.importe,
                pendiente=fila.pendiente and fila.tipo == "trabajo",
                hecha=False,
                origen=fila.origen,
            )
        )
    db.commit()
    return len(plan.nuevas)
