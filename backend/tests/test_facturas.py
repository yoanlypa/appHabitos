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


class TestTicketCompleto:
    """Todo lo que pone el ticket se guarda, y lo absurdo se queda fuera."""

    LEIDO = {
        "total": "8,08", "fecha": "2026-10-08", "hora": "16:33", "comercio": "Leroy Merlin",
        "razon_social": "LEROY MERLIN MALAGA S.L.U.", "cif": "B84818442", "numero": "036-0010-243003",
        "lineas": [
            {"descripcion": "4 TACOS 6X55", "cantidad": 1, "precio_unitario": 5.61, "importe": 4.19},
            {"descripcion": "", "cantidad": 1, "importe": 3},  # sin descripción: fuera
            "basura",
        ],
        "base_imponible": 6.68, "iva": 1.40, "tipos_iva": [{"tipo": 21, "cuota": 1.4}, {"tipo": 99}],
        "forma_pago": "Tarjeta", "documento": "regalo",
        "esquinas": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
    }

    def test_se_limpia_lo_leido(self):
        d = interpretar_lectura(self.LEIDO, HOY)
        assert d.detalle["cif"] == "B84818442"
        assert d.detalle["lineas"] == [
            {"descripcion": "4 TACOS 6X55", "cantidad": "1", "precio_unitario": "5.61", "importe": "4.19"}
        ]
        assert d.detalle["tipos_iva"] == [{"tipo": "21", "base": None, "cuota": "1.40"}]
        assert "documento" not in d.detalle  # ni gasto ni devolución: no se inventa
        assert d.esquinas == [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]

    @pytest.mark.parametrize(
        "esquinas", [None, [[0, 0]] * 3, [[0, 0], [1, 0], [1, 1], [5, 5]], "x", [[0, "a"]] * 4]
    )
    def test_esquinas_raras_no_valen(self, esquinas):
        assert interpretar_lectura({"esquinas": esquinas}, HOY).esquinas is None

    def test_una_base_mayor_que_el_total_no_vale(self):
        assert "base_imponible" not in interpretar_lectura({"total": 5, "base_imponible": 50}, HOY).detalle

    @pytest.mark.asyncio
    async def test_se_guarda_y_sale_en_la_segunda_pagina_del_pdf(self, db, monkeypatch):
        async def falso(_i, _m):
            return dict(self.LEIDO)

        monkeypatch.setattr(facturas, "leer_ticket", falso)
        leido, apunte = await facturas.escanear_y_anotar(db, USUARIO, _foto(), "image/jpeg", None, "bot")
        guardado = facturas.datos_leidos(leido.factura)
        assert guardado["cif"] == "B84818442" and guardado["total"] == "8.08"
        pdf, _ = facturas.pdf_de_factura(db, USUARIO, leido.factura.id)
        assert pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages") == 2  # foto + datos

    def test_sin_datos_leidos_el_pdf_es_solo_la_foto(self, db):
        f = facturas.guardar_factura(db, USUARIO, _foto(), "image/jpeg")
        pdf, _ = facturas.pdf_de_factura(db, USUARIO, f.id)
        assert pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages") == 1


def _foto() -> bytes:
    import io as _io
    from PIL import Image as _Image

    salida = _io.BytesIO()
    _Image.new("RGB", (300, 500), (230, 225, 200)).save(salida, format="JPEG")
    return salida.getvalue()


def test_el_precio_de_la_gasolina_conserva_los_tres_decimales():
    """Ticket real de Ballenoil: 45,61 l a 1,637 € = 74,66 €. Con 1,64 no cuadra."""
    d = interpretar_lectura(
        {"total": 74.66, "lineas": [{"descripcion": "Sin Plomo 95", "cantidad": 45.61,
                                     "precio_unitario": "1,637", "importe": 74.66}]},
        HOY,
    )
    linea = d.detalle["lineas"][0]
    assert linea["precio_unitario"] == "1.637"
    assert linea["cantidad"] == "45.61"
    assert interpretar_lectura(
        {"lineas": [{"descripcion": "x", "precio_unitario": 5.6}]}, HOY
    ).detalle["lineas"][0]["precio_unitario"] == "5.60"


