"""Router del escáner de tickets: adaptador fino sobre servicios/facturas.py."""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from datetime import date

from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.api.dependencias import get_current_user_id
from app.api.schemas import ApunteSalida, FacturaEmitidaEntrada, GastoDeFactura, TicketLeido
from app.nucleo.db import get_db
from app.nucleo.lectura_tickets import ErrorDeLectura, LecturaNoDisponible
from app.servicios.facturas import (
    FacturaNoEncontrada,
    FacturaNoValida,
    GastoNoValido,
    anotar_emitida,
    anotar_gasto,
    importe_a_cobrar,
    escanear,
    pdf_de_factura,
    pdf_del_periodo,
    ruta_de,
    vista_emitida,
)
from app.nucleo.pdf import ImagenNoLegible

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
    vista = vista_emitida(db, user_id, d)
    return TicketLeido(
        factura_id=leido.factura.id,
        total=d.total,
        fecha=d.fecha,
        comercio=d.comercio,
        iva=d.iva,
        concepto=(d.concepto or d.concepto_sugerido) if vista else d.concepto_sugerido,
        emitida=vista is not None,
        cliente=vista.cliente if vista else None,
        a_cobrar=importe_a_cobrar(d) if vista else None,
        candidatos=vista.candidatos if vista else [],
    )


@router.post("/{factura_id}/emitida", response_model=ApunteSalida, status_code=status.HTTP_201_CREATED)
def confirmar_emitida(
    factura_id: int,
    entrada: FacturaEmitidaEntrada,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Una factura de Yoa confirmada: a un trabajo ya anotado o a uno nuevo."""
    try:
        return anotar_emitida(
            db, user_id, factura_id, entrada.apunte_id, entrada.cobrada,
            entrada.concepto, entrada.importe, entrada.fecha, origen="web",
        )
    except FacturaNoEncontrada as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except GastoNoValido as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


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


def _pdf(contenido: bytes, nombre: str) -> Response:
    # inline: el móvil lo abre en su visor y desde ahí se guarda o se comparte.
    return Response(
        contenido,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{nombre}"'},
    )


@router.get("/pdf")
def pdf_periodo(
    desde: date,
    hasta: date,
    emitidas: bool = False,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Todas las facturas del periodo en un solo PDF, para la gestoría."""
    if hasta < desde:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "el rango está al revés")
    try:
        contenido = pdf_del_periodo(db, user_id, desde, hasta, emitidas)
    except ImagenNoLegible as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
    if contenido is None:
        que = "facturas emitidas" if emitidas else "tickets escaneados"
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No hay {que} en esas fechas")
    nombre = "facturas-emitidas" if emitidas else "tickets"
    return _pdf(contenido, f"{nombre}-{desde.isoformat()}_{hasta.isoformat()}.pdf")


@router.get("/{factura_id}/pdf")
def pdf_factura(
    factura_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        contenido, nombre = pdf_de_factura(db, user_id, factura_id)
    except FacturaNoEncontrada as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ImagenNoLegible as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "la imagen ya no se puede abrir") from exc
    return _pdf(contenido, nombre)
