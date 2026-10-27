"""El PDF de los tickets: que salga un PDF de verdad, una página por ticket y
en orden de fecha, y que el de otro usuario no se cuele en el tuyo.

Lo que se rompería en silencio: un PDF del mes con los tickets de otra
persona, o uno que se queda corto porque se perdió una foto por el camino.
"""
import io
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import crear_api
from app.nucleo.pdf import imagenes_a_pdf
from app.nucleo import archivos
from app.servicios import facturas
from app.servicios.auth import generar_token
from tests.conftest import USUARIO


def _jpg(ancho=300, alto=600, color=(230, 220, 190)) -> bytes:
    """Una foto de verdad, apaisada con EXIF de giro no hace falta: basta con que se abra."""
    salida = io.BytesIO()
    Image.new("RGB", (ancho, alto), color).save(salida, format="JPEG")
    return salida.getvalue()


def _paginas(pdf: bytes) -> int:
    return pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages")


def _gasto(db, user_id, fecha, concepto="ticket"):
    f = facturas.guardar_factura(db, user_id, _jpg(), "image/jpeg")
    return facturas.anotar_gasto(db, user_id, f.id, concepto, Decimal("10"), fecha, "web")


def test_una_foto_da_un_pdf_de_una_pagina(tmp_path):
    ruta = tmp_path / "t.jpg"
    ruta.write_bytes(_jpg())
    pdf = imagenes_a_pdf([ruta])
    assert pdf.startswith(b"%PDF")
    assert _paginas(pdf) == 1


def test_el_pdf_de_una_factura_lleva_fecha_y_concepto_en_el_nombre(db):
    apunte = _gasto(db, USUARIO, date(2026, 10, 8), "Tacos expansión · Leroy Merlin")
    pdf, nombre = facturas.pdf_de_factura(db, USUARIO, apunte.factura_id)
    assert pdf.startswith(b"%PDF")
    assert nombre == "2026-10-08-tacos-expansión-leroy-merlin.pdf"


def test_el_del_mes_va_por_fecha_y_solo_con_lo_tuyo(db):
    hoy = date(2026, 10, 27)
    _gasto(db, USUARIO, hoy)
    _gasto(db, USUARIO, hoy - timedelta(days=20))
    _gasto(db, USUARIO, date(2026, 9, 30))  # mes anterior: fuera
    _gasto(db, 111, hoy)  # de otro: fuera
    facturas.guardar_factura(db, USUARIO, _jpg(), "image/jpeg")  # sin anotar: fuera

    pdf = facturas.pdf_del_periodo(db, USUARIO, date(2026, 10, 1), hoy)
    assert _paginas(pdf) == 2


def test_sin_tickets_no_hay_pdf(db):
    assert facturas.pdf_del_periodo(db, USUARIO, date(2026, 10, 1), date(2026, 10, 31)) is None


def test_si_falta_una_foto_el_resto_sale_igual(db):
    a = _gasto(db, USUARIO, date(2026, 10, 2))
    _gasto(db, USUARIO, date(2026, 10, 3))
    archivos.borrar(a.factura.ruta)
    pdf = facturas.pdf_del_periodo(db, USUARIO, date(2026, 10, 1), date(2026, 10, 31))
    assert _paginas(pdf) == 1


class TestPorHttp:
    @pytest.fixture
    def cliente(self):
        with TestClient(crear_api()) as c:
            yield c

    @pytest.fixture
    def cabeceras(self, db):
        return {"Authorization": f"Bearer {generar_token(db, USUARIO)}"}

    def test_pdf_de_una_y_del_mes(self, cliente, db, cabeceras):
        apunte = _gasto(db, USUARIO, date(2026, 10, 8))
        r = cliente.get(f"/facturas/{apunte.factura_id}/pdf", headers=cabeceras)
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF")

        r = cliente.get("/facturas/pdf?desde=2026-10-01&hasta=2026-10-31", headers=cabeceras)
        assert r.status_code == 200 and r.content.startswith(b"%PDF")

    def test_mes_vacio_da_404_y_rango_al_reves_422(self, cliente, cabeceras):
        assert cliente.get("/facturas/pdf?desde=2026-01-01&hasta=2026-01-31", headers=cabeceras).status_code == 404
        assert cliente.get("/facturas/pdf?desde=2026-02-01&hasta=2026-01-31", headers=cabeceras).status_code == 422

    def test_el_pdf_de_otro_no(self, cliente, db, cabeceras):
        ajeno = _gasto(db, 111, date(2026, 10, 8))
        assert cliente.get(f"/facturas/{ajeno.factura_id}/pdf", headers=cabeceras).status_code == 404
