"""La ficha de un trabajo (obra): crear, cambiar, borrar y lo que tiene dentro.

Lo que se rompería en silencio: unas cuentas del trabajo que no cuadran con
lo que tiene dentro, borrar una obra y perder sus gastos o sus citas, una
nota o una cita que no hereda el cliente de la obra, o ver la obra de otro.
"""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import crear_api
from app.nucleo.tiempo import hoy_local
from app.servicios.auth import generar_token
from tests.conftest import USUARIO


@pytest.fixture
def c():
    with TestClient(crear_api()) as cliente:
        yield cliente


@pytest.fixture
def cab(db):
    return {"Authorization": f"Bearer {generar_token(db, USUARIO)}"}


def test_crear_cambiar_y_borrar_un_trabajo(c, cab):
    ana = c.post("/clientes", headers=cab, json={"nombre": "Ana Ruiz"}).json()
    r = c.post("/trabajos", headers=cab, json={"titulo": "  Reforma baño  ", "cliente_id": ana["id"]})
    assert r.status_code == 201
    obra = r.json()
    assert obra["titulo"] == "Reforma baño" and obra["cliente"]["nombre"] == "Ana Ruiz"
    assert obra["fecha_inicio"] == hoy_local().isoformat()  # sin decirlo, empieza hoy
    assert not obra["facturado"] and not obra["resena"] and obra["fecha_fin"] is None

    cambiada = c.patch(f"/trabajos/{obra['id']}", headers=cab, json={
        "fecha_fin": (hoy_local() + timedelta(days=3)).isoformat(), "resena": True, "facturado": True}).json()
    assert cambiada["resena"] and cambiada["facturado"] and cambiada["fecha_fin"]
    # Lo que no se manda no se toca; null lo vacía.
    sin_cliente = c.patch(f"/trabajos/{obra['id']}", headers=cab, json={"cliente_id": None}).json()
    assert sin_cliente["cliente_id"] is None and sin_cliente["resena"]

    assert c.delete(f"/trabajos/{obra['id']}", headers=cab).status_code == 204
    assert c.get(f"/trabajos/{obra['id']}", headers=cab).status_code == 404


def test_lo_que_no_tiene_sentido_da_422(c, cab):
    assert c.post("/trabajos", headers=cab, json={"titulo": "  "}).status_code == 422
    assert c.post("/trabajos", headers=cab, json={
        "titulo": "x", "fecha_inicio": "2026-10-10", "fecha_fin": "2026-10-01"}).status_code == 422
    assert c.post("/trabajos", headers=cab, json={"titulo": "x", "cliente_id": 99999}).status_code == 422
    assert c.get("/trabajos").status_code == 401


def test_la_ficha_junta_todo_y_hace_las_cuentas(c, cab):
    ana = c.post("/clientes", headers=cab, json={"nombre": "Ana Ruiz"}).json()
    obra = c.post("/trabajos", headers=cab, json={"titulo": "Cocina", "cliente_id": ana["id"]}).json()
    t = obra["id"]
    def mov(tipo, concepto, importe, pendiente=False):
        return c.post("/apuntes/movimiento", headers=cab, json={
            "tipo": tipo, "concepto": concepto, "importe": importe, "pendiente": pendiente,
            "trabajo_id": t}).json()
    mov("trabajo", "Señal", "500")
    mov("trabajo", "Resto", "1000", pendiente=True)
    mov("gasto", "Encimera", "320.40")
    mov("gasto", "Tornillos", "0.10")
    c.post("/apuntes/movimiento", headers=cab, json={"tipo": "gasto", "concepto": "Suelto", "importe": "9"})

    nota = c.post("/notas", headers=cab, json={"texto": "Pedir el grifo", "trabajo_id": t}).json()
    assert nota["trabajo_id"] == t and nota["cliente_id"] == ana["id"]  # hereda el cliente
    manana = (hoy_local() + timedelta(days=1)).isoformat()
    cita = c.post("/citas", headers=cab, json={"fecha": manana, "titulo": "Montar", "trabajo_id": t}).json()
    assert cita["trabajo_id"] == t and cita["cliente_id"] == ana["id"]
    # Agendar una nota de la obra deja la cita en la obra.
    agendada = c.post(f"/notas/{nota['id']}/agendar", headers=cab, json={"fecha": manana}).json()
    assert agendada["trabajo_id"] == t

    ficha = c.get(f"/trabajos/{t}", headers=cab).json()
    assert ficha["cuentas"] == {"cobrado": "500.00", "pendiente": "1000.00", "gastos": "320.50",
                                "ingresos": "1500.00", "beneficio": "1179.50"}
    assert [m["concepto"] for m in ficha["movimientos"]] and len(ficha["movimientos"]) == 4
    assert [x["titulo"] for x in ficha["citas"]] == ["Montar", "Pedir el grifo"]

    listado = c.get("/trabajos", headers=cab).json()
    assert len(listado) == 1 and listado[0]["cuentas"]["beneficio"] == "1179.50"
    assert listado[0]["proxima_cita"]["fecha"] == manana


def test_borrar_la_obra_no_borra_lo_de_dentro(c, cab, db):
    obra = c.post("/trabajos", headers=cab, json={"titulo": "Cocina"}).json()
    gasto = c.post("/apuntes/movimiento", headers=cab, json={
        "tipo": "gasto", "concepto": "Encimera", "importe": "320", "trabajo_id": obra["id"]}).json()
    cita = c.post("/citas", headers=cab, json={
        "fecha": hoy_local().isoformat(), "titulo": "Medir", "trabajo_id": obra["id"]}).json()
    c.delete(f"/trabajos/{obra['id']}", headers=cab)

    gastos = c.get(f"/apuntes/rango?desde=2020-01-01&hasta={hoy_local()}", headers=cab).json()
    assert [g["id"] for g in gastos] == [gasto["id"]] and gastos[0]["trabajo_id"] is None
    citas = c.get(f"/citas?fecha={hoy_local()}", headers=cab).json()
    assert citas[0]["id"] == cita["id"] and citas[0]["trabajo_id"] is None


def test_mover_una_cita_a_otro_trabajo_o_sacarla(c, cab):
    obra = c.post("/trabajos", headers=cab, json={"titulo": "Cocina"}).json()
    cita = c.post("/citas", headers=cab, json={"fecha": "2026-12-01", "titulo": "Medir"}).json()
    assert c.patch(f"/citas/{cita['id']}", headers=cab, json={"trabajo_id": obra["id"]}).json()["trabajo_id"] == obra["id"]
    assert c.patch(f"/citas/{cita['id']}", headers=cab, json={"trabajo_id": 99999}).status_code == 404
    assert c.patch(f"/citas/{cita['id']}", headers=cab, json={"trabajo_id": None}).json()["trabajo_id"] is None
