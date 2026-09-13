"""Casos de uso de los hábitos: crearlos, marcar un día y ver cómo van.

Las reglas (qué día toca, rachas, cumplimiento) están en `dominio/habitos.py`.
Aquí se leen y escriben las filas y se juntan con esas reglas. La web y el
bot llaman a lo mismo: marcar "beber agua" desde Telegram tiene que verse al
momento en la web, y con la misma racha.

Los recordatorios también se deciden aquí y no en el bot: a quién, cuándo y
cuándo ya no. El bot solo manda lo que le digan.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from app.dominio import habitos as reglas
from app.dominio.models import Habito, HabitoHecho
from app.nucleo.tiempo import hoy_local
from app.servicios.avisos import avisos_activos

# Un recordatorio que llega tarde es ruido. Si el proceso estuvo caído, o el
# hábito se creó a las 15:00 con hora a las 7:05, no se manda nada hoy.
VENTANA_RECORDATORIO = timedelta(minutes=30)

_SIN_TOCAR = object()  # None es un valor válido: "quítale el recordatorio"


class HabitoNoEncontrado(LookupError):
    """No existe ese hábito para ese usuario."""


class DiaNoMarcable(ValueError):
    """Un día que aún no ha llegado, o uno en el que el hábito no toca."""


@dataclass
class ResumenHabito:
    """Lo que enseña la lista: la semana, la racha y si hoy ya está."""

    habito: Habito
    semana: list[reglas.Dia]
    racha: int
    toca_hoy: bool
    hecho_hoy: bool


@dataclass
class DetalleHabito:
    habito: Habito
    racha: int
    mejor_racha: int
    cumplidos: int
    programados: int
    anio: int
    mes: int
    dias_del_mes: list[reglas.Dia]

    @property
    def porcentaje(self) -> int:
        return round(100 * self.cumplidos / self.programados) if self.programados else 0


def _suyo(db: Session, user_id: int, habito_id: int) -> Habito:
    habito = (
        db.query(Habito).filter(Habito.id == habito_id, Habito.user_id == user_id).first()
    )
    if habito is None:
        raise HabitoNoEncontrado(f"el hábito {habito_id} no existe para {user_id}")
    return habito


def _hechos(habito: Habito) -> set[date]:
    return {hecho.fecha for hecho in habito.hechos}


def _inicio(habito: Habito, hechos: set[date]) -> date:
    # Si se marcan días de antes de crearlo ("llevo toda la semana bebiendo
    # agua"), el hábito empieza ahí: si no, esos días no contarían.
    return min([habito.inicio, *hechos])


def _resumen(habito: Habito, hoy: date) -> ResumenHabito:
    dias = reglas.dias_desde_texto(habito.dias)
    hechos = _hechos(habito)
    inicio = _inicio(habito, hechos)
    return ResumenHabito(
        habito=habito,
        semana=reglas.semana(dias, hechos, inicio, hoy),
        racha=reglas.racha_actual(dias, hechos, inicio, hoy),
        toca_hoy=reglas.toca(dias, hoy),
        hecho_hoy=hoy in hechos,
    )


def crear(
    db: Session, user_id: int, nombre: str, dias, recordar_a: time | None = None
) -> Habito:
    limpio = nombre.strip()
    if not limpio:
        raise ValueError("un hábito necesita un nombre")
    habito = Habito(
        user_id=user_id,
        nombre=limpio,
        dias=reglas.dias_a_texto(dias),
        inicio=hoy_local(),
        recordar_a=recordar_a,
    )
    db.add(habito)
    db.commit()
    db.refresh(habito)
    return habito


def listar(db: Session, user_id: int) -> list[ResumenHabito]:
    hoy = hoy_local()
    habitos = db.query(Habito).filter(Habito.user_id == user_id).order_by(Habito.id).all()
    return [_resumen(habito, hoy) for habito in habitos]


def resumen(db: Session, user_id: int, habito_id: int) -> ResumenHabito:
    return _resumen(_suyo(db, user_id, habito_id), hoy_local())


def editar(
    db: Session,
    user_id: int,
    habito_id: int,
    nombre: str | None = None,
    dias=None,
    recordar_a=_SIN_TOCAR,
) -> Habito:
    habito = _suyo(db, user_id, habito_id)
    if nombre is not None:
        if not nombre.strip():
            raise ValueError("un hábito necesita un nombre")
        habito.nombre = nombre.strip()
    if dias is not None:
        habito.dias = reglas.dias_a_texto(dias)
    if recordar_a is not _SIN_TOCAR and recordar_a != habito.recordar_a:
        habito.recordar_a = recordar_a
        # Hora nueva, recordatorio nuevo: si ya se avisó hoy a las 9 y ahora
        # se pone a las 18, a las 18 tiene que llegar.
        habito.recordado_el = None
    db.commit()
    db.refresh(habito)
    return habito


def borrar(db: Session, user_id: int, habito_id: int) -> None:
    db.delete(_suyo(db, user_id, habito_id))
    db.commit()


def marcar(
    db: Session, user_id: int, habito_id: int, fecha: date | None = None, hecho: bool = True
) -> ResumenHabito:
    """Marca o desmarca un día. Sin fecha, hoy.

    Marcar dos veces el mismo día no hace nada la segunda: la racha no
    puede subir por tocar dos veces el círculo.
    """
    habito = _suyo(db, user_id, habito_id)
    hoy = hoy_local()
    dia = fecha or hoy
    if dia > hoy:
        raise DiaNoMarcable("no se puede marcar un día que aún no ha llegado")
    if not reglas.toca(reglas.dias_desde_texto(habito.dias), dia):
        raise DiaNoMarcable("ese día no le toca a este hábito")

    existente = next((h for h in habito.hechos if h.fecha == dia), None)
    if hecho and existente is None:
        habito.hechos.append(HabitoHecho(fecha=dia))
    elif not hecho and existente is not None:
        habito.hechos.remove(existente)
    db.commit()
    db.refresh(habito)
    return _resumen(habito, hoy)


def alternar_hoy(db: Session, user_id: int, habito_id: int) -> ResumenHabito:
    """Lo que hace el botón del bot: si estaba hecho se desmarca, y al revés."""
    habito = _suyo(db, user_id, habito_id)
    return marcar(db, user_id, habito_id, hecho=hoy_local() not in _hechos(habito))


def detalle(
    db: Session, user_id: int, habito_id: int, anio: int | None = None, mes: int | None = None
) -> DetalleHabito:
    habito = _suyo(db, user_id, habito_id)
    hoy = hoy_local()
    anio, mes = anio or hoy.year, mes or hoy.month
    dias = reglas.dias_desde_texto(habito.dias)
    hechos = _hechos(habito)
    inicio = _inicio(habito, hechos)
    cumplidos, programados = reglas.cumplimiento(dias, hechos, inicio, hoy)
    return DetalleHabito(
        habito=habito,
        racha=reglas.racha_actual(dias, hechos, inicio, hoy),
        mejor_racha=reglas.mejor_racha(dias, hechos, inicio, hoy),
        cumplidos=cumplidos,
        programados=programados,
        anio=anio,
        mes=mes,
        dias_del_mes=reglas.dias_del_mes(dias, hechos, inicio, hoy, anio, mes),
    )


def recordatorios_debidos(db: Session, ahora: datetime) -> list[Habito]:
    """Los hábitos a los que hay que recordar ahora mismo.

    Tienen hora, hoy les toca, no están hechos, no se les ha recordado ya
    hoy, y su hora llegó hace menos de `VENTANA_RECORDATORIO`. Nunca a quien
    apagó los avisos con /avisos off: ese interruptor es para todo.

    `ahora` tiene que venir en hora local: la hora del recordatorio es la
    del reloj de quien lo puso, no la del servidor.
    """
    hoy = ahora.date()
    en_punto = ahora.replace(tzinfo=None)
    candidatos = db.query(Habito).filter(Habito.recordar_a.isnot(None)).all()

    debidos = []
    for habito in candidatos:
        if habito.recordado_el == hoy:
            continue
        if not reglas.toca(reglas.dias_desde_texto(habito.dias), hoy):
            continue
        momento = datetime.combine(hoy, habito.recordar_a)
        if not momento <= en_punto < momento + VENTANA_RECORDATORIO:
            continue
        if hoy in _hechos(habito):
            continue
        if not avisos_activos(db, habito.user_id):
            continue
        debidos.append(habito)
    return debidos


def marcar_recordado(db: Session, habito: Habito, dia: date) -> None:
    habito.recordado_el = dia
    db.commit()
