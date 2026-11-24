"""Router de Casa: adaptador fino sobre servicios/casa.py.

Todo cuelga de `/casa`. Las dos rutas de invitación de entrada
(`GET /casa/invitacion/{codigo}` y `POST /casa/unirse`) no piden token:
quien llega con el enlace todavía no tiene ninguno, y el código es lo que
le da permiso. Un código vale una vez y caduca a los 7 días.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencias import get_current_user_id
from app.api.schemas import (
    ArticuloCambios,
    ArticuloEntrada,
    ArticuloSalida,
    CarteraSalida,
    CasaSalida,
    ImporteEntrada,
    MovimientoCarteraSalida,
    RecuentoSalida,
    GastoCasaCambios,
    GastoCasaEntrada,
    GastoCasaSalida,
    GastoCasaTexto,
    InvitacionSalida,
    InvitacionVista,
    MiembroSalida,
    NombreEntrada,
    RecetaSalida,
    RecetasEntrada,
    ResumenCasaSalida,
    UnirseEntrada,
    UnirseSalida,
)
from app.dominio import casa as reglas
from app.nucleo import recetas as cocina
from app.nucleo.db import get_db
from app.servicios import casa

router = APIRouter(prefix="/casa", tags=["casa"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, (casa.NoEncontrado, casa.SinCasa)):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, casa.SoloTitular):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


_ERRORES = (casa.NoEncontrado, casa.SinCasa, casa.SoloTitular, casa.DatoNoValido, casa.InvitacionNoValida, casa.YaEnOtraCasa)


@router.get("", response_model=CasaSalida)
def mi_casa(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    yo = casa.asegurar_casa(db, user_id)
    return CasaSalida(
        hogar_id=yo.hogar_id,
        nombre=yo.hogar.nombre,
        yo=MiembroSalida.model_validate(yo),
        miembros=[MiembroSalida.model_validate(m) for m in casa.miembros(db, yo.hogar_id)],
        solo_casa=not yo.titular,
        categorias=reglas.CATEGORIAS,
        hay_recetas=cocina.hay_recetas(),
    )


@router.patch("/yo", response_model=MiembroSalida)
def mi_nombre(entrada: NombreEntrada, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    yo = casa.asegurar_casa(db, user_id)
    try:
        if entrada.nombre is not None:
            yo = casa.cambiar_nombre(db, user_id, entrada.nombre)
        if entrada.efectivo is not None:
            yo = casa.pago_habitual(db, user_id, entrada.efectivo)
        return yo
    except _ERRORES as exc:
        raise _error(exc) from exc


@router.post("/invitacion", response_model=InvitacionSalida)
def invitar(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    try:
        return InvitacionSalida(codigo=casa.crear_invitacion(db, user_id), dias=casa.DIAS_INVITACION)
    except _ERRORES as exc:
        raise _error(exc) from exc


@router.get("/invitacion/{codigo}", response_model=InvitacionVista)
def ver_invitacion(codigo: str, db: Session = Depends(get_db)):
    try:
        hogar, gente = casa.ver_invitacion(db, codigo)
    except _ERRORES as exc:
        raise _error(exc) from exc
    return InvitacionVista(casa=hogar.nombre, miembros=[m.nombre for m in gente])


@router.post("/unirse", response_model=UnirseSalida)
def unirse(entrada: UnirseEntrada, db: Session = Depends(get_db)):
    try:
        _, token = casa.unirse_por_web(db, entrada.codigo, entrada.nombre)
    except _ERRORES as exc:
        raise _error(exc) from exc
    return UnirseSalida(token=token)


@router.delete("/miembros/{miembro_id}", status_code=status.HTTP_204_NO_CONTENT)
def quitar(miembro_id: int, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    try:
        casa.quitar_miembro(db, user_id, miembro_id)
    except _ERRORES as exc:
        raise _error(exc) from exc


# --- Gastos -----------------------------------------------------------------


@router.get("/gastos", response_model=list[GastoCasaSalida])
def gastos(
    desde: date = Query(...),
    hasta: date = Query(...),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return casa.listar_gastos(db, user_id, desde, hasta)


@router.get("/resumen", response_model=ResumenCasaSalida)
def resumen(
    desde: date = Query(...),
    hasta: date = Query(...),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    if hasta < desde:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "el rango está al revés")
    return casa.resumen(db, user_id, desde, hasta)


@router.post("/gastos", response_model=GastoCasaSalida, status_code=status.HTTP_201_CREATED)
def crear_gasto(entrada: GastoCasaEntrada, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    try:
        return casa.crear_gasto(db, user_id, origen="web", **entrada.model_dump())
    except _ERRORES as exc:
        raise _error(exc) from exc


@router.post("/gastos/texto", response_model=GastoCasaSalida, status_code=status.HTTP_201_CREATED)
def gasto_escrito(entrada: GastoCasaTexto, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """"-45 súper", "pagué 60 de luz": la misma forma de escribir que en el bot."""
    try:
        gasto = casa.anotar_texto(db, user_id, entrada.texto, origen="web")
    except _ERRORES as exc:
        raise _error(exc) from exc
    if not gasto:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "no veo el importe: escribe por ejemplo «45 súper»")
    return gasto


@router.patch("/gastos/{gasto_id}", response_model=GastoCasaSalida)
def cambiar_gasto(
    gasto_id: int,
    cambios: GastoCasaCambios,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        return casa.actualizar_gasto(db, user_id, gasto_id, cambios.model_dump(exclude_unset=True, exclude_none=True))
    except _ERRORES as exc:
        raise _error(exc) from exc


@router.delete("/gastos/{gasto_id}", status_code=status.HTTP_204_NO_CONTENT)
def borrar_gasto(gasto_id: int, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    try:
        casa.borrar_gasto(db, user_id, gasto_id)
    except _ERRORES as exc:
        raise _error(exc) from exc


# --- Lista y despensa -------------------------------------------------------


@router.get("/lista", response_model=list[ArticuloSalida])
def lista(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    return casa.listar_articulos(db, user_id)


@router.post("/lista", response_model=list[ArticuloSalida], status_code=status.HTTP_201_CREATED)
def anadir(entrada: ArticuloEntrada, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Admite varias cosas de golpe: "leche, huevos y pan"."""
    articulos = reglas.articulos_de(entrada.texto)
    if not articulos:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "escribe qué falta")
    return casa.anadir(db, user_id, articulos)


