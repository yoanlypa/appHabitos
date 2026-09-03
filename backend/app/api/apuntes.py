"""Router de apuntes: adaptador fino sobre servicios/apuntes.py, sin lógica propia."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencias import get_current_user_id
from app.api.schemas import ApunteEntrada, ApunteSalida
from app.dominio.parsing import TextoNoInterpretable
from app.nucleo.db import get_db
from app.servicios.apuntes import ApunteNoEncontrado, crear_apunte, marcar_cobrado

router = APIRouter(prefix="/apuntes", tags=["apuntes"])


@router.post("", response_model=ApunteSalida, status_code=status.HTTP_201_CREATED)
def crear(
    entrada: ApunteEntrada,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        return crear_apunte(db, user_id, entrada.texto, entrada.origen)
    except TextoNoInterpretable as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.post("/{apunte_id}/cobrado", response_model=ApunteSalida)
def cobrar(
    apunte_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        return marcar_cobrado(db, user_id, apunte_id)
    except ApunteNoEncontrado as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
