"""Trabajos con sus gastos, y qué va a la gestoría.

Lo que se rompería en silencio, y sale caro porque se descubre cuando la
gestoría ya ha presentado el trimestre: un gasto de un trabajo que factura
otra empresa colándose en lo que se manda; un gasto que se cae de la lista al
borrar su trabajo; o el listado, el CSV y el PDF diciendo cosas distintas.
"""
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.dominio.gestoria import marca_gestoria, va_a_gestoria
from app.dominio.models import Apunte
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
    lista = cliente.get(f"/apuntes/rango?desde=2026-01-01&hasta=2026-11-01", headers=cab).json()
    return next(a for a in lista if a["id"] == apunte_id)


# ---------- La regla ----------


def test_la_regla_de_que_va_y_que_no():
    assert va_a_gestoria("trabajo", True, False, None)
    assert not va_a_gestoria("trabajo", False, False, None)
    # Un gasto de un trabajo sigue a su trabajo, lleve la marca que lleve.
    assert va_a_gestoria("gasto", False, False, True)
    assert not va_a_gestoria("gasto", False, True, False)
    # Un gasto suelto solo va si se ha marcado a mano.
    assert va_a_gestoria("gasto", False, True, None)
    assert not va_a_gestoria("gasto", False, False, None)
    assert not va_a_gestoria("nota", True, True, True)


def test_para_la_gestoria_en_el_texto_de_la_foto():
    assert marca_gestoria("material baño para la gestoría") == (True, "material baño")
    assert marca_gestoria("Para gestoria 15/10 gasolina") == (True, "15/10 gasolina")
    assert marca_gestoria("gestoría") == (True, "")
    # La palabra dentro del concepto no es una orden: es lo que se ha pagado.
    assert marca_gestoria("Factura gestoría octubre") == (False, "Factura gestoría octubre")
    assert marca_gestoria(None) == (False, "")


# ---------- Gastos de un trabajo ----------


def test_el_gasto_sigue_a_su_trabajo_sin_tocarlo(cliente, cab):
    trabajo = _nuevo(cliente, cab, "trabajo", "Reforma baño Luis", "980")
    gasto = _nuevo(cliente, cab, "gasto", "Azulejos", "210.50", trabajo_id=trabajo["id"])
    assert gasto["trabajo_id"] == trabajo["id"] and gasto["trabajo_concepto"] == "Reforma baño Luis"
    assert not trabajo["facturado"] and not gasto["gestoria"]

    # Se factura el trabajo: su gasto entra solo, nadie lo ha editado.
    assert _editar(cliente, cab, trabajo["id"], facturado=True).json()["gestoria"]
    assert _apunte(cliente, cab, gasto["id"])["gestoria"]
    # Y sale igual de solo si resulta que no lo facturaba él.
    _editar(cliente, cab, trabajo["id"], facturado=False)
    assert not _apunte(cliente, cab, gasto["id"])["gestoria"]


def test_el_suelto_se_marca_a_mano_y_la_marca_no_reaparece(cliente, cab):
    trabajo = _nuevo(cliente, cab, "trabajo", "Obra de la otra empresa", "500")
    gasto = _nuevo(cliente, cab, "gasto", "Gasolina", "45", para_gestoria=True)
    assert gasto["gestoria"] and gasto["para_gestoria"]

    # Se cuelga de un trabajo que NO factura Yoa: deja de ir.
    colgado = _editar(cliente, cab, gasto["id"], trabajo_id=trabajo["id"]).json()
    assert not colgado["gestoria"] and not colgado["para_gestoria"]
    # Se descuelga: no vuelve a ir por una marca vieja que ya nadie recuerda.
    suelto = _editar(cliente, cab, gasto["id"], trabajo_id=None).json()
    assert suelto["trabajo_id"] is None and not suelto["gestoria"]


def test_un_gasto_solo_cuelga_de_un_trabajo_propio(cliente, cab, db):
    gasto = _nuevo(cliente, cab, "gasto", "Pintura", "30")
    otro_gasto = _nuevo(cliente, cab, "gasto", "Brochas", "12")
    ajeno = Apunte(user_id=111, fecha=date(2026, 10, 1), tipo="trabajo", concepto="De otro",
                   importe=Decimal("100"), pendiente=False, origen="web")
    db.add(ajeno)
    db.commit()

    assert _editar(cliente, cab, gasto["id"], trabajo_id=ajeno.id).status_code == 422
    assert _editar(cliente, cab, gasto["id"], trabajo_id=otro_gasto["id"]).status_code == 422
    assert _editar(cliente, cab, gasto["id"], trabajo_id=99999).status_code == 422
    r = cliente.post("/apuntes/movimiento", headers=cab, json={
        "tipo": "gasto", "concepto": "x", "importe": "1", "trabajo_id": ajeno.id})
    assert r.status_code == 422
    assert _apunte(cliente, cab, gasto["id"])["trabajo_id"] is None


