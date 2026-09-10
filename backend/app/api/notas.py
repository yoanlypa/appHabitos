"""Router del buzón de notas: adaptador fino sobre servicios/notas.py."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencias import get_current_user_id
from app.api.schemas import AgendarNota, CitaSalida, NotaEntrada, NotaSalida
from app.nucleo.db import get_db
from app.servicios.agenda import RangoAlReves
from app.servicios.apuntes import ApunteNoEncontrado
from app.servicios.notas import agendar, borrar, crear, editar, listar_notas

router = APIRouter(prefix="/notas", tags=["notas"])


@router.get("", response_model=list[NotaSalida])
def listar(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Todas las notas sin fecha, de la más nueva a la más vieja."""
    return listar_notas(db, user_id)


@router.post("", response_model=NotaSalida, status_code=status.HTTP_201_CREATED)
def nueva(
    entrada: NotaEntrada,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        return crear(db, user_id, entrada.texto, origen="web")
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.patch("/{nota_id}", response_model=NotaSalida)
def cambiar(
    nota_id: int,
    entrada: NotaEntrada,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        return editar(db, user_id, nota_id, entrada.texto)
    except ApunteNoEncontrado as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.delete("/{nota_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar(
    nota_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        borrar(db, user_id, nota_id)
    except ApunteNoEncontrado as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.post(
    "/{nota_id}/agendar", response_model=CitaSalida, status_code=status.HTTP_201_CREATED
)
def a_la_agenda(
    nota_id: int,
    entrada: AgendarNota,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Devuelve la cita nueva. La nota ya no está: se ha convertido en ella."""
    try:
        return agendar(
            db,
            user_id,
            nota_id,
            entrada.fecha,
            fecha_fin=entrada.fecha_fin,
            hora=entrada.hora,
            titulo=entrada.titulo,
        )
    except ApunteNoEncontrado as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except RangoAlReves as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
