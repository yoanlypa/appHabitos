"""Las reglas de los hábitos: qué días tocan, rachas y cumplimiento.

Funciones puras, sin base de datos. Reciben los días en que toca, las
fechas en que se hizo, el día en que empezó y el día de hoy. Así se prueban
con fechas inventadas, sin esperar a que pase una semana.

Dos reglas deciden si la racha anima o desanima:

- Un día que no toca no rompe nada. Entrenar de lunes a viernes no pierde la
  racha por descansar el sábado.
- Hoy sin marcar tampoco rompe nada mientras no acabe el día. Si lo hiciera,
  la racha amanecería rota cada mañana y marcar sería reparar en vez de sumar.

Los días de antes de empezar no cuentan como fallados: no se puede fallar
algo que todavía no existía.
"""
from dataclasses import dataclass
from datetime import date, timedelta

TODOS_LOS_DIAS = frozenset(range(7))  # 0 es lunes, como en Python
_UN_DIA = timedelta(days=1)

# Estados de un día. Los mismos para los círculos de la semana y para el
# calendario del detalle, así las dos vistas no pueden contar cosas distintas.
HECHO = "hecho"
HOY = "hoy"  # toca hoy y aún no está hecho
FALLADO = "fallado"  # tocaba, ya pasó y no se hizo
FUTURO = "futuro"  # toca, pero todavía no ha llegado
NO_TOCA = "no_toca"
ANTES = "antes"  # tocaría, pero el hábito aún no existía


class DiasNoValidos(ValueError):
    """Un hábito tiene que tocar al menos un día, del 0 (lunes) al 6 (domingo)."""


@dataclass(frozen=True)
class Dia:
    fecha: date
    estado: str


def dias_desde_texto(texto: str) -> frozenset[int]:
    """Los días se guardan como texto de dígitos: "01234" es de lunes a viernes."""
    return frozenset(int(caracter) for caracter in texto if caracter.isdigit())


def dias_a_texto(dias) -> str:
    conjunto = set(dias)
    if not conjunto:
        raise DiasNoValidos("un hábito tiene que tocar algún día")
    if any(dia not in TODOS_LOS_DIAS for dia in conjunto):
        raise DiasNoValidos("los días van del 0 (lunes) al 6 (domingo)")
    return "".join(str(dia) for dia in sorted(conjunto))


def toca(dias: frozenset[int], fecha: date) -> bool:
    return fecha.weekday() in dias


def estado_del_dia(
    dias: frozenset[int], hechos: set[date], inicio: date, hoy: date, fecha: date
) -> str:
    if fecha in hechos:
        return HECHO
    if not toca(dias, fecha):
        return NO_TOCA
    if fecha > hoy:
        return FUTURO
    if fecha == hoy:
        return HOY
    if fecha < inicio:
        return ANTES
    return FALLADO


def racha_actual(dias: frozenset[int], hechos: set[date], inicio: date, hoy: date) -> int:
    """Días que tocaban, seguidos y cumplidos, contando hacia atrás desde hoy."""
    racha = 0
    dia = hoy
    if toca(dias, hoy) and hoy not in hechos:
        dia -= _UN_DIA  # hoy aún está a tiempo: se empieza a contar por ayer
    while dia >= inicio:
        if toca(dias, dia):
            if dia not in hechos:
                break
            racha += 1
        dia -= _UN_DIA
    return racha


def mejor_racha(dias: frozenset[int], hechos: set[date], inicio: date, hoy: date) -> int:
    mejor = actual = 0
    dia = inicio
    while dia <= hoy:
        if toca(dias, dia):
            if dia in hechos:
                actual += 1
                mejor = max(mejor, actual)
            elif dia != hoy:
                actual = 0
        dia += _UN_DIA
    return mejor


def cumplimiento(
    dias: frozenset[int], hechos: set[date], inicio: date, hoy: date
) -> tuple[int, int]:
    """(cumplidos, programados) desde que empezó.

    Hoy solo cuenta si ya está hecho. Si contara sin hacer, el primer día de
    un hábito nuevo saldría con un 0%, que es la peor bienvenida posible.
    """
    cumplidos = programados = 0
    dia = inicio
    while dia <= hoy:
        if toca(dias, dia):
            if dia in hechos:
                cumplidos += 1
                programados += 1
            elif dia != hoy:
                programados += 1
        dia += _UN_DIA
    return cumplidos, programados


def semana(dias: frozenset[int], hechos: set[date], inicio: date, hoy: date) -> list[Dia]:
    """De lunes a domingo de la semana de hoy: los círculos de la lista."""
    lunes = hoy - timedelta(days=hoy.weekday())
    fechas = (lunes + timedelta(days=i) for i in range(7))
    return [Dia(fecha, estado_del_dia(dias, hechos, inicio, hoy, fecha)) for fecha in fechas]


def dias_del_mes(
    dias: frozenset[int], hechos: set[date], inicio: date, hoy: date, anio: int, mes: int
) -> list[Dia]:
    """Todos los días del mes con su estado: el calendario del detalle."""
    fecha = date(anio, mes, 1)
    resultado = []
    while fecha.month == mes:
        resultado.append(Dia(fecha, estado_del_dia(dias, hechos, inicio, hoy, fecha)))
        fecha += _UN_DIA
    return resultado
