"""Las facturas que emite Yoa: entran como trabajo pendiente, no como gasto.

Lo que se rompería en silencio: una compra de Yoa (donde su NIF sale como
cliente) tomada por factura suya y contada como ingreso; un trabajo ya
apuntado contado dos veces al subir su factura; o una factura cobrada que
sigue figurando como deuda.
"""
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.dominio.models import Apunte, Cliente
from app.main import crear_api
from app.servicios import facturas
from app.servicios.auth import generar_token
from app.servicios.resumen import resumen_rango
from tests.conftest import USUARIO
from tests.test_facturas import _foto

NIF = "Z0000000T"  # de mentira: el de verdad va en Railway, no en el repo


@pytest.fixture(autouse=True)
def nif_propio(monkeypatch):
    monkeypatch.setattr(facturas, "NIF_PROPIO", NIF)
    monkeypatch.setattr(facturas, "NOMBRES_PROPIOS", ["YOA INSTALACIONES"])


def _lectura(monkeypatch, **cambios):
    datos = {
        "total": "1210", "fecha": "2026-10-20", "comercio": "YOA INSTALACIONES", "cif": NIF,
        "numero": "2026-015", "concepto": "reforma baño", "base_imponible": "1000", "iva": "210",
        "destinatario": {"nombre": "Iris Galerie", "nif": "B11111111", "direccion": "C/ Larios 1"},
    }
    datos.update(cambios)

    async def falso(_i, _m):
        return dict(datos)

    monkeypatch.setattr(facturas, "leer_ticket", falso)


async def _subir(db, texto=None):
    return await facturas.escanear_y_anotar(db, USUARIO, _foto(), "image/jpeg", texto, "bot")


@pytest.mark.asyncio
async def test_factura_propia_es_un_trabajo_pendiente_con_cliente_nuevo(db, monkeypatch):
    _lectura(monkeypatch)
    leido, apunte = await _subir(db)
    assert leido.emitida is not None and leido.factura.emitida
    assert (apunte.tipo, apunte.importe, apunte.pendiente) == ("trabajo", Decimal("1210.00"), True)
    assert apunte.fecha == date(2026, 10, 20)
    assert apunte.concepto == "Fra. 2026-015 · reforma baño · Iris Galerie"
    cliente = db.query(Cliente).one()
    assert (cliente.nombre, cliente.notas) == ("Iris Galerie", "NIF: B11111111")
    assert apunte.cliente_id == cliente.id and leido.emitida.cliente_nuevo
    # Pendiente: no cuenta como cobrado hasta que se cobre.
    r = resumen_rango(db, USUARIO, date(2026, 10, 1), date(2026, 10, 31))
    assert (r.cobrado, r.pendiente, r.gastos) == (0, Decimal("1210.00"), 0)


@pytest.mark.asyncio
async def test_con_cobrado_en_el_mensaje_entra_cobrada(db, monkeypatch):
    _lectura(monkeypatch)
    _, apunte = await _subir(db, "cobrado")
    assert not apunte.pendiente
    assert "cobrado" not in apunte.concepto


@pytest.mark.asyncio
async def test_una_compra_con_el_nif_de_yoa_como_cliente_sigue_siendo_gasto(db, monkeypatch):
    _lectura(monkeypatch, comercio="Leroy Merlin", cif="B84818442",
             destinatario={"nombre": "Yoanly Perez", "nif": NIF})
    leido, apunte = await _subir(db)
    assert leido.emitida is None and apunte.tipo == "gasto"


@pytest.mark.asyncio
async def test_se_cuelga_del_trabajo_ya_apuntado_y_no_cuenta_doble(db, monkeypatch):
    cliente = Cliente(user_id=USUARIO, nombre="Iris Galerie")
    db.add(cliente)
    db.commit()
    previo = Apunte(user_id=USUARIO, fecha=date(2026, 10, 18), tipo="trabajo", concepto="Reforma baño",
                    importe=Decimal("1210"), pendiente=True, origen="bot", cliente_id=cliente.id)
    db.add(previo)
    db.commit()
    _lectura(monkeypatch)
    leido, apunte = await _subir(db)
    assert apunte.id == previo.id and leido.emitida.vinculada
    assert db.query(Apunte).filter(Apunte.tipo == "trabajo").count() == 1
    assert not leido.emitida.cliente_nuevo


