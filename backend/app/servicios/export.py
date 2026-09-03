"""Caso de uso: exportar los apuntes de un rango de fechas (incluidas ambas) a CSV."""
import csv
import io
from datetime import date

from sqlalchemy.orm import Session

from app.dominio.models import Apunte


def exportar_csv(db: Session, user_id: int, desde: date, hasta: date) -> str:
    apuntes = (
        db.query(Apunte)
        .filter(Apunte.user_id == user_id, Apunte.fecha >= desde, Apunte.fecha <= hasta)
        .order_by(Apunte.fecha, Apunte.id)
        .all()
    )
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(["fecha", "tipo", "concepto", "importe", "pendiente", "origen"])
    for a in apuntes:
        escritor.writerow(
            [a.fecha.isoformat(), a.tipo, a.concepto, a.importe, a.pendiente, a.origen]
        )
    return salida.getvalue()
