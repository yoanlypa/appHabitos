"""Router de importación: varios movimientos de golpe desde la web.

Adaptador fino sobre `servicios/importacion.py`, el mismo que usa el bot.
Va en tres llamadas porque leer una captura cuesta dinero y no se repite:

1. `POST /importar/leer`: un fichero (CSV, Excel, captura) o un texto pegado
   → los movimientos leídos, con cuáles parecen estar ya. No guarda nada.
2. `POST /importar/revisar`: los mismos movimientos con el tipo elegido
   (cuando la tabla no decía si eran gastos o cobros) → otra vez marcados.
3. `POST /importar`: los elegidos → entran. Y `POST /importar/deshacer`
   quita lo recién importado.
"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.dependencias import get_current_user_id
from app.api.schemas import (
    ConfirmarImportacion,
    Deshecha,
    DeshacerImportacion,
    ImportacionHecha,
    LecturaImportacion,
    MovimientoImportado,
    RevisarImportacion,
)
from app.dominio.importacion import ImportacionNoValida, Movimiento
from app.nucleo.db import get_db
from app.nucleo.lectura_tickets import ErrorDeLectura, LecturaNoDisponible
from app.servicios.importacion import (
    borrar_importados,
    con_tipo,
    falta_el_tipo,
    importar,
    leer_entrada,
    planificar,
    repetidos,
)

router = APIRouter(prefix="/importar", tags=["importar"])

# Una lista de movimientos no llega ni a un mega; una captura, unos pocos.
TAMANO_MAXIMO = 10 * 1024 * 1024
_TIPOS = {"trabajo", "gasto"}


def _a_dominio(m: MovimientoImportado) -> Movimiento:
    if m.tipo is not None and m.tipo not in _TIPOS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"tipo '{m.tipo}' no válido")
    if m.importe <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "un importe tiene que ser mayor que cero")
    if not m.concepto.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "hay un movimiento sin concepto")
    return Movimiento(
        fecha=m.fecha, tipo=m.tipo, concepto=m.concepto.strip(), importe=m.importe, pendiente=m.pendiente
    )


def _lectura(db: Session, user_id: int, movimientos: list[Movimiento]) -> LecturaImportacion:
    marcas = repetidos(db, user_id, movimientos)
    return LecturaImportacion(
        movimientos=[
            MovimientoImportado(
                fecha=m.fecha,
                tipo=m.tipo,
                concepto=m.concepto,
                importe=m.importe,
                pendiente=m.pendiente,
                repetido=repetido,
            )
            for m, repetido in zip(movimientos, marcas)
        ],
        falta_tipo=falta_el_tipo(movimientos),
    )


@router.post("/leer", response_model=LecturaImportacion)
async def leer(
    fichero: UploadFile | None = File(None),
    texto: str | None = Form(None),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    datos = None
    if fichero is not None:
        datos = await fichero.read(TAMANO_MAXIMO + 1)
        if len(datos) > TAMANO_MAXIMO:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "el fichero es demasiado grande")
    if not datos and not (texto or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "sube un fichero o escribe los movimientos")
    try:
        movimientos = await leer_entrada(
            fichero.filename if fichero else None,
            fichero.content_type if fichero else None,
            datos,
            texto,
        )
    except ImportacionNoValida as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except LecturaNoDisponible as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "No sé leer capturas: falta configurar OPENAI_API_KEY"
        ) from exc
    except ErrorDeLectura as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"No he podido leer la imagen: {exc}") from exc
    return _lectura(db, user_id, movimientos)


@router.post("/revisar", response_model=LecturaImportacion)
def revisar(
    entrada: RevisarImportacion,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    if entrada.tipo is not None and entrada.tipo not in _TIPOS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"tipo '{entrada.tipo}' no válido")
    movimientos = [_a_dominio(m) for m in entrada.movimientos]
    if entrada.tipo:
        movimientos = con_tipo(movimientos, entrada.tipo)
    return _lectura(db, user_id, movimientos)


@router.post("", response_model=ImportacionHecha, status_code=status.HTTP_201_CREATED)
def confirmar(
    entrada: ConfirmarImportacion,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    movimientos = [_a_dominio(m) for m in entrada.movimientos]
    if not movimientos:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "no has elegido ningún movimiento")
    ya_estaban = 0 if entrada.todo else len(planificar(db, user_id, movimientos).repetidos)
    try:
        apuntes = importar(db, user_id, movimientos, origen="web", todo=entrada.todo)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return ImportacionHecha(apuntes=apuntes, ya_estaban=ya_estaban)


@router.post("/deshacer", response_model=Deshecha)
def deshacer(
    entrada: DeshacerImportacion,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return Deshecha(borrados=borrar_importados(db, user_id, entrada.ids))
