"""Router de apuntes: adaptador fino sobre servicios/apuntes.py, sin lógica propia."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencias import get_current_user_id
from app.api.schemas import ApunteCreado, ApunteEntrada, ApunteSalida
from app.dominio.parsing import TextoNoInterpretable
from app.nucleo.db import get_db
from app.servicios.apuntes import (
    ApunteNoEncontrado,
    anotar,
    listar_apuntes,
    marcar_cobrado,
)

router = APIRouter(prefix="/apuntes", tags=["apuntes"])


@router.get("", response_model=list[ApunteSalida])
def listar(
    fecha: date | None = None,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return listar_apuntes(db, user_id, fecha)


@router.post("", response_model=ApunteCreado, status_code=status.HTTP_201_CREATED)
def crear(
    entrada: ApunteEntrada,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Anota y, si el texto nombra a un cliente sin lugar a dudas, lo cuelga de él.

    Si hay dos clientes con ese nombre no se elige por el usuario: se
    devuelven en `candidatos` para que la web pregunte, igual que hace el
    bot con sus botones.
    """
    try:
        creado = anotar(db, user_id, entrada.texto, entrada.origen)
    except TextoNoInterpretable as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return ApunteCreado(apunte=creado.apunte, candidatos=creado.candidatos)


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
