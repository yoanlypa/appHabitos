"""El escáner de tickets: lo que se acepta de la lectura y lo que pasa con las fotos.

Lo que puede romperse en silencio aquí: que una lectura absurda (un total de
2340 por 23,40, una fecha de 2062) llegue a las cuentas, que un gasto
borrado deje su foto huérfana, o que un usuario vea la factura de otro.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.dominio.models import Factura
from app.dominio.tickets import interpretar_lectura
from app.main import crear_api
from app.nucleo import archivos
from app.servicios import facturas
from app.servicios.apuntes import borrar_apunte
from app.servicios.auth import generar_token
from app.servicios.resumen import resumen_dia
from tests.conftest import USUARIO

HOY = date(2026, 10, 27)
JPG = b"\xff\xd8\xff\xe0" + b"0" * 500


class TestLectura:
    @pytest.mark.parametrize(
        "leido,esperado",
        [(23.4, "23.40"), ("23,40", "23.40"), ("1.234,50 €", "1234.50"), ("1,234.50", "1234.50")],
    )
    def test_entiende_los_formatos_de_importe(self, leido, esperado):
        assert interpretar_lectura({"total": leido}, HOY).total == Decimal(esperado)

    @pytest.mark.parametrize("leido", [0, -5, "abc", None, True, 250000])
    def test_un_total_imposible_queda_vacio(self, leido):
        assert interpretar_lectura({"total": leido}, HOY).total is None

    def test_una_fecha_futura_o_muy_vieja_no_vale(self):
        assert interpretar_lectura({"fecha": "2062-10-27"}, HOY).fecha is None
        assert interpretar_lectura({"fecha": "2020-01-01"}, HOY).fecha is None
        assert interpretar_lectura({"fecha": "2026-10-25"}, HOY).fecha == date(2026, 10, 25)

    def test_el_iva_no_puede_superar_el_total(self):
        assert interpretar_lectura({"total": 10, "iva": 12}, HOY).iva is None
        assert interpretar_lectura({"total": 12.1, "iva": 2.1}, HOY).iva == Decimal("2.10")

    def test_concepto_sugerido(self):
        d = interpretar_lectura({"concepto": "tornillería", "comercio": "Leroy Merlin"}, HOY)
        assert d.concepto_sugerido == "tornillería · Leroy Merlin"
        assert interpretar_lectura({}, HOY).concepto_sugerido == "Ticket escaneado"


@pytest.fixture
def lector(monkeypatch):
    """Sustituye al modelo de visión: los tests no salen a internet."""
    respuesta = {"total": "23,40", "fecha": None, "comercio": "Ferretería Paco", "concepto": "silicona"}

    async def falso(_imagen, _mime):
        return dict(respuesta)

    monkeypatch.setattr(facturas, "leer_ticket", falso)
    return respuesta


@pytest.mark.asyncio
async def test_el_bot_anota_el_gasto_y_cuelga_la_foto(db, lector):
    leido, apunte = await facturas.escanear_y_anotar(db, USUARIO, JPG, "image/jpeg", None, "bot")
    assert apunte.tipo == "gasto" and apunte.importe == Decimal("23.40")
    assert apunte.factura_id == leido.factura.id
    assert archivos.ruta_absoluta(leido.factura.ruta).exists()
    # Cuenta como gasto en el resumen, que es para lo que se escanea.
    assert resumen_dia(db, USUARIO, apunte.fecha).gastos == Decimal("23.40")


@pytest.mark.asyncio
async def test_sin_total_no_se_anota_ni_se_queda_la_foto(db, lector):
    lector["total"] = None
    _, apunte = await facturas.escanear_y_anotar(db, USUARIO, JPG, "image/jpeg", None, "bot")
    assert apunte is None
    assert db.query(Factura).count() == 0


@pytest.mark.asyncio
async def test_si_la_lectura_falla_no_queda_rastro(db, monkeypatch):
    async def roto(_i, _m):
        raise RuntimeError("cuota agotada")

    monkeypatch.setattr(facturas, "leer_ticket", roto)
    with pytest.raises(RuntimeError):
        await facturas.escanear(db, USUARIO, JPG, "image/jpeg")
    assert db.query(Factura).count() == 0


@pytest.mark.asyncio
async def test_borrar_el_gasto_borra_su_foto(db, lector):
    leido, apunte = await facturas.escanear_y_anotar(db, USUARIO, JPG, "image/jpeg", "pintura", "bot")
    ruta = archivos.ruta_absoluta(leido.factura.ruta)
    assert apunte.concepto == "pintura"  # lo escrito manda sobre lo leído
    borrar_apunte(db, USUARIO, apunte.id)
    assert not ruta.exists()
    assert db.query(Factura).count() == 0


def test_lo_escaneado_y_abandonado_se_limpia(db):
    factura = facturas.guardar_factura(db, USUARIO, JPG, "image/jpeg")
    ruta = archivos.ruta_absoluta(factura.ruta)
    assert facturas.limpiar_huerfanas(db) == 0  # recién escaneada: se respeta
    factura.creado = factura.creado - timedelta(days=2)
    db.commit()
    assert facturas.limpiar_huerfanas(db) == 1
    assert not ruta.exists()


class TestPorHttp:
    @pytest.fixture
    def cliente(self):
        with TestClient(crear_api()) as c:
            yield c

    @pytest.fixture
    def cabeceras(self, db):
        return {"Authorization": f"Bearer {generar_token(db, USUARIO)}"}

    def test_escanear_confirmar_y_ver_la_foto(self, cliente, cabeceras, lector):
        r = cliente.post(
            "/facturas/escanear", headers=cabeceras,
            files={"imagen": ("t.jpg", JPG, "image/jpeg")},
        )
        assert r.status_code == 200, r.text
        leido = r.json()
        assert leido["total"] == "23.40"
        assert leido["concepto"] == "silicona · Ferretería Paco"

        # Antes de confirmar no hay gasto: lo leído se enseña, no se anota.
        assert cliente.get("/apuntes", headers=cabeceras).json() == []

        r = cliente.post(
            f"/facturas/{leido['factura_id']}/gasto", headers=cabeceras,
            json={"concepto": "silicona", "importe": "23.40"},
        )
        assert r.status_code == 201
        assert r.json()["factura_id"] == leido["factura_id"]
        lista = cliente.get("/apuntes", headers=cabeceras).json()
        assert lista[0]["factura_id"] == leido["factura_id"]

        imagen = cliente.get(f"/facturas/{leido['factura_id']}/imagen", headers=cabeceras)
        assert imagen.status_code == 200 and imagen.content == JPG

        # Confirmar dos veces la misma foto no duplica el gasto.
        otra = cliente.post(
            f"/facturas/{leido['factura_id']}/gasto", headers=cabeceras,
            json={"concepto": "x", "importe": "1"},
        )
        assert otra.status_code == 422

    def test_la_factura_de_otro_no_se_ve(self, cliente, db, cabeceras):
        ajena = facturas.guardar_factura(db, 111, JPG, "image/jpeg")
        assert cliente.get(f"/facturas/{ajena.id}/imagen", headers=cabeceras).status_code == 404

    def test_sin_token_no(self, cliente):
        assert cliente.post("/facturas/escanear").status_code == 401

    def test_un_pdf_o_un_fichero_raro_se_rechaza(self, cliente, cabeceras, lector):
        r = cliente.post(
            "/facturas/escanear", headers=cabeceras,
            files={"imagen": ("a.txt", b"hola", "text/plain")},
        )
        assert r.status_code == 422

    def test_importe_cero_no(self, cliente, db, cabeceras):
        f = facturas.guardar_factura(db, USUARIO, JPG, "image/jpeg")
        r = cliente.post(f"/facturas/{f.id}/gasto", headers=cabeceras, json={"concepto": "x", "importe": "0"})
        assert r.status_code == 422