@pytest.mark.asyncio
async def test_con_dos_posibles_se_pregunta_y_se_elige(db, monkeypatch):
    cliente = Cliente(user_id=USUARIO, nombre="Iris Galerie")
    db.add(cliente)
    db.commit()
    for d in (5, 12):
        db.add(Apunte(user_id=USUARIO, fecha=date(2026, 10, d), tipo="trabajo", concepto=f"t{d}",
                      importe=Decimal("1210"), pendiente=True, origen="bot", cliente_id=cliente.id))
    db.commit()
    _lectura(monkeypatch)
    leido, apunte = await _subir(db)
    assert apunte is None and len(leido.emitida.candidatos) == 2
    elegido = leido.emitida.candidatos[1]
    hecho = facturas.vincular_emitida(db, USUARIO, leido.factura.id, elegido.id, cobrada=True)
    assert hecho.id == elegido.id and not hecho.pendiente and hecho.factura_emitida


@pytest.mark.asyncio
async def test_la_retencion_se_descuenta_de_lo_que_entra(db, monkeypatch):
    _lectura(monkeypatch, total="1210", retencion="150")
    _, apunte = await _subir(db)
    assert apunte.importe == Decimal("1060.00")


@pytest.mark.asyncio
async def test_pdf_del_mes_separa_emitidas_de_tickets(db, monkeypatch):
    _lectura(monkeypatch)
    await _subir(db)
    _lectura(monkeypatch, comercio="Leroy Merlin", cif="B84818442", destinatario=None, total="8")
    await _subir(db)
    desde, hasta = date(2026, 10, 1), date(2026, 10, 31)
    emitidas = facturas.pdf_del_periodo(db, USUARIO, desde, hasta, emitidas=True)
    tickets = facturas.pdf_del_periodo(db, USUARIO, desde, hasta)
    paginas = lambda pdf: pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages")
    assert paginas(emitidas) == 1 and paginas(tickets) == 1


def test_por_la_web_se_ve_antes_y_se_confirma(db, monkeypatch):
    _lectura(monkeypatch)
    with TestClient(crear_api()) as cliente:
        cab = {"Authorization": f"Bearer {generar_token(db, USUARIO)}"}
        r = cliente.post("/facturas/escanear", headers=cab, files={"imagen": ("f.jpg", _foto(), "image/jpeg")})
        leido = r.json()
        assert leido["emitida"] and leido["cliente"] == "Iris Galerie" and leido["a_cobrar"] == "1210.00"
        # Ver no anota nada ni da de alta a nadie.
        assert db.query(Cliente).count() == 0
        r = cliente.post(f"/facturas/{leido['factura_id']}/emitida", headers=cab,
                         json={"cobrada": False, "importe": "1210", "concepto": "Reforma baño Iris"})
        assert r.status_code == 201
        a = r.json()
        assert (a["tipo"], a["pendiente"], a["factura_emitida"]) == ("trabajo", True, True)


@pytest.mark.asyncio
async def test_a_nombre_del_autonomo_y_con_tildes(db, monkeypatch):
    """Factura real: emisor la persona, no la marca, y con tilde."""
    monkeypatch.setattr(facturas, "NOMBRES_PROPIOS", ["YOA INSTALACIONES", "YOANLY PEREZ ACOSTA"])
    _lectura(monkeypatch, comercio="YOANLY PÉREZ ACOSTA", cif=None)
    leido, apunte = await _subir(db)
    assert leido.emitida is not None and apunte.tipo == "trabajo"


