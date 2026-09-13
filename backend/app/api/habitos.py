"""Router de hábitos: adaptador fino sobre servicios/habitos.py."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencias import get_current_user_id
from app.api.schemas import (
    HabitoCambios,
    HabitoDetalleSalida,
    HabitoEntrada,
    HabitoResumenSalida,
    MarcarDia,
)
from app.dominio.habitos import DiasNoValidos
from app.nucleo.db import get_db
from app.servicios import habitos as servicio
from app.servicios.habitos import DiaNoMarcable, HabitoNoEncontrado

router = APIRouter(prefix="/habitos", tags=["habitos"])


def _no_existe(exc: HabitoNoEncontrado) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))


def _no_vale(exc: ValueError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


@router.get("", response_model=list[HabitoResumenSalida])
def listar(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Cada hábito con su semana de lunes a domingo y su racha."""
    return servicio.listar(db, user_id)


@router.post("", response_model=HabitoResumenSalida, status_code=status.HTTP_201_CREATED)
def crear(
    entrada: HabitoEntrada,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        habito = servicio.crear(db, user_id, entrada.nombre, entrada.dias, entrada.recordar_a)
    except (DiasNoValidos, ValueError) as exc:
        raise _no_vale(exc) from exc
    return servicio.resumen(db, user_id, habito.id)


@router.get("/{habito_id}", response_model=HabitoDetalleSalida)
def detalle(
    habito_id: int,
    anio: int | None = None,
    mes: int | None = None,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Rachas, cumplimiento y el calendario del mes (el actual si no se dice)."""
    try:
        return servicio.detalle(db, user_id, habito_id, anio, mes)
    except HabitoNoEncontrado as exc:
        raise _no_existe(exc) from exc


@router.patch("/{habito_id}", response_model=HabitoResumenSalida)
def editar(
    habito_id: int,
    cambios: HabitoCambios,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        servicio.editar(db, user_id, habito_id, **cambios.model_dump(exclude_unset=True))
        return servicio.resumen(db, user_id, habito_id)
    except HabitoNoEncontrado as exc:
        raise _no_existe(exc) from exc
    except (DiasNoValidos, ValueError) as exc:
        raise _no_vale(exc) from exc


@router.delete("/{habito_id}", status_code=status.HTTP_204_NO_CONTENT)
def borrar(
    habito_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        servicio.borrar(db, user_id, habito_id)
    except HabitoNoEncontrado as exc:
        raise _no_existe(exc) from exc


@router.post("/{habito_id}/dias", response_model=HabitoResumenSalida)
def marcar(
    habito_id: int,
    entrada: MarcarDia,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Marca o desmarca un día (hoy si no se dice cuál)."""
    try:
        return servicio.marcar(db, user_id, habito_id, entrada.fecha, entrada.hecho)
    except HabitoNoEncontrado as exc:
        raise _no_existe(exc) from exc
    except DiaNoMarcable as exc:
        raise _no_vale(exc) from exc