class TestVales:
    """Los cheques y cupones del ticket acaban como notas pendientes."""

    LEIDO = {
        "total": 74.66, "comercio": "Ballenoil",
        "vales": [
            {"tipo": "cheque", "descripcion": "Cheque devolución", "importe": "25,34",
             "codigo": "9926 8349 94302", "caduca": "2029-10-23"},
            {"tipo": "cupon", "descripcion": "Cupón lavado gratis", "codigo": "1573193622",
             "caduca": "2026-11-22"},
            {"tipo": "cupon", "descripcion": "Caducado", "caduca": "2020-01-01"},
            {"tipo": "regalo", "descripcion": "tipo raro"},
        ],
    }

    def test_se_limpian_y_los_caducados_fuera(self):
        vales = interpretar_lectura(self.LEIDO, HOY).detalle["vales"]
        assert [v["descripcion"] for v in vales] == ["Cheque devolución", "Cupón lavado gratis"]
        assert vales[0]["codigo"] == "9926834994302"  # sin espacios, para teclearlo

    def test_el_texto_de_la_nota(self):
        from app.dominio.tickets import texto_de_vale

        vale = interpretar_lectura(self.LEIDO, HOY).detalle["vales"][0]
        assert texto_de_vale(vale, "Ballenoil") == (
            "🎟 Cheque devolución 25,34 € · Ballenoil · cód. 9926834994302 · caduca 23/10/2029"
        )

    @pytest.mark.asyncio
    async def test_al_anotar_el_gasto_van_al_buzon_y_no_suman(self, db, monkeypatch):
        from app.servicios.notas import listar_notas

        async def falso(_i, _m):
            return dict(self.LEIDO)

        monkeypatch.setattr(facturas, "leer_ticket", falso)
        _, apunte = await facturas.escanear_y_anotar(db, USUARIO, _foto(), "image/jpeg", None, "bot")
        notas = [n.concepto for n in listar_notas(db, USUARIO)]
        assert len(notas) == 2
        assert all(n.startswith("🎟") for n in notas)
        # Una nota no es dinero: el gasto del día sigue siendo solo la gasolina.
        assert resumen_dia(db, USUARIO, apunte.fecha).gastos == Decimal("74.66")

    @pytest.mark.asyncio
    async def test_escanear_sin_confirmar_no_deja_notas(self, db, monkeypatch):
        from app.servicios.notas import listar_notas

        async def falso(_i, _m):
            return dict(self.LEIDO)

        monkeypatch.setattr(facturas, "leer_ticket", falso)
        await facturas.escanear(db, USUARIO, _foto(), "image/jpeg")
        assert listar_notas(db, USUARIO) == []