@pytest.mark.asyncio
async def test_el_nif_del_emisor_gana_aunque_la_ia_lo_repita_en_el_cliente(db, monkeypatch):
    _lectura(monkeypatch, comercio="Fulano", destinatario={"nombre": "Iris Galerie", "nif": NIF})
    leido, _ = await _subir(db)
    assert leido.emitida is not None


@pytest.mark.asyncio
async def test_mia_en_el_mensaje_la_fuerza(db, monkeypatch):
    _lectura(monkeypatch, comercio="Fulano", cif=None)
    leido, apunte = await _subir(db, "mía cobrada")
    assert leido.emitida is not None and not apunte.pendiente
    assert "mía" not in apunte.concepto


@pytest.mark.asyncio
async def test_emitida_convierte_un_gasto_que_era_factura_propia(db, monkeypatch):
    _lectura(monkeypatch, comercio="Fulano", cif=None)
    _, gasto = await _subir(db)
    assert gasto.tipo == "gasto"
    hecho = facturas.convertir_en_emitida(db, USUARIO, gasto.id, cobrada=False)
    assert (hecho.tipo, hecho.pendiente, hecho.factura_emitida) == ("trabajo", True, True)
    assert hecho.cliente.nombre == "Iris Galerie"
    with pytest.raises(facturas.GastoNoValido):
        facturas.convertir_en_emitida(db, USUARIO, gasto.id, cobrada=False)


@pytest.mark.asyncio
async def test_aprende_el_emisor_al_corregir_y_la_siguiente_entra_sola(db, monkeypatch):
    """Sin nada en Railway: la primera entra como gasto, se corrige con
    /emitida, y la siguiente con el mismo formato ya es suya. Pasó con las
    facturas de Yoa a nombre de la persona, todas iguales."""
    monkeypatch.setattr(facturas, "NIF_PROPIO", "")
    monkeypatch.setattr(facturas, "NOMBRES_PROPIOS", [])
    _lectura(monkeypatch, comercio="FULANO PÉREZ", razon_social="FULANO PÉREZ GÓMEZ", cif="Y1111111H")
    _, primera = await _subir(db)
    assert primera.tipo == "gasto"
    facturas.convertir_en_emitida(db, USUARIO, primera.id, cobrada=False)

    # La IA no siempre copia igual: sin tilde y el NIF con guion.
    _lectura(monkeypatch, comercio="FULANO PEREZ", razon_social=None, cif="Y-1111111-H", numero="2026-016")
    leido, segunda = await _subir(db)
    assert leido.emitida is not None and segunda.tipo == "trabajo" and segunda.pendiente


@pytest.mark.asyncio
async def test_lo_aprendido_no_vuelve_suya_una_compra(db, monkeypatch):
    """Su NIF aprendido sale como cliente en Leroy Merlin: eso sigue siendo gasto."""
    monkeypatch.setattr(facturas, "NIF_PROPIO", "")
    monkeypatch.setattr(facturas, "NOMBRES_PROPIOS", [])
    _lectura(monkeypatch, comercio="FULANO PEREZ", razon_social=None, cif="Y1111111H")
    _, primera = await _subir(db, "mía")
    assert primera.tipo == "trabajo"

    _lectura(
        monkeypatch, comercio="Leroy Merlin", razon_social="LEROY MERLIN ESPAÑA S.L.U.",
        cif="B84818442", destinatario={"nombre": "FULANO PEREZ", "nif": "Y1111111H"},
    )
    _, compra = await _subir(db)
    assert compra.tipo == "gasto"


@pytest.mark.asyncio
async def test_aprender_dos_veces_no_duplica(db, monkeypatch):
    from app.dominio.models import EmisorPropio

    monkeypatch.setattr(facturas, "NIF_PROPIO", "")
    monkeypatch.setattr(facturas, "NOMBRES_PROPIOS", [])
    _lectura(monkeypatch, comercio="FULANO PEREZ", razon_social=None, cif="Y1111111H")
    await _subir(db, "mía")
    await _subir(db, "mía")
    assert db.query(EmisorPropio).count() == 1
