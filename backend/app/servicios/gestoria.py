"""Lo que se manda a la gestoría de un periodo: el mes, o el trimestre.

En la app está todo junto, pero a la gestoría va solo lo de Yoa: las
facturas que emite y los gastos que les corresponden (`dominio/gestoria.py`
tiene la regla). Esto reparte los movimientos de un periodo en "va" y "no
va", para que la pantalla sea una lista de repaso de fin de mes: se ve lo
que sale, y lo que se queda fuera también, que es donde se cuela un olvido.

Cada cosa va en el periodo de su propia fecha, como en los libros de IVA: la
factura en el mes en que se emite y el gasto en el mes del ticket, aunque
sean del mismo trabajo.
"""
import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.servicios.apuntes import movimientos


@dataclass
class ParteGestoria:
    # Lo que va: trabajos facturados y los gastos que los acompañan.
    emitidas: list
    recibidas: list
    # Lo que se queda fuera, para repasarlo: trabajos sin facturar y gastos
    # de trabajos no facturados o sueltos sin marcar.
    trabajos_fuera: list
    gastos_fuera: list

    @property
    def facturado(self) -> Decimal:
        return sum((a.importe for a in self.emitidas), Decimal("0"))

    @property
    def gastos(self) -> Decimal:
        return sum((a.importe for a in self.recibidas), Decimal("0"))

    @property
    def diferencia(self) -> Decimal:
        return self.facturado - self.gastos

    @property
    def sin_documento(self) -> int:
        """Cuántos de los que van no tienen su factura o ticket colgado.

        A la gestoría no le vale una línea en una hoja: necesita el papel.
        Decirlo aquí es la diferencia entre subirlo hoy y que lo reclamen
        cuando ya no se sabe dónde está.
        """
        return sum(1 for a in self.emitidas + self.recibidas if a.factura is None)


def parte_gestoria(db: Session, user_id: int, desde: date, hasta: date) -> ParteGestoria:
    """Los movimientos del periodo repartidos en lo que va y lo que no."""
    parte = ParteGestoria(emitidas=[], recibidas=[], trabajos_fuera=[], gastos_fuera=[])
    # De más antiguo a más reciente: es el orden en que los pide la gestoría.
    for apunte in reversed(movimientos(db, user_id, desde, hasta)):
        if apunte.tipo == "trabajo":
            (parte.emitidas if apunte.gestoria else parte.trabajos_fuera).append(apunte)
        else:
            (parte.recibidas if apunte.gestoria else parte.gastos_fuera).append(apunte)
    return parte


def csv_gestoria(db: Session, user_id: int, desde: date, hasta: date) -> str:
    """La hoja que acompaña a los PDF: una línea por factura emitida o recibida."""
    parte = parte_gestoria(db, user_id, desde, hasta)
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(["fecha", "tipo", "concepto", "importe", "trabajo", "documento"])
    filas = [("factura emitida", a) for a in parte.emitidas] + [
        ("gasto", a) for a in parte.recibidas
    ]
    for tipo, a in sorted(filas, key=lambda fila: (fila[1].fecha, fila[1].id)):
        escritor.writerow(
            [
                a.fecha.isoformat(),
                tipo,
                a.concepto,
                # Dos decimales siempre, como en el otro CSV.
                f"{a.importe:.2f}",
                a.trabajo_concepto or "",
                "si" if a.factura is not None else "no",
            ]
        )
    return salida.getvalue()
