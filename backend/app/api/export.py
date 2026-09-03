"""Router de exportación: adaptador fino sobre servicios/export.py."""
from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.dependencias import get_current_user_id
from app.nucleo.db import get_db
from app.servicios.export import exportar_csv

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/csv", response_class=PlainTextResponse)
def csv(
    desde: date,
    hasta: date,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return PlainTextResponse(exportar_csv(db, user_id, desde, hasta), media_type="text/csv")
