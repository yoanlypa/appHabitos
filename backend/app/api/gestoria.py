"""Router de la gestoría: adaptador fino sobre servicios/gestoria.py."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.dependencias import get_current_user_id
from app.api.schemas import ParteGestoriaSalida
from app.nucleo.db import get_db
from app.servicios.gestoria import csv_gestoria, parte_gestoria

router = APIRouter(prefix="/gestoria", tags=["gestoria"])


def _rango(desde: date, hasta: date) -> None:
    if hasta < desde:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "el rango está al revés")


@router.get("", response_model=ParteGestoriaSalida)
def parte(
    desde: date,
    hasta: date,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Lo del periodo repartido en lo que va a la gestoría y lo que no."""
    _rango(desde, hasta)
    return parte_gestoria(db, user_id, desde, hasta)


@router.get("/csv")
def csv(
    desde: date,
    hasta: date,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """La hoja de lo que va a la gestoría, para abrir en Excel.

    Con BOM: sin él Excel lee "Reforma baño" como "Reforma baÃ±o", y esto lo
    abre alguien que no tiene por qué saber arreglarlo.
    """
    _rango(desde, hasta)
    contenido = "\ufeff" + csv_gestoria(db, user_id, desde, hasta)
    return Response(contenido.encode("utf-8"), media_type="text/csv; charset=utf-8")
