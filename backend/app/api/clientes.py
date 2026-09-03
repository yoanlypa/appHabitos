"""Router de clientes: adaptador fino sobre servicios/clientes.py."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencias import get_current_user_id
from app.api.schemas import (
    ApunteSalida,
    AsignarCliente,
    ClienteCambios,
    ClienteEntrada,
    ClienteListado,
    ClienteSalida,
    FichaClienteSalida,
)
from app.nucleo.db import get_db
from app.servicios.clientes import (
    ClienteNoEncontrado,
    actualizar_cliente,
    asignar_cliente,
    borrar_cliente,
    crear_cliente,
    ficha_cliente,
    listar_clientes,
    pendientes_de_cobro,
)

router = APIRouter(prefix="/clientes", tags=["clientes"])


@router.get("", response_model=list[ClienteListado])
def listar(
    buscar: str | None = None,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return [
        ClienteListado(cliente=c.cliente, debe=c.debe, total_trabajos=c.total_trabajos)
        for c in listar_clientes(db, user_id, buscar)
    ]


@router.post("", response_model=ClienteSalida, status_code=status.HTTP_201_CREATED)
def crear(
    entrada: ClienteEntrada,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return crear_cliente(
        db, user_id, entrada.nombre, entrada.telefono, entrada.direccion, entrada.notas
    )


@router.get("/{cliente_id}", response_model=FichaClienteSalida)
def ficha(
    cliente_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        f = ficha_cliente(db, user_id, cliente_id)
    except ClienteNoEncontrado as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return FichaClienteSalida(
        cliente=f.cliente, debe=f.debe, cobrado=f.cobrado, apuntes=f.apuntes, citas=f.citas
    )


@router.patch("/{cliente_id}", response_model=ClienteSalida)
def editar(
    cliente_id: int,
    cambios: ClienteCambios,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        return actualizar_cliente(db, user_id, cliente_id, **cambios.model_dump(exclude_unset=True))
    except ClienteNoEncontrado as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.delete("/{cliente_id}", status_code=status.HTTP_204_NO_CONTENT)
def borrar(
    cliente_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        borrar_cliente(db, user_id, cliente_id)
    except ClienteNoEncontrado as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


# Cuelga de /clientes porque es lo mismo mirado del otro lado: quién te debe.
otros = APIRouter(tags=["clientes"])


@otros.get("/apuntes/pendientes", response_model=list[ApunteSalida])
def pendientes(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return pendientes_de_cobro(db, user_id)


@otros.post("/apuntes/{apunte_id}/cliente", response_model=ApunteSalida)
def poner_cliente(
    apunte_id: int,
    cuerpo: AsignarCliente,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        return asignar_cliente(db, user_id, apunte_id, cuerpo.cliente_id)
    except (ClienteNoEncontrado, LookupError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