class TestFechaDelTicket:
    """El gasto va al día del ticket, no al día en que se sube."""

    @pytest.fixture
    def leido(self, monkeypatch):
        respuesta = {"total": 20, "fecha": "2026-10-08", "comercio": "Leroy Merlin"}

        async def falso(_i, _m):
            return dict(respuesta)

        monkeypatch.setattr(facturas, "leer_ticket", falso)
        return respuesta

    @pytest.mark.asyncio
    async def test_va_al_dia_del_ticket(self, db, leido):
        t, apunte = await facturas.escanear_y_anotar(db, USUARIO, _foto(), "image/jpeg", None, "bot")
        assert apunte.fecha == date(2026, 10, 8)
        assert not t.fecha_supuesta

    @pytest.mark.asyncio
    async def test_la_fecha_escrita_con_la_foto_manda(self, db, leido, monkeypatch):
        monkeypatch.setattr(facturas, "hoy_local", lambda: date(2026, 10, 28))
        _, apunte = await facturas.escanear_y_anotar(
            db, USUARIO, _foto(), "image/jpeg", "3/10 material baño", "bot"
        )
        assert apunte.fecha == date(2026, 10, 3)
        assert apunte.concepto == "material baño"  # la fecha no se queda en el concepto

    @pytest.mark.asyncio
    async def test_sin_fecha_leida_se_pone_hoy_y_se_avisa(self, db, leido):
        leido["fecha"] = None
        t, apunte = await facturas.escanear_y_anotar(db, USUARIO, _foto(), "image/jpeg", None, "bot")
        assert t.fecha_supuesta
        from app.bot import formato

        assert f"/fecha {apunte.id}" in formato.ticket_anotado(apunte, t.datos, t.fecha_supuesta)

    def test_un_ticket_de_hace_tres_anos_vale(self):
        assert interpretar_lectura({"fecha": "2023-11-02"}, HOY).fecha == date(2023, 11, 2)
        assert interpretar_lectura({"fecha": "2019-11-02"}, HOY).fecha is None


class TestFechaEscrita:
    """Al revés que una cita, la fecha de un ticket siempre es pasada."""

    @pytest.mark.parametrize(
        "texto,esperado",
        [
            ("15/10 material", (date(2026, 10, 15), "material")),
            ("15/12 navidad", (date(2025, 12, 15), "navidad")),  # sin año: el último
            ("ayer gasolina", (date(2026, 10, 26), "gasolina")),
            ("3 de octubre comida", (date(2026, 10, 3), "comida")),
            ("mañana algo", (None, "mañana algo")),
            ("lunes algo", (None, "lunes algo")),
            ("01/11/2026 futuro", (None, "01/11/2026 futuro")),  # año escrito y futuro
            ("material sin fecha", (None, "material sin fecha")),
        ],
    )
    def test_casos(self, texto, esperado):
        from app.dominio.tickets import fecha_escrita

        assert fecha_escrita(texto, HOY) == esperado


def test_cambiar_la_fecha_de_un_apunte(db):
    from app.servicios.apuntes import FechaNoValida, cambiar_fecha

    f = facturas.guardar_factura(db, USUARIO, _foto(), "image/jpeg")
    apunte = facturas.anotar_gasto(db, USUARIO, f.id, "x", Decimal("5"), None, "bot")
    movido = cambiar_fecha(db, USUARIO, apunte.id, "1/1/2026")
    assert movido.fecha == date(2026, 1, 1)
    with pytest.raises(FechaNoValida):
        cambiar_fecha(db, USUARIO, apunte.id, "mañana")


class TestFechasEspanolas:
    """La causa de que casi todos los tickets cayeran en "hoy"."""

    @pytest.mark.parametrize(
        "leida,dia,hora",
        [
            ("2026-10-24", date(2026, 10, 24), None),
            ("24/10/2026", date(2026, 10, 24), None),
            ("24/10/2026 19:26:28", date(2026, 10, 24), "19:26"),
            ("24-10-26", date(2026, 10, 24), None),
            ("24.10.2026", date(2026, 10, 24), None),
            ("Fecha: 24/10/2026", date(2026, 10, 24), None),
            ("31/02/2026", None, None),  # no existe
        ],
    )
    def test_formatos(self, leida, dia, hora):
        d = interpretar_lectura({"fecha": leida}, HOY)
        assert d.fecha == dia
        assert d.detalle.get("hora") == hora

    def test_el_dia_va_primero(self):
        """03/10 es 3 de octubre, no 10 de marzo."""
        assert interpretar_lectura({"fecha": "03/10/2026"}, HOY).fecha == date(2026, 10, 3)


