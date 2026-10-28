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


def test_el_total_del_ano_es_la_suma_de_sus_meses(cliente, db):
    """Un periodo largo no puede contar distinto que sus trozos."""
    _apunte(db, date(2026, 1, 1), "trabajo", "100")
    _apunte(db, date(2026, 6, 15), "gasto", "30")
    _apunte(db, date(2026, 12, 31), "trabajo", "50")
    _apunte(db, date(2025, 12, 31), "trabajo", "999")  # año anterior: fuera
    cab = {"Authorization": f"Bearer {generar_token(db, USUARIO)}"}
    anio = cliente.get("/resumen/rango?desde=2026-01-01&hasta=2026-12-31", headers=cab).json()
    assert anio == {"cobrado": "150.00", "pendiente": "0.00", "gastos": "30.00", "neto": "120.00"}
    meses = [
        cliente.get(f"/resumen/mes?anio=2026&mes={m}", headers=cab).json()["neto"] for m in range(1, 13)
    ]
    assert sum(Decimal(n) for n in meses) == Decimal(anio["neto"])
    assert cliente.get("/resumen/rango?desde=2026-02-01&hasta=2026-01-01", headers=cab).status_code == 422


class TestEditarMovimientos:
    """Añadir, corregir y borrar desde Finanzas, sin colar nada absurdo."""

    def _cab(self, db):
        return {"Authorization": f"Bearer {generar_token(db, USUARIO)}"}

    def test_crear_con_fecha_y_concepto_con_numeros(self, cliente, db):
        r = cliente.post("/apuntes/movimiento", headers=self._cab(db), json={
            "tipo": "trabajo", "concepto": "Cambiar 2 grifos Ana", "importe": "90",
            "fecha": "2026-10-03", "pendiente": True,
        })
        assert r.status_code == 201
        a = r.json()
        # El "2" se queda en el concepto: aquí no hay parser que lo confunda.
        assert (a["concepto"], a["importe"], a["fecha"], a["pendiente"]) == (
            "Cambiar 2 grifos Ana", "90.00", "2026-10-03", True)

    def test_un_gasto_nunca_queda_pendiente_de_cobro(self, cliente, db):
        r = cliente.post("/apuntes/movimiento", headers=self._cab(db), json={
            "tipo": "gasto", "concepto": "Gasolina", "importe": "40", "pendiente": True})
        assert r.json()["pendiente"] is False

    @pytest.mark.parametrize("cuerpo", [
        {"tipo": "nota", "concepto": "x", "importe": "1"},
        {"tipo": "gasto", "concepto": "  ", "importe": "1"},
        {"tipo": "gasto", "concepto": "x", "importe": "0"},
        {"tipo": "gasto", "concepto": "x", "importe": "1", "fecha": "2099-01-01"},
    ])
    def test_lo_absurdo_da_422(self, cliente, db, cuerpo):
        assert cliente.post("/apuntes/movimiento", headers=self._cab(db), json=cuerpo).status_code == 422

    def test_cambiar_de_trabajo_a_gasto_quita_el_pendiente(self, cliente, db):
        cab = self._cab(db)
        a = cliente.post("/apuntes/movimiento", headers=cab, json={
            "tipo": "trabajo", "concepto": "Taladro", "importe": "89", "pendiente": True}).json()
        r = cliente.patch(f"/apuntes/{a['id']}", headers=cab, json={"tipo": "gasto", "importe": "79.90"})
        assert r.status_code == 200
        assert (r.json()["tipo"], r.json()["pendiente"], r.json()["importe"]) == ("gasto", False, "79.90")
        assert cliente.patch(f"/apuntes/{a['id']}", headers=cab, json={"importe": "-5"}).status_code == 422

    def test_borrar(self, cliente, db):
        cab = self._cab(db)
        a = cliente.post("/apuntes/movimiento", headers=cab, json={
            "tipo": "gasto", "concepto": "x", "importe": "1"}).json()
        assert cliente.delete(f"/apuntes/{a['id']}", headers=cab).status_code == 204
        assert cliente.delete(f"/apuntes/{a['id']}", headers=cab).status_code == 404