def test_las_marcas_solo_valen_para_su_tipo(cliente, cab):
    trabajo = _nuevo(cliente, cab, "trabajo", "Reforma", "980", para_gestoria=True)
    assert not trabajo["para_gestoria"]  # eso es de los gastos sueltos
    gasto = _nuevo(cliente, cab, "gasto", "Azulejos", "10", facturado=True)
    assert not gasto["facturado"] and not gasto["gestoria"]  # un gasto no se "factura"


def test_borrar_un_trabajo_facturado_no_saca_sus_gastos_de_la_gestoria(cliente, cab):
    trabajo = _nuevo(cliente, cab, "trabajo", "Reforma baño", "980", facturado=True)
    gasto = _nuevo(cliente, cab, "gasto", "Azulejos", "210", trabajo_id=trabajo["id"])
    assert cliente.delete(f"/apuntes/{trabajo['id']}", headers=cab).status_code == 204

    suelto = _apunte(cliente, cab, gasto["id"])
    assert suelto["trabajo_id"] is None
    assert suelto["gestoria"] and suelto["para_gestoria"]  # conserva lo que valía


def test_un_trabajo_que_pasa_a_gasto_suelta_los_suyos(cliente, cab):
    trabajo = _nuevo(cliente, cab, "trabajo", "Mal apuntado", "100")
    gasto = _nuevo(cliente, cab, "gasto", "Tornillos", "5", trabajo_id=trabajo["id"])
    cambiado = _editar(cliente, cab, trabajo["id"], tipo="gasto").json()
    assert cambiado["tipo"] == "gasto" and not cambiado["facturado"]
    assert _apunte(cliente, cab, gasto["id"])["trabajo_id"] is None


def test_la_ficha_del_trabajo_suma_sus_gastos(cliente, cab):
    trabajo = _nuevo(cliente, cab, "trabajo", "Reforma baño", "980")
    _nuevo(cliente, cab, "gasto", "Azulejos", "210.50", trabajo_id=trabajo["id"])
    _nuevo(cliente, cab, "gasto", "Cemento", "0.10", trabajo_id=trabajo["id"])
    _nuevo(cliente, cab, "gasto", "Gasolina", "45")  # suelto: no es de este trabajo

    ficha = cliente.get(f"/apuntes/{trabajo['id']}/ficha", headers=cab).json()
    assert [g["concepto"] for g in ficha["gastos"]] == ["Azulejos", "Cemento"]
    assert (ficha["total_gastos"], ficha["beneficio"]) == ("210.60", "769.40")
    # Solo de trabajos, y solo de los suyos.
    gasto_id = ficha["gastos"][0]["id"]
    assert cliente.get(f"/apuntes/{gasto_id}/ficha", headers=cab).status_code == 404
    assert cliente.get(f"/apuntes/{trabajo['id']}/ficha").status_code == 401


def test_los_trabajos_para_elegir_son_solo_trabajos_y_los_recientes_primero(cliente, cab):
    viejo = _nuevo(cliente, cab, "trabajo", "Viejo", "100", fecha="2026-09-01")
    nuevo = _nuevo(cliente, cab, "trabajo", "Nuevo", "100", fecha="2026-10-20")
    _nuevo(cliente, cab, "gasto", "Gasolina", "45")
    lista = cliente.get("/apuntes/trabajos", headers=cab).json()
    assert [t["id"] for t in lista] == [nuevo["id"], viejo["id"]]


# ---------- El parte de la gestoría ----------


def test_el_parte_reparte_el_periodo_en_lo_que_va_y_lo_que_no(cliente, cab, db):
    facturado = _nuevo(cliente, cab, "trabajo", "Reforma baño", "980", facturado=True)
    de_otra = _nuevo(cliente, cab, "trabajo", "Obra de la otra empresa", "500")
    _nuevo(cliente, cab, "gasto", "Azulejos", "210.50", trabajo_id=facturado["id"])
    _nuevo(cliente, cab, "gasto", "Material obra ajena", "80", trabajo_id=de_otra["id"])
    _nuevo(cliente, cab, "gasto", "Cuota autónomos", "294", fecha="2026-10-31", para_gestoria=True)
    _nuevo(cliente, cab, "gasto", "Café", "3.20", fecha="2026-10-01")
    _nuevo(cliente, cab, "gasto", "De septiembre", "99", fecha="2026-09-30", para_gestoria=True)
    db.add(Apunte(user_id=111, fecha=date(2026, 10, 5), tipo="trabajo", concepto="De otro usuario",
                  importe=Decimal("777"), pendiente=False, origen="web", facturado=True))
    db.add(Apunte(user_id=USUARIO, fecha=date(2026, 10, 5), tipo="nota", concepto="Llamar",
                  importe=Decimal("0"), pendiente=False, origen="web"))
    db.commit()

    parte = cliente.get(f"/gestoria?{OCTUBRE}", headers=cab).json()
    nombres = lambda clave: [a["concepto"] for a in parte[clave]]
    assert nombres("emitidas") == ["Reforma baño"]
    assert nombres("recibidas") == ["Azulejos", "Cuota autónomos"]  # del 10 y del 31: extremos dentro
    assert nombres("trabajos_fuera") == ["Obra de la otra empresa"]
    assert nombres("gastos_fuera") == ["Café", "Material obra ajena"]
    assert (parte["facturado"], parte["gastos"], parte["diferencia"]) == ("980.00", "504.50", "475.50")
    # Ninguno tiene su papel colgado, y eso se dice: la gestoría lo va a pedir.
    assert parte["sin_documento"] == 3

    # En las cuentas de Yoa sigue estando todo, facturado o no.
    todo = resumen_rango(db, USUARIO, date(2026, 10, 1), date(2026, 10, 31))
    assert (todo.cobrado, todo.gastos) == (Decimal("1480"), Decimal("587.70"))

    assert cliente.get("/gestoria?desde=2026-10-31&hasta=2026-10-01", headers=cab).status_code == 422
    assert cliente.get(f"/gestoria?{OCTUBRE}").status_code == 401


