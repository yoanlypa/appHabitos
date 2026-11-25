"""Importar varios movimientos desde la web: las mismas reglas que en el bot.

Lo que se prueba es lo que se notaría tarde: que algo entre sin haberlo
confirmado, que lo repetido entre dos veces, que una tabla sin tipo se tome
por cobros sin preguntar, o que una copia de seguridad se importe como si
fuera una lista (y se salte sus reglas para no duplicar).
"""
import io
from datetime import timedelta
from decimal import Decimal

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.dominio.models import Apunte
from app.main import crear_api
from app.nucleo.tiempo import hoy_local
from app.servicios import importacion
from app.servicios.apuntes import crear_apunte
from app.servicios.auth import generar_token
from app.servicios.copia_completa import generar
from tests.conftest import USUARIO

HOY = hoy_local()
AYER = HOY - timedelta(days=1)


@pytest.fixture
def cliente():
    with TestClient(crear_api()) as c:
        yield c


@pytest.fixture
def cabeceras(db):
    return {"Authorization": f"Bearer {generar_token(db, USUARIO)}"}


def _leer_texto(cliente, cabeceras, texto):
    return cliente.post("/importar/leer", data={"texto": texto}, headers=cabeceras)


def _leer_fichero(cliente, cabeceras, nombre, datos, mime):
    return cliente.post("/importar/leer", files={"fichero": (nombre, datos, mime)}, headers=cabeceras)


