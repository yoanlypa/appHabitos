"""Router de exportación: adaptador fino sobre servicios/export.py."""
from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.orm import Session

from app.api.dependencias import get_current_user_id
from app.nucleo.db import get_db
from app.nucleo.tiempo import hoy_local
from app.servicios.copia_completa import generar
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


@router.get("/copia")
def copia(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """La copia de seguridad completa, la misma que manda el bot.

    Para quien entró solo por la web (no tiene chat de Telegram donde
    recibirla) y para quien prefiera guardarla en su ordenador. 204 si no
    hay nada que guardar.
    """
    copia = generar(db, user_id)
    if copia is None:
        return Response(status_code=204)
    datos, _cuenta = copia
    nombre = f"parte-del-dia-{hoy_local().isoformat()}.zip"
    return Response(
        datos,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )
