"""Trabajos (obras) con lo que tienen dentro, y qué va a la gestoría.

Lo que se rompería en silencio, y sale caro porque se descubre cuando la
gestoría ya ha presentado el trimestre: un gasto de un trabajo que factura
otra empresa colándose en lo que se manda; algo que se cae de la lista al
borrar su trabajo; o el listado, el CSV y el PDF diciendo cosas distintas.
"""
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.dominio.gestoria import marca_gestoria, va_a_gestoria
from app.dominio.models import Apunte, Trabajo
from app.main import crear_api
from app.servicios import facturas
from app.servicios.auth import generar_token
from app.servicios.resumen import resumen_rango
from tests.conftest import USUARIO
from tests.test_facturas import _foto
from tests.test_facturas_emitidas import NIF, _lectura, _subir

OCTUBRE = "desde=2026-10-01&hasta=2026-10-31"


@pytest.fixture
def cliente():
    with TestClient(crear_api()) as c:
        yield c


@pytest.fixture
def cab(db):
    return {"Authorization": f"Bearer {generar_token(db, USUARIO)}"}


def _obra(cliente, cab, titulo="Reforma baño Luis", **extra):
    r = cliente.post("/trabajos", headers=cab, json={"titulo": titulo, "fecha_inicio": "2026-10-01", **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _nuevo(cliente, cab, tipo, concepto, importe, fecha="2026-10-10", **extra):
    r = cliente.post(
        "/apuntes/movimiento",
        headers=cab,
        json={"tipo": tipo, "concepto": concepto, "importe": importe, "fecha": fecha, **extra},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _editar(cliente, cab, apunte_id, **cambios):
    return cliente.patch(f"/apuntes/{apunte_id}", headers=cab, json=cambios)


def _apunte(cliente, cab, apunte_id):
    lista = cliente.get("/apuntes/rango?desde=2026-01-01&hasta=2026-11-01", headers=cab).json()
    return next(a for a in lista if a["id"] == apunte_id)


# ---------- La regla ----------


def test_la_regla_de_que_va_y_que_no():
    # De un trabajo: sigue a su trabajo, lleve la marca que lleve.
    assert va_a_gestoria("trabajo", False, True)
    assert va_a_gestoria("gasto", False, True)
    assert not va_a_gestoria("gasto", True, False)
    # Suelto: solo si se ha marcado a mano.
    assert va_a_gestoria("gasto", True, None)
    assert not va_a_gestoria("gasto", False, None)
    # El papel manda: un cobro con su factura emitida va siempre.
    assert va_a_gestoria("trabajo", False, False, factura_emitida=True)
    assert not va_a_gestoria("nota", True, True, True)


def test_para_la_gestoria_en_el_texto_de_la_foto():
    assert marca_gestoria("material baño para la gestoría") == (True, "material baño")
    assert marca_gestoria("Para gestoria 15/10 gasolina") == (True, "15/10 gasolina")
    assert marca_gestoria("gestoría") == (True, "")
    assert marca_gestoria("Factura gestoría octubre") == (False, "Factura gestoría octubre")
    assert marca_gestoria(None) == (False, "")


# ---------- Dentro de un trabajo ----------


def test_lo_de_un_trabajo_sigue_al_trabajo_sin_tocarlo(cliente, cab):
    obra = _obra(cliente, cab)
    cobro = _nuevo(cliente, cab, "trabajo", "Primer pago", "500", trabajo_id=obra["id"])
    gasto = _nuevo(cliente, cab, "gasto", "Azulejos", "210.50", trabajo_id=obra["id"])
    assert gasto["trabajo_titulo"] == "Reforma baño Luis"
    assert not cobro["gestoria"] and not gasto["gestoria"]

    # Se factura el trabajo: entra todo solo, nadie ha editado los apuntes.
    assert cliente.patch(f"/trabajos/{obra['id']}", headers=cab, json={"facturado": True}).json()["facturado"]
    assert _apunte(cliente, cab, cobro["id"])["gestoria"]
    assert _apunte(cliente, cab, gasto["id"])["gestoria"]
    cliente.patch(f"/trabajos/{obra['id']}", headers=cab, json={"facturado": False})
    assert not _apunte(cliente, cab, gasto["id"])["gestoria"]


def test_el_suelto_se_marca_a_mano_y_la_marca_no_reaparece(cliente, cab):
    ajena = _obra(cliente, cab, "Obra de la otra empresa")
    gasto = _nuevo(cliente, cab, "gasto", "Gasolina", "45", para_gestoria=True)
    assert gasto["gestoria"] and gasto["para_gestoria"]

    metido = _editar(cliente, cab, gasto["id"], trabajo_id=ajena["id"]).json()
    assert not metido["gestoria"] and not metido["para_gestoria"]
    # Se saca: no vuelve a ir por una marca vieja que ya nadie recuerda.
    suelto = _editar(cliente, cab, gasto["id"], trabajo_id=None).json()
    assert suelto["trabajo_id"] is None and not suelto["gestoria"]


def test_solo_en_un_trabajo_propio(cliente, cab, db):
    gasto = _nuevo(cliente, cab, "gasto", "Pintura", "30")
    ajeno = Trabajo(user_id=111, titulo="De otro", fecha_inicio=date(2026, 10, 1))
    db.add(ajeno)
    db.commit()
    assert _editar(cliente, cab, gasto["id"], trabajo_id=ajeno.id).status_code == 422
    assert _editar(cliente, cab, gasto["id"], trabajo_id=99999).status_code == 422
    r = cliente.post("/apuntes/movimiento", headers=cab, json={
        "tipo": "gasto", "concepto": "x", "importe": "1", "trabajo_id": ajeno.id})
    assert r.status_code == 422
    assert cliente.get(f"/trabajos/{ajeno.id}", headers=cab).status_code == 404
    assert cliente.patch(f"/trabajos/{ajeno.id}", headers=cab, json={"resena": True}).status_code == 404
    assert cliente.delete(f"/trabajos/{ajeno.id}", headers=cab).status_code == 404


def test_borrar_un_trabajo_facturado_no_saca_nada_de_la_gestoria(cliente, cab):
    obra = _obra(cliente, cab, facturado=True)
    gasto = _nuevo(cliente, cab, "gasto", "Azulejos", "210", trabajo_id=obra["id"])
    assert cliente.delete(f"/trabajos/{obra['id']}", headers=cab).status_code == 204
    suelto = _apunte(cliente, cab, gasto["id"])
    assert suelto["trabajo_id"] is None
    assert suelto["gestoria"] and suelto["para_gestoria"]  # conserva lo que valía


# ---------- El parte de la gestoría ----------


def test_el_parte_reparte_el_periodo_en_lo_que_va_y_lo_que_no(cliente, cab, db):
    facturada = _obra(cliente, cab, "Reforma baño", facturado=True)
    ajena = _obra(cliente, cab, "Obra de la otra empresa")
    _nuevo(cliente, cab, "trabajo", "Reforma baño", "980", trabajo_id=facturada["id"])
    _nuevo(cliente, cab, "trabajo", "Obra de la otra empresa", "500", trabajo_id=ajena["id"])
    _nuevo(cliente, cab, "gasto", "Azulejos", "210.50", trabajo_id=facturada["id"])
    _nuevo(cliente, cab, "gasto", "Material obra ajena", "80", trabajo_id=ajena["id"])
    _nuevo(cliente, cab, "gasto", "Cuota autónomos", "294", fecha="2026-10-31", para_gestoria=True)
    _nuevo(cliente, cab, "gasto", "Café", "3.20", fecha="2026-10-01")
    _nuevo(cliente, cab, "gasto", "De septiembre", "99", fecha="2026-09-30", para_gestoria=True)
    db.add(Apunte(user_id=111, fecha=date(2026, 10, 5), tipo="trabajo", concepto="De otro usuario",
                  importe=Decimal("777"), pendiente=False, origen="web", para_gestoria=True))
    db.commit()

    parte = cliente.get(f"/gestoria?{OCTUBRE}", headers=cab).json()
    nombres = lambda clave: [a["concepto"] for a in parte[clave]]
    assert nombres("emitidas") == ["Reforma baño"]
    assert nombres("recibidas") == ["Azulejos", "Cuota autónomos"]
    assert nombres("trabajos_fuera") == ["Obra de la otra empresa"]
    assert nombres("gastos_fuera") == ["Café", "Material obra ajena"]
    assert (parte["facturado"], parte["gastos"], parte["diferencia"]) == ("980.00", "504.50", "475.50")
    assert parte["sin_documento"] == 3

    todo = resumen_rango(db, USUARIO, date(2026, 10, 1), date(2026, 10, 31))
    assert (todo.cobrado, todo.gastos) == (Decimal("1480"), Decimal("587.70"))
    assert cliente.get("/gestoria?desde=2026-10-31&hasta=2026-10-01", headers=cab).status_code == 422
    assert cliente.get(f"/gestoria?{OCTUBRE}").status_code == 401


def test_el_csv_dice_lo_mismo_que_el_parte_y_excel_lo_lee(cliente, cab):
    obra = _obra(cliente, cab, "Reforma baño", facturado=True)
    _nuevo(cliente, cab, "trabajo", "Reforma baño", "980", trabajo_id=obra["id"])
    _nuevo(cliente, cab, "gasto", "Azulejos", "210.5", fecha="2026-10-03", trabajo_id=obra["id"])
    _nuevo(cliente, cab, "gasto", "Café", "3.20")

    r = cliente.get(f"/gestoria/csv?{OCTUBRE}", headers=cab)
    assert r.content.startswith(b"\xef\xbb\xbf")
    assert r.content.decode("utf-8-sig").splitlines() == [
        "fecha,tipo,concepto,importe,trabajo,documento",
        "2026-10-03,gasto,Azulejos,210.50,Reforma baño,no",
        "2026-10-10,factura emitida,Reforma baño,980.00,Reforma baño,no",
    ]


# ---------- Con los papeles ----------


@pytest.mark.asyncio
async def test_la_factura_emitida_va_siempre_y_marca_su_trabajo(db, monkeypatch, cliente, cab):
    monkeypatch.setattr(facturas, "NIF_PROPIO", NIF)
    monkeypatch.setattr(facturas, "NOMBRES_PROPIOS", ["YOA INSTALACIONES"])
    _lectura(monkeypatch)
    _, apunte = await _subir(db)
    assert apunte.gestoria  # suelta, pero con su factura: el papel manda

    # Un cobro ya metido en una obra, al colgarle la factura, factura la obra.
    obra = _obra(cliente, cab, "Reforma")
    cobro = _nuevo(cliente, cab, "trabajo", "Reforma", "1210", trabajo_id=obra["id"], fecha="2026-10-20")
    _lectura(monkeypatch, numero="2026-016")
    leido = await facturas.escanear(db, USUARIO, _foto(), "image/jpeg")
    facturas.vincular_emitida(db, USUARIO, leido.factura.id, cobro["id"], cobrada=False)
    assert cliente.get(f"/trabajos/{obra['id']}", headers=cab).json()["trabajo"]["facturado"]


@pytest.mark.asyncio
async def test_el_ticket_dice_de_que_trabajo_es_al_confirmarlo(db, monkeypatch, cliente, cab):
    async def lee(_i, _m):
        return {"total": "23.40", "fecha": "2026-10-12", "comercio": "Ferretería"}

    monkeypatch.setattr(facturas, "leer_ticket", lee)
    obra = _obra(cliente, cab, "Reforma baño", facturado=True)
    leido = await facturas.escanear(db, USUARIO, _foto(), "image/jpeg")
    gasto = cliente.post(f"/facturas/{leido.factura.id}/gasto", headers=cab, json={
        "concepto": "Tornillería", "importe": "23.40", "fecha": "2026-10-12",
        "trabajo_id": obra["id"], "para_gestoria": True}).json()
    assert gasto["trabajo_id"] == obra["id"] and gasto["gestoria"] and not gasto["para_gestoria"]

    otro = await facturas.escanear(db, USUARIO, _foto(), "image/jpeg")
    facturas.anotar_gasto(db, USUARIO, otro.factura.id, "Café", Decimal("3"), date(2026, 10, 13), "web")
    hasta = date(2026, 10, 31)
    assert facturas.pdf_del_periodo(db, USUARIO, date(2026, 10, 13), hasta, solo_gestoria=True) is None
    assert facturas.pdf_del_periodo(db, USUARIO, date(2026, 10, 1), hasta, solo_gestoria=True) is not None
    r = cliente.post(f"/facturas/{otro.factura.id}/gasto", headers=cab, json={
        "concepto": "x", "importe": "1", "trabajo_id": 99999})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_por_el_bot_para_la_gestoria_en_el_texto_marca_el_gasto(db, monkeypatch):
    async def lee(_i, _m):
        return {"total": "45.00", "fecha": "2026-10-12", "comercio": "Gasolinera"}

    monkeypatch.setattr(facturas, "leer_ticket", lee)
    _, marcado = await facturas.escanear_y_anotar(
        db, USUARIO, _foto(), "image/jpeg", "gasolina para la gestoría", "bot")
    assert (marcado.concepto, marcado.para_gestoria, marcado.gestoria) == ("gasolina", True, True)
    leido, sin_marca = await facturas.escanear_y_anotar(db, USUARIO, _foto(), "image/jpeg", "gasolina", "bot")
    assert not sin_marca.gestoria
    from app.bot import formato

    assert "📁 Va a la gestoría" in formato.ticket_anotado(marcado, leido.datos)
    assert "No va a la gestoría" in formato.ticket_anotado(sin_marca, leido.datos)