class TestLeer:
    def test_varias_lineas_se_leen_y_no_se_guarda_nada(self, cliente, cabeceras, db):
        r = _leer_texto(cliente, cabeceras, "ayer -45 gasolina\n-2,75 parking\nCambio de grifo 120")
        assert r.status_code == 200, r.text
        cuerpo = r.json()
        assert [(m["tipo"], m["concepto"], m["importe"]) for m in cuerpo["movimientos"]] == [
            ("gasto", "gasolina", "45.00"),
            ("gasto", "parking", "2.75"),
            ("trabajo", "Cambio de grifo", "120.00"),
        ]
        assert cuerpo["movimientos"][0]["fecha"] == AYER.isoformat()
        assert db.query(Apunte).count() == 0, "leer no guarda"

    def test_una_linea_sola_no_es_una_lista(self, cliente, cabeceras):
        r = _leer_texto(cliente, cabeceras, "-45 gasolina")
        assert r.status_code == 422
        assert "al menos dos" in r.json()["detail"]

    def test_lo_que_ya_esta_sale_marcado(self, cliente, cabeceras, db):
        crear_apunte(db, USUARIO, "-45 gasolina", origen="bot")
        r = _leer_texto(cliente, cabeceras, "-45 repsol\n-3 parking")
        marcas = [m["repetido"] for m in r.json()["movimientos"]]
        assert marcas == [True, False], "mismo día, tipo e importe: el concepto no cuenta"

    def test_un_csv_sin_tipo_y_todo_positivo_pregunta(self, cliente, cabeceras):
        csv = f"fecha,concepto,importe\n{AYER.strftime('%d/%m/%Y')},Parking,2.75\n{HOY.strftime('%d/%m/%Y')},Gasolina,45\n"
        r = _leer_fichero(cliente, cabeceras, "extracto.csv", csv.encode(), "text/csv")
        cuerpo = r.json()
        assert cuerpo["falta_tipo"] is True
        assert all(m["tipo"] is None for m in cuerpo["movimientos"]), "nunca se supone"

        r = cliente.post(
            "/importar/revisar",
            json={"movimientos": cuerpo["movimientos"], "tipo": "gasto"},
            headers=cabeceras,
        )
        assert r.json()["falta_tipo"] is False
        assert {m["tipo"] for m in r.json()["movimientos"]} == {"gasto"}

    def test_un_excel(self, cliente, cabeceras):
        libro = openpyxl.Workbook()
        hoja = libro.active
        hoja.append(["Fecha", "Concepto", "Importe"])
        hoja.append([AYER, "Parking", -2.75])
        hoja.append([HOY, "Pago cliente", 300])
        salida = io.BytesIO()
        libro.save(salida)

        r = _leer_fichero(
            cliente, cabeceras, "movimientos.xlsx", salida.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        assert r.status_code == 200, r.text
        assert [m["tipo"] for m in r.json()["movimientos"]] == ["gasto", "trabajo"]

    def test_una_copia_de_seguridad_no_se_importa(self, cliente, cabeceras, db):
        crear_apunte(db, USUARIO, "-45 gasolina", origen="bot")
        datos, _ = generar(db, USUARIO)
        r = _leer_fichero(cliente, cabeceras, "parte-del-dia.zip", datos, "application/zip")
        assert r.status_code == 422
        assert "reenvíasela al bot" in r.json()["detail"]

    def test_una_captura_se_lee_como_lista(self, cliente, cabeceras, monkeypatch):
        async def captura(imagen, mime):
            return {
                "movimientos": [
                    {"fecha": AYER.isoformat(), "concepto": "Parking", "importe": 2.75, "tipo": "gasto"},
                    {"fecha": HOY.isoformat(), "concepto": "Parking", "importe": 2.75, "tipo": "gasto"},
                ]
            }

        monkeypatch.setattr(importacion, "leer_movimientos", captura)
        r = _leer_fichero(cliente, cabeceras, "captura.jpg", b"\xff\xd8 imagen", "image/jpeg")
        assert r.status_code == 200, r.text
        assert len(r.json()["movimientos"]) == 2


class TestConfirmar:
    def test_entra_solo_lo_elegido_y_se_puede_deshacer(self, cliente, cabeceras, db):
        leido = _leer_texto(cliente, cabeceras, "-45 gasolina\n-3 parking").json()["movimientos"]

        r = cliente.post("/importar", json={"movimientos": leido[:1]}, headers=cabeceras)
        assert r.status_code == 201, r.text
        hecho = r.json()
        assert [a["concepto"] for a in hecho["apuntes"]] == ["gasolina"]
        assert hecho["apuntes"][0]["origen"] == "web"
        assert db.query(Apunte).count() == 1

        ids = [a["id"] for a in hecho["apuntes"]]
        r = cliente.post("/importar/deshacer", json={"ids": ids}, headers=cabeceras)
        assert r.json() == {"borrados": 1}
        assert db.query(Apunte).count() == 0

    def test_confirmar_dos_veces_no_duplica(self, cliente, cabeceras, db):
        """Dos pestañas, o un doble clic: lo que ya entró no vuelve a entrar."""
        leido = _leer_texto(cliente, cabeceras, "-45 gasolina\n-3 parking").json()["movimientos"]
        cliente.post("/importar", json={"movimientos": leido}, headers=cabeceras)

        r = cliente.post("/importar", json={"movimientos": leido}, headers=cabeceras)

        assert r.json()["apuntes"] == [] and r.json()["ya_estaban"] == 2
        assert db.query(Apunte).count() == 2

    def test_un_repetido_elegido_a_mano_entra(self, cliente, cabeceras, db):
        """Dos gasolinas de 45 el mismo día pueden ser dos: si se elige, entra."""
        crear_apunte(db, USUARIO, "-45 gasolina", origen="bot")
        leido = _leer_texto(cliente, cabeceras, "-45 gasolina\n-3 parking").json()["movimientos"]
        assert leido[0]["repetido"]

        cliente.post("/importar", json={"movimientos": leido, "todo": True}, headers=cabeceras)

        assert db.query(Apunte).filter(Apunte.concepto == "gasolina").count() == 2

    def test_sin_tipo_no_entra(self, cliente, cabeceras, db):
        sin_tipo = [{"fecha": HOY.isoformat(), "tipo": None, "concepto": "Parking", "importe": "2.75"}]
        r = cliente.post("/importar", json={"movimientos": sin_tipo}, headers=cabeceras)
        assert r.status_code == 422
        assert db.query(Apunte).count() == 0

    def test_una_fecha_futura_no_entra(self, cliente, cabeceras, db):
        manana = (HOY + timedelta(days=1)).isoformat()
        r = cliente.post(
            "/importar",
            json={"movimientos": [{"fecha": manana, "tipo": "gasto", "concepto": "x", "importe": "1"}]},
            headers=cabeceras,
        )
        assert r.status_code == 422
        assert db.query(Apunte).count() == 0

    def test_no_se_deshace_lo_de_otro(self, cliente, cabeceras, db):
        ajeno = crear_apunte(db, 111222333, "-45 gasolina", origen="bot")
        r = cliente.post("/importar/deshacer", json={"ids": [ajeno.id]}, headers=cabeceras)
        assert r.json() == {"borrados": 0}
        assert db.query(Apunte).count() == 1

    def test_pide_token(self, cliente):
        assert cliente.post("/importar/leer", data={"texto": "a 1\nb 2"}).status_code == 401