@router.patch("/lista/{articulo_id}", response_model=ArticuloSalida)
def cambiar_articulo(
    articulo_id: int,
    cambios: ArticuloCambios,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        articulo = None
        if cambios.texto is not None:
            articulo = casa.renombrar_articulo(db, user_id, articulo_id, cambios.texto)
        if cambios.hay is not None:
            articulo = casa.marcar(db, user_id, articulo_id, cambios.hay)
        if articulo is None:
            raise casa.DatoNoValido("no has dicho qué cambiar")
        return articulo
    except _ERRORES as exc:
        raise _error(exc) from exc


@router.delete("/lista/{articulo_id}", status_code=status.HTTP_204_NO_CONTENT)
def borrar_articulo(articulo_id: int, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    try:
        casa.borrar_articulo(db, user_id, articulo_id)
    except _ERRORES as exc:
        raise _error(exc) from exc


@router.post("/recetas", response_model=list[RecetaSalida])
async def recetas(entrada: RecetasEntrada, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    try:
        return await casa.sugerir_recetas(db, user_id, entrada.preferencias)
    except _ERRORES as exc:
        raise _error(exc) from exc
    except cocina.RecetasNoDisponibles as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "las recetas necesitan la clave de OpenAI") from exc
    except cocina.ErrorDeRecetas as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "no he podido pensar recetas ahora, prueba otra vez") from exc


# --- Carteras ---------------------------------------------------------------


@router.get("/carteras", response_model=list[CarteraSalida])
def carteras(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """La de cada uno: lo que debería haber desde que se contó."""
    return casa.carteras(db, user_id)


@router.get("/cartera/movimientos", response_model=list[MovimientoCarteraSalida])
def movimientos(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    casa.asegurar_casa(db, user_id)
    return casa.movimientos_cartera(db, user_id)


@router.post("/cartera/entrada", response_model=MovimientoCarteraSalida, status_code=status.HTTP_201_CREATED)
def entrada(datos: ImporteEntrada, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Lo que entra en tu cartera: lo que sacas del cajero, lo que te dan."""
    try:
        return casa.meter_en_cartera(db, user_id, datos.importe)
    except _ERRORES as exc:
        raise _error(exc) from exc


@router.post("/cartera/recuento", response_model=RecuentoSalida, status_code=status.HTTP_201_CREATED)
def recuento(datos: ImporteEntrada, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Lo que te queda al contar. Lo que falte sin apuntar entra como "Efectivo sin detallar"."""
    try:
        return casa.contar_cartera(db, user_id, datos.importe)
    except _ERRORES as exc:
        raise _error(exc) from exc


@router.delete("/cartera/{movimiento_id}", status_code=status.HTTP_204_NO_CONTENT)
def deshacer(movimiento_id: int, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    try:
        casa.deshacer_movimiento(db, user_id, movimiento_id)
    except _ERRORES as exc:
        raise _error(exc) from exc
