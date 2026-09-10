"""Casos de uso de exportación: sacar los apuntes en CSV.

`exportar_todo()` existe para las copias de seguridad: el sitio más seguro
para los datos de Yoa no es el servidor, es su propio Telegram.
"""
import csv
import io
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.dominio.models import Apunte


def exportar_csv(
    db: Session, user_id: int, desde: date, hasta: date, incluir_notas: bool = False
) -> str:
    """El CSV del gestor no lleva notas: son recordatorios, no dinero.

    Una columna de importes llena de ceros con "llamar al fontanero" al lado
    solo sirve para que quien lo abra pregunte qué es eso. En la copia de
    seguridad sí van, que ahí lo que se guarda es todo.
    """
    consulta = db.query(Apunte).filter(
        Apunte.user_id == user_id, Apunte.fecha >= desde, Apunte.fecha <= hasta
    )
    if not incluir_notas:
        consulta = consulta.filter(Apunte.tipo != "nota")
    apuntes = consulta.order_by(Apunte.fecha, Apunte.id).all()
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(["fecha", "tipo", "concepto", "importe", "pendiente", "origen"])
    for a in apuntes:
        escritor.writerow(
            [
                a.fecha.isoformat(),
                a.tipo,
                a.concepto,
                # Dos decimales siempre: esto lo abre un gestor, y una
                # columna con "120" y "45.5" mezclados parece mal apuntada.
                f"{a.importe:.2f}",
                "si" if a.pendiente else "no",
                a.origen,
            ]
        )
    return salida.getvalue()


def exportar_todo(db: Session, user_id: int) -> str:
    """Todo el histórico, para la copia de seguridad. Notas incluidas."""
    primero = db.query(func.min(Apunte.fecha)).filter(Apunte.user_id == user_id).scalar()
    ultimo = db.query(func.max(Apunte.fecha)).filter(Apunte.user_id == user_id).scalar()
    if primero is None:
        return "fecha,tipo,concepto,importe,pendiente,origen\n"
    return exportar_csv(db, user_id, primero, ultimo, incluir_notas=True)
