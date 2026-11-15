"""Router de trabajos (obras): adaptador fino sobre servicios/trabajos.py."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencias import get_current_user_id
from app.api.schemas import (
    FichaTrabajoSalida,
    TrabajoCambios,
    TrabajoEntrada,
    TrabajoListadoSalida,
    TrabajoSalida,
)
from app.nucleo.db import get_db
from app.servicios.trabajos import (
    TrabajoNoEncontrado,
    TrabajoNoValido,
    actualizar_trabajo,
    borrar_trabajo,
    crear_trabajo,
    ficha_trabajo,
    listar_trabajos,
)

router = APIRouter(prefix="/trabajos", tags=["trabajos"])


@router.get("", response_model=list[TrabajoListadoSalida])
def listar(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Todos los trabajos con sus cuentas, del más reciente al más viejo."""
    return listar_trabajos(db, user_id)


@router.post("", response_model=TrabajoSalida, status_code=status.HTTP_201_CREATED)
def crear(
    entrada: TrabajoEntrada,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        return crear_trabajo(db, user_id, **entrada.model_dump())
    except TrabajoNoValido as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.get("/{trabajo_id}", response_model=FichaTrabajoSalida)
def ficha(
    trabajo_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """El trabajo abierto: sus cobros, gastos, notas, citas y cuentas."""
    try:
        return ficha_trabajo(db, user_id, trabajo_id)
    except TrabajoNoEncontrado as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.patch("/{trabajo_id}", response_model=TrabajoSalida)
def cambiar(
    trabajo_id: int,
    cambios: TrabajoCambios,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        return actualizar_trabajo(
            db, user_id, trabajo_id, **cambios.model_dump(exclude_unset=True)
        )
    except TrabajoNoEncontrado as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except TrabajoNoValido as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.delete("/{trabajo_id}", status_code=status.HTTP_204_NO_CONTENT)
def borrar(
    trabajo_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Borra la ficha. Lo que tenía dentro se queda, suelto."""
    try:
        borrar_trabajo(db, user_id, trabajo_id)
    except TrabajoNoEncontrado as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
