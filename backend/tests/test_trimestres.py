"""El resumen por trimestre.

Los límites de fecha son el sitio donde más fácil es colar un error que no
se ve: un día de más o de menos mete o saca trabajos del periodo, y eso
cambia lo que se declara.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.servicios.apuntes import actualizar_apunte, crear_apunte
from app.servicios.trimestres import limites, resumen_trimestre, trimestre_de
from tests.conftest import USUARIO


@pytest.mark.parametrize(
    "trimestre,desde,hasta",
    [
        (1, date(2026, 1, 1), date(2026, 3, 31)),
        (2, date(2026, 4, 1), date(2026, 6, 30)),
        (3, date(2026, 7, 1), date(2026, 9, 30)),
        (4, date(2026, 10, 1), date(2026, 12, 31)),
    ],
)
def test_los_limites_de_cada_trimestre(trimestre, desde, hasta):
    assert limites(2026, trimestre) == (desde, hasta)


def test_febrero_bisiesto_no_descoloca_el_primer_trimestre():
    assert limites(2028, 1) == (date(2028, 1, 1), date(2028, 3, 31))


@pytest.mark.parametrize(
    "fecha,esperado",
    [
        (date(2026, 1, 1), 1),
        (date(2026, 3, 31), 1),
        (date(2026, 4, 1), 2),
        (date(2026, 9, 30), 3),
        (date(2026, 10, 1), 4),
        (date(2026, 12, 31), 4),
    ],
)
def test_a_que_trimestre_pertenece_una_fecha(fecha, esperado):
    assert trimestre_de(fecha) == esperado


def test_un_trimestre_que_no_existe(db):
    with pytest.raises(ValueError):
        resumen_trimestre(db, USUARIO, 2026, 5)


def test_solo_entra_lo_del_periodo(db):
    """Un trabajo del último día del trimestre cuenta; el del día siguiente no."""
    dentro = crear_apunte(db, USUARIO, "Dentro 100", origen="web")
    actualizar_apunte(db, USUARIO, dentro.id, fecha=date(2026, 3, 31))

    fuera = crear_apunte(db, USUARIO, "Fuera 500", origen="web")
    actualizar_apunte(db, USUARIO, fuera.id, fecha=date(2026, 4, 1))

    primero = resumen_trimestre(db, USUARIO, 2026, 1)
    assert primero.cobrado == Decimal("100")

    segundo = resumen_trimestre(db, USUARIO, 2026, 2)
    assert segundo.cobrado == Decimal("500")


def test_lo_pendiente_no_cuenta_como_cobrado(db):
    """Se declara lo que ha entrado, no lo que está por cobrar."""
    cobrado = crear_apunte(db, USUARIO, "Cobrado 1000", origen="web")
    actualizar_apunte(db, USUARIO, cobrado.id, fecha=date(2026, 2, 1))
    pendiente = crear_apunte(db, USUARIO, "pendiente Sin cobrar 900", origen="web")
    actualizar_apunte(db, USUARIO, pendiente.id, fecha=date(2026, 2, 1))

    r = resumen_trimestre(db, USUARIO, 2026, 1)
    assert r.cobrado == Decimal("1000")
    assert r.pendiente == Decimal("900")
    assert r.neto == Decimal("1000"), "el pendiente no infla el neto"


def test_la_estimacion_es_el_20_por_ciento_del_neto(db):
    ingreso = crear_apunte(db, USUARIO, "Trabajo 1000", origen="web")
    actualizar_apunte(db, USUARIO, ingreso.id, fecha=date(2026, 2, 1))
    gasto = crear_apunte(db, USUARIO, "-200 material", origen="web")
    actualizar_apunte(db, USUARIO, gasto.id, fecha=date(2026, 2, 1))

    r = resumen_trimestre(db, USUARIO, 2026, 1)
    assert r.neto == Decimal("800")
    assert r.estimacion_130 == Decimal("160.00")


def test_si_el_trimestre_sale_en_perdidas_no_se_paga_nada(db):
    """Un 130 negativo no existe: sería el Estado pagándote a ti."""
    gasto = crear_apunte(db, USUARIO, "-500 material", origen="web")
    actualizar_apunte(db, USUARIO, gasto.id, fecha=date(2026, 2, 1))

    r = resumen_trimestre(db, USUARIO, 2026, 1)
    assert r.neto == Decimal("-500")
    assert r.estimacion_130 == Decimal("0.00")
