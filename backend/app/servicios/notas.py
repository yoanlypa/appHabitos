"""El buzón de notas: lo apuntado que todavía no tiene ni fecha ni precio.

Una nota es un `Apunte` de tipo "nota" (importe 0), lo mismo que ya crea el
bot cuando se dicta algo sin importe. No hay tabla nueva a propósito: lo que
se escribe por Telegram y lo que se ve en la web tienen que ser la misma
fila, y en el momento en que fueran dos cosas distintas habría que
sincronizarlas.

El buzón solo guarda lo que no tiene fecha. En cuanto se le pone una, deja
de ser una nota y pasa a la agenda: por eso `agendar()` crea la cita y borra
la nota. Un buzón donde se queda todo deja de mirarse a la tercera semana.

Lo cumplido tampoco se borra: se marca. "Revisar el coche" cuando ya lo
revisaste no es un error del que haya que deshacerse, y borrarlo quitaría
la única prueba de que se hizo.
"""
from datetime import date, time

from sqlalchemy.orm import Session

from app.dominio.models import Apunte, Cita
from app.servicios.agenda import crear_cita
from app.servicios.apuntes import ApunteNoEncontrado, crear_nota
from app.servicios.clientes import clientes_mencionados


def _suya(db: Session, user_id: int, nota_id: int) -> Apunte:
    nota = (
        db.query(Apunte)
        .filter(Apunte.id == nota_id, Apunte.user_id == user_id, Apunte.tipo == "nota")
        .first()
    )
    if nota is None:
        raise ApunteNoEncontrado(f"la nota {nota_id} no existe para {user_id}")
    return nota


def listar_notas(db: Session, user_id: int, hechas: bool | None = False) -> list[Apunte]:
    """Sin filtrar por día: una nota sigue pendiente aunque sea de hace un mes.

    Por defecto solo lo que queda por hacer, que es para lo que se abre el
    buzón. `hechas=True` da las cumplidas y `hechas=None` las dos.

    De la más nueva a la más vieja, que es el orden en el que se buscan.
    """
    consulta = db.query(Apunte).filter(Apunte.user_id == user_id, Apunte.tipo == "nota")
    if hechas is not None:
        consulta = consulta.filter(Apunte.hecha.is_(hechas))
    return consulta.order_by(Apunte.id.desc()).all()


def contar_notas(db: Session, user_id: int) -> int:
    """Las que quedan por hacer: es lo que se cuenta en el aviso de la noche."""
    return (
        db.query(Apunte)
        .filter(Apunte.user_id == user_id, Apunte.tipo == "nota", Apunte.hecha.is_(False))
        .count()
    )


def marcar_hecha(db: Session, user_id: int, nota_id: int, hecha: bool = True) -> Apunte:
    """Marca una nota como cumplida, o la devuelve al buzón si se marcó sin querer."""
    nota = _suya(db, user_id, nota_id)
    nota.hecha = hecha
    db.commit()
    db.refresh(nota)
    return nota


def crear(db: Session, user_id: int, texto: str, origen: str) -> Apunte:
    """Una nota escrita a mano en el buzón.

    Aquí no se interpreta ningún importe aunque el texto acabe en número:
    "cambiar 2 grifos" es una tarea, no dos euros. Quien quiera anotar
    dinero lo hace desde la caja de "Hoy", que es la que interpreta.
    """
    if not texto.strip():
        raise ValueError("una nota en blanco no es nada")
    mencionados = clientes_mencionados(db, user_id, texto)
    unico = mencionados[0].id if len(mencionados) == 1 else None
    return crear_nota(db, user_id, texto, origen, cliente_id=unico)


def editar(db: Session, user_id: int, nota_id: int, texto: str) -> Apunte:
    nota = _suya(db, user_id, nota_id)
    if not texto.strip():
        raise ValueError("una nota en blanco no es nada")
    nota.concepto = texto.strip()
    db.commit()
    db.refresh(nota)
    return nota


def borrar(db: Session, user_id: int, nota_id: int) -> Apunte:
    nota = _suya(db, user_id, nota_id)
    db.delete(nota)
    db.commit()
    return nota


def agendar(
    db: Session,
    user_id: int,
    nota_id: int,
    fecha: date,
    fecha_fin: date | None = None,
    hora: time | None = None,
    titulo: str | None = None,
) -> Cita:
    """Le pone fecha a una nota: nace la cita y la nota sale del buzón.

    El cliente se hereda. Si la nota estaba colgada de Ana Ruiz, la cita
    también, y no hay que volver a decirlo.

    La nota se borra sólo después de que la cita esté guardada: si algo
    falla al crearla, lo apuntado sigue donde estaba.
    """
    nota = _suya(db, user_id, nota_id)
    cita = crear_cita(
        db,
        user_id,
        fecha,
        titulo if titulo and titulo.strip() else nota.concepto,
        hora=hora,
        cliente_id=nota.cliente_id,
        fecha_fin=fecha_fin,
    )
    db.delete(nota)
    db.commit()
    return cita
