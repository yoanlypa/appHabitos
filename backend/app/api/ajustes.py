"""Router de ajustes: adaptador fino sobre servicios/avisos.py.

De momento, a qué correo se mandan también los avisos de las citas, y un
botón para probarlo, que es como se sabe si la clave de Resend está bien.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencias import get_current_user_id
from app.api.schemas import AjustesCambios, AjustesSalida
from app.nucleo.correo import CorreoNoDisponible, ErrorDeCorreo
from app.nucleo.db import get_db
from app.servicios.avisos import (
    CorreoNoValido,
    avisos_activos,
    correo_de,
    correo_disponible,
    guardar_correo,
    probar_correo,
)

router = APIRouter(prefix="/ajustes", tags=["ajustes"])


def _salida(db: Session, user_id: int) -> AjustesSalida:
    return AjustesSalida(
        avisos_activos=avisos_activos(db, user_id),
        correo=correo_de(db, user_id),
        correo_disponible=correo_disponible(),
    )


@router.get("", response_model=AjustesSalida)
def ver(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    return _salida(db, user_id)


@router.patch("", response_model=AjustesSalida)
def cambiar(
    cambios: AjustesCambios,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    if "correo" in cambios.model_fields_set:
        try:
            guardar_correo(db, user_id, cambios.correo)
        except CorreoNoValido as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return _salida(db, user_id)


@router.post("/correo/prueba")
async def prueba(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Manda un correo de prueba. Si falla, devuelve el motivo tal cual: es lo que hay que arreglar."""
    try:
        para = await probar_correo(db, user_id)
    except CorreoNoValido as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except CorreoNoDisponible as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "El servidor todavía no sabe mandar correos: falta RESEND_API_KEY en Railway.",
        ) from exc
    except ErrorDeCorreo as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return {"enviado_a": para}