@pytest.mark.asyncio
async def test_releer_pone_en_su_dia_lo_que_quedo_en_hoy(db, monkeypatch):
    # Dos tickets subidos con la versión que no entendía "24/10/2026": sin fecha.
    con_fecha = facturas.guardar_factura(db, USUARIO, _foto(), "image/jpeg")
    a1 = facturas.anotar_gasto(db, USUARIO, con_fecha.id, "gasolina", Decimal("74.66"), HOY, "bot")
    ilegible = facturas.guardar_factura(db, USUARIO, _foto(), "image/jpeg")
    a2 = facturas.anotar_gasto(db, USUARIO, ilegible.id, "x", Decimal("5"), HOY, "bot")
    # Uno ya bien leído: no se toca ni se paga otra lectura.
    bien = facturas.guardar_factura(db, USUARIO, _foto(), "image/jpeg")
    bien.datos = '{"fecha": "2026-10-08"}'
    db.commit()
    facturas.anotar_gasto(db, USUARIO, bien.id, "tacos", Decimal("8.08"), date(2026, 10, 8), "bot")

    leidas = []

    async def falso(imagen, mime):
        leidas.append(1)
        return {"total": 1, "fecha": "24/10/2026" if len(leidas) == 1 else None}

    monkeypatch.setattr(facturas, "leer_ticket", falso)
    resultado = await facturas.releer_fechas(db, USUARIO)
    assert len(leidas) == 2  # el bien leído no se relee
    assert [c.apunte.id for c in resultado.corregidas] == [a1.id]
    db.refresh(a1)
    db.refresh(a2)
    assert a1.fecha == date(2026, 10, 24)
    assert a2.fecha == HOY and resultado.sin_fecha == 1  # sin fecha: se queda como estaba

    # Segunda vez: nada que hacer, ni siquiera el que no tenía fecha.
    leidas.clear()
    otra = await facturas.releer_fechas(db, USUARIO)
    assert leidas == [] and not otra.corregidas


def _pdf(paginas: int = 2) -> bytes:
    """Una factura en PDF como las que llegan por email (aquí, páginas lisas)."""
    import io as _io
    from PIL import Image as _Image

    hojas = [_Image.new("RGB", (620, 877), (255, 255, 255)) for _ in range(paginas)]
    salida = _io.BytesIO()
    hojas[0].save(salida, format="PDF", save_all=True, append_images=hojas[1:])
    return salida.getvalue()


class TestFacturaEnPdf:
    """Un PDF pasa por lo mismo que una foto: se lee, se anota y vuelve en PDF."""

    @pytest.mark.asyncio
    async def test_se_lee_y_se_anota(self, db, monkeypatch):
        vistas = []

        async def falso(imagen, mime):
            vistas.append(mime)
            return {"total": "56,20", "fecha": "12/10/2026", "comercio": "Endesa",
                    "esquinas": [[0, 0], [1, 0], [1, 1], [0, 1]]}

        monkeypatch.setattr(facturas, "leer_ticket", falso)
        leido, apunte = await facturas.escanear_y_anotar(db, USUARIO, _pdf(2), "application/pdf", None, "bot")
        # A la IA le llega una imagen (las dos páginas unidas), no el PDF.
        assert vistas == ["image/jpeg"]
        assert (apunte.importe, apunte.fecha) == (Decimal("56.20"), date(2026, 10, 12))
        assert leido.factura.ruta.endswith(".pdf")  # se guarda el PDF original
        assert leido.factura.esquinas is None  # un PDF no se endereza

        pdf, _ = facturas.pdf_de_factura(db, USUARIO, leido.factura.id)
        # Las dos páginas del original y la ficha de datos.
        assert pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages") == 3

    @pytest.mark.asyncio
    async def test_un_pdf_roto_no_deja_rastro(self, db, monkeypatch):
        async def falso(_i, _m):
            raise AssertionError("no debería llegar a leerse")

        monkeypatch.setattr(facturas, "leer_ticket", falso)
        with pytest.raises(facturas.FacturaNoValida):
            await facturas.escanear(db, USUARIO, b"%PDF-1.4 basura", "application/pdf")
        assert db.query(Factura).count() == 0
