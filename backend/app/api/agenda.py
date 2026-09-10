"""Router de la agenda: adaptador fino sobre servicios/agenda.py."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencias import get_current_user_id
from app.api.schemas import CitaCambios, CitaEntrada, CitaSalida
from app.nucleo.db import get_db
from app.servicios.agenda import (
    CitaNoEncontrada,
    RangoAlReves,
    actualizar_cita,
    borrar_cita,
    citas_del_dia,
    citas_del_mes,
    crear_cita,
    marcar_hecha,
    proximas_citas,
)

router = APIRouter(prefix="/citas", tags=["agenda"])


@router.get("", response_model=list[CitaSalida])
def listar(
    fecha: date | None = None,
    anio: int | None = None,
    mes: int | None = None,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Un día concreto, un mes entero (para pintar el calendario), o hoy."""
    if anio is not None and mes is not None:
        return citas_del_mes(db, user_id, anio, mes)
    return citas_del_dia(db, user_id, fecha)


@router.get("/proximas", response_model=list[CitaSalida])
def proximas(
    limite: int = 10,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return proximas_citas(db, user_id, limite)


@router.post("", response_model=CitaSalida, status_code=status.HTTP_201_CREATED)
def crear(
    entrada: CitaEntrada,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        return crear_cita(
            db,
            user_id,
            entrada.fecha,
            entrada.titulo,
            hora=entrada.hora,
            direccion=entrada.direccion,
            cliente_id=entrada.cliente_id,
            notas=entrada.notas,
            fecha_fin=entrada.fecha_fin,
        )
    except RangoAlReves as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.patch("/{cita_id}", response_model=CitaSalida)
def editar(
    cita_id: int,
    cambios: CitaCambios,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Corrige una cita ya puesta: el texto, el día, el rango, la hora.

    `exclude_unset` es lo que hace que se pueda vaciar la hora sin borrar
    de paso todo lo demás: lo que no se manda, no se toca.
    """
    try:
        return actualizar_cita(db, user_id, cita_id, **cambios.model_dump(exclude_unset=True))
    except CitaNoEncontrada as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except RangoAlReves as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.post("/{cita_id}/hecha", response_model=CitaSalida)
def hecha(
    cita_id: int,
    hecha: bool = True,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        return marcar_hecha(db, user_id, cita_id, hecha)
    except CitaNoEncontrada as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.delete("/{cita_id}", status_code=status.HTTP_204_NO_CONTENT)
def borrar(
    cita_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        borrar_cita(db, user_id, cita_id)
    except CitaNoEncontrada as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
