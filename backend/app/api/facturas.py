"""Router del escáner de tickets: adaptador fino sobre servicios/facturas.py."""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.dependencias import get_current_user_id
from app.api.schemas import ApunteSalida, GastoDeFactura, TicketLeido
from app.nucleo.db import get_db
from app.nucleo.lectura_tickets import ErrorDeLectura, LecturaNoDisponible
from app.servicios.facturas import (
    FacturaNoEncontrada,
    FacturaNoValida,
    GastoNoValido,
    anotar_gasto,
    escanear,
    ruta_de,
)

router = APIRouter(prefix="/facturas", tags=["facturas"])


@router.post("/escanear", response_model=TicketLeido)
async def escanear_ticket(
    imagen: UploadFile = File(...),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Lee la foto y devuelve lo entendido. No anota nada todavía."""
    datos = await imagen.read()
    try:
        leido = await escanear(db, user_id, datos, imagen.content_type or "")
    except FacturaNoValida as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except LecturaNoDisponible as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "No sé leer tickets: falta configurar OPENAI_API_KEY",
        ) from exc
    except ErrorDeLectura as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"No he podido leer la foto: {exc}") from exc
    d = leido.datos
    return TicketLeido(
        factura_id=leido.factura.id,
        total=d.total,
        fecha=d.fecha,
        comercio=d.comercio,
        iva=d.iva,
        concepto=d.concepto_sugerido,
    )


@router.post("/{factura_id}/gasto", response_model=ApunteSalida, status_code=status.HTTP_201_CREATED)
def confirmar_gasto(
    factura_id: int,
    gasto: GastoDeFactura,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        return anotar_gasto(
            db, user_id, factura_id, gasto.concepto, gasto.importe, gasto.fecha, origen="web"
        )
    except FacturaNoEncontrada as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except GastoNoValido as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.get("/{factura_id}/imagen")
def ver_imagen(
    factura_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        ruta, mime = ruta_de(db, user_id, factura_id)
    except FacturaNoEncontrada as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    if not ruta.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "la imagen ya no está en el servidor")
    return FileResponse(ruta, media_type=mime)
