"""Los movimientos de Finanzas: el periodo exacto, sin notas, y solo los tuyos.

Lo que se rompería en silencio: un gasto del día 1 o del 31 que no sale (el
rango tiene que incluir los dos extremos), o una nota que aparece como 0 €.
"""
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.dominio.models import Apunte
from app.main import crear_api
from app.servicios.auth import generar_token
from tests.conftest import USUARIO


def _apunte(db, fecha, tipo="gasto", importe="10", user_id=USUARIO):
    db.add(Apunte(user_id=user_id, fecha=fecha, tipo=tipo, concepto=f"{tipo} {fecha}",
                  importe=Decimal(importe), pendiente=False, origen="web"))
    db.commit()


@pytest.fixture
def cliente():
    with TestClient(crear_api()) as c:
        yield c


def test_el_mes_entero_con_sus_extremos_sin_notas_ni_ajenos(cliente, db):
    _apunte(db, date(2026, 10, 1))
    _apunte(db, date(2026, 10, 31), "trabajo", "120")
    _apunte(db, date(2026, 10, 15), "nota", "0")
    _apunte(db, date(2026, 9, 30))
    _apunte(db, date(2026, 11, 1))
    _apunte(db, date(2026, 10, 10), user_id=111)
    cab = {"Authorization": f"Bearer {generar_token(db, USUARIO)}"}

    r = cliente.get("/apuntes/rango?desde=2026-10-01&hasta=2026-10-31", headers=cab)
    assert r.status_code == 200
    datos = r.json()
    assert [a["fecha"] for a in datos] == ["2026-10-31", "2026-10-01"]  # reciente primero
    assert all(a["tipo"] != "nota" for a in datos)
    assert "factura_id" in datos[0]


def test_rango_al_reves_y_sin_token(cliente, db):
    cab = {"Authorization": f"Bearer {generar_token(db, USUARIO)}"}
    assert cliente.get("/apuntes/rango?desde=2026-10-31&hasta=2026-10-01", headers=cab).status_code == 422
    assert cliente.get("/apuntes/rango?desde=2026-10-01&hasta=2026-10-31").status_code == 401
