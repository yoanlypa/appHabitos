"""Router de resúmenes: adaptador fino sobre servicios/resumen.py."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencias import get_current_user_id
from app.api.schemas import ResumenSalida, TrimestreSalida
from app.nucleo.db import get_db
from app.nucleo.tiempo import hoy_local
from app.servicios.resumen import ResumenPeriodo, resumen_dia, resumen_mes
from app.servicios.trimestres import resumen_trimestre, trimestre_de

router = APIRouter(prefix="/resumen", tags=["resumen"])


def _a_salida(r: ResumenPeriodo) -> ResumenSalida:
    return ResumenSalida(cobrado=r.cobrado, pendiente=r.pendiente, gastos=r.gastos, neto=r.neto)


@router.get("/dia", response_model=ResumenSalida)
def dia(
    fecha: date | None = None,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return _a_salida(resumen_dia(db, user_id, fecha))


@router.get("/mes", response_model=ResumenSalida)
def mes(
    anio: int,
    mes: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return _a_salida(resumen_mes(db, user_id, anio, mes))


@router.get("/trimestre", response_model=TrimestreSalida)
def trimestre(
    anio: int | None = None,
    numero: int | None = None,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Totales del trimestre. Sin parámetros, el que corre ahora."""
    hoy = hoy_local()
    try:
        return resumen_trimestre(db, user_id, anio or hoy.year, numero or trimestre_de(hoy))
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
