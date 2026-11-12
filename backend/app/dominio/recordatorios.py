"""Cuándo se recuerda una cita el mismo día. Reglas puras, sin base de datos.

El aviso de las 21:00 cuenta las citas de mañana, pero el día de la cita no
decía nada: una cita a las 14:00 apuntada la semana pasada se olvidaba igual.

- Con hora: se avisa `antelacion` antes, y se puede avisar hasta la hora
  misma. Si el bot estaba reiniciándose a las 13:00, a las 13:20 todavía sirve;
  a las 14:05 ya no, y un aviso tarde es ruido.
- Sin hora: a primera hora (`hora_sin_hora`), con media hora de margen, como
  los recordatorios de hábitos.
- Solo el primer día de una cita de varios días: es cuando hay que acordarse
  de ir. Los siguientes ya se está metido en ella.
"""
from datetime import date, datetime, time, timedelta

MARGEN_SIN_HORA = timedelta(minutes=30)


def ventana_del_aviso(
    fecha: date, hora: time | None, antelacion: timedelta, hora_sin_hora: time
) -> tuple[datetime, datetime]:
    """Desde cuándo y hasta cuándo (sin incluir) tiene sentido avisar."""
    if hora is None:
        inicio = datetime.combine(fecha, hora_sin_hora)
        return inicio, inicio + MARGEN_SIN_HORA
    empieza = datetime.combine(fecha, hora)
    return empieza - antelacion, empieza


def toca_avisar(
    ahora: datetime,
    fecha: date,
    hora: time | None,
    hecha: bool,
    avisada_el: date | None,
    antelacion: timedelta,
    hora_sin_hora: time,
) -> bool:
    """`ahora` en hora local y sin zona: la hora de la cita es la del reloj de Yoa."""
    if hecha or avisada_el == fecha or ahora.date() != fecha:
        return False
    inicio, fin = ventana_del_aviso(fecha, hora, antelacion, hora_sin_hora)
    return inicio <= ahora < fin