def test_el_csv_dice_lo_mismo_que_el_parte_y_excel_lo_lee(cliente, cab):
    trabajo = _nuevo(cliente, cab, "trabajo", "Reforma baño", "980", facturado=True)
    _nuevo(cliente, cab, "gasto", "Azulejos", "210.5", fecha="2026-10-03", trabajo_id=trabajo["id"])
    _nuevo(cliente, cab, "gasto", "Café", "3.20")

    r = cliente.get(f"/gestoria/csv?{OCTUBRE}", headers=cab)
    assert r.content.startswith(b"\xef\xbb\xbf")  # BOM: sin él, "baño" sale "baÃ±o" en Excel
    lineas = r.content.decode("utf-8-sig").splitlines()
    assert lineas == [
        "fecha,tipo,concepto,importe,trabajo,documento",
        "2026-10-03,gasto,Azulejos,210.50,Reforma baño,no",
        "2026-10-10,factura emitida,Reforma baño,980.00,,no",
    ]


# ---------- Con los papeles ----------


@pytest.mark.asyncio
async def test_colgarle_la_factura_a_un_trabajo_lo_deja_facturado(db, monkeypatch, cliente, cab):
    monkeypatch.setattr(facturas, "NIF_PROPIO", NIF)
    monkeypatch.setattr(facturas, "NOMBRES_PROPIOS", ["YOA INSTALACIONES"])
    _lectura(monkeypatch)
    _, apunte = await _subir(db)
    assert apunte.facturado and apunte.gestoria

    # El papel manda: con la factura colgada no se puede decir que no está facturado.
    assert _editar(cliente, cab, apunte.id, facturado=False).json()["facturado"]
    parte = cliente.get(f"/gestoria?{OCTUBRE}", headers=cab).json()
    assert [a["id"] for a in parte["emitidas"]] == [apunte.id] and parte["sin_documento"] == 0


@pytest.mark.asyncio
async def test_el_ticket_dice_de_que_trabajo_es_al_confirmarlo(db, monkeypatch, cliente, cab):
    async def lee(_i, _m):
        return {"total": "23.40", "fecha": "2026-10-12", "comercio": "Ferretería"}

    monkeypatch.setattr(facturas, "leer_ticket", lee)
    trabajo = _nuevo(cliente, cab, "trabajo", "Reforma baño", "980", facturado=True)
    leido = await facturas.escanear(db, USUARIO, _foto(), "image/jpeg")
    gasto = cliente.post(f"/facturas/{leido.factura.id}/gasto", headers=cab, json={
        "concepto": "Tornillería", "importe": "23.40", "fecha": "2026-10-12",
        "trabajo_id": trabajo["id"], "para_gestoria": True}).json()
    assert gasto["trabajo_id"] == trabajo["id"] and gasto["gestoria"] and not gasto["para_gestoria"]

    # El PDF para la gestoría lleva este ticket; el de un gasto sin marcar, no.
    otro = await facturas.escanear(db, USUARIO, _foto(), "image/jpeg")
    facturas.anotar_gasto(db, USUARIO, otro.factura.id, "Café", Decimal("3"), date(2026, 10, 13), "web")
    hasta = date(2026, 10, 31)
    assert facturas.pdf_del_periodo(db, USUARIO, date(2026, 10, 13), hasta, solo_gestoria=True) is None
    assert facturas.pdf_del_periodo(db, USUARIO, date(2026, 10, 13), hasta) is not None
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
    # Y el bot lo dice en los dos casos: lo que no va, que se sepa al subirlo.
    from app.bot import formato

    assert "📁 Va a la gestoría" in formato.ticket_anotado(marcado, leido.datos)
    assert "No va a la gestoría" in formato.ticket_anotado(sin_marca, leido.datos)
