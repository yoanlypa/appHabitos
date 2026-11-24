"""Las carteras de efectivo: lo que se rompería en silencio.

- Que un gasto en efectivo apuntado tarde cuente dos veces (él y el "sin
  detallar" del recuento que ya lo incluía).
- Que el primer recuento se invente un gasto (no hay con qué comparar).
- Que lo de la cartera de uno salga en la del otro.
- Que "quedan 3 huevos" se tome por un recuento, o "me quedan 35" por un
  cobro del negocio de Yoa.
"""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.bot import casa as bot_casa
from app.dominio import casa as reglas
from app.dominio.models import GastoCasa
from app.nucleo.tiempo import hoy_local
from app.servicios import casa
from tests.conftest import USUARIO

ELLA = 111222333
HOY = hoy_local()


@pytest.fixture
def pareja(db):
    casa.asegurar_casa(db, USUARIO, "Yoa")
    casa.unirse(db, casa.crear_invitacion(db, USUARIO), ELLA, "María")


def test_frases_de_cartera():
    assert reglas.interpretar_cartera("saco 200") == ("entrada", Decimal("200"))
    assert reglas.interpretar_cartera("me quedan 35,50 €") == ("recuento", Decimal("35.50"))
    assert reglas.interpretar_cartera("quedan 3 huevos") is None
    assert reglas.interpretar_cartera("45 súper") is None


def test_forma_de_pago_se_quita_del_concepto(db, pareja):
    g = casa.anotar_texto(db, USUARIO, "-45 súper con tarjeta")
    assert g.concepto == "Súper" and not g.efectivo
    g = casa.anotar_texto(db, USUARIO, "12 farmacia en efectivo")
    assert g.concepto == "Farmacia" and g.efectivo


def test_sin_decirlo_va_como_paga_casi_siempre(db, pareja):
    assert casa.anotar_texto(db, ELLA, "45 súper").efectivo  # empieza en efectivo
    casa.pago_habitual(db, ELLA, False)
    assert not casa.anotar_texto(db, ELLA, "45 súper").efectivo


def test_el_primer_recuento_es_el_punto_de_partida(db, pareja):
    r = casa.contar_cartera(db, ELLA, Decimal("80"))
    assert r.esperado is None and r.sin_detallar == 0
    assert db.query(GastoCasa).count() == 0
    assert casa.cartera_de(db, ELLA).esperado == Decimal("80")


def test_la_semana_entera(db, pareja):
    casa.contar_cartera(db, ELLA, Decimal("20"))       # domingo pasado (hoy, da igual)
    casa.meter_en_cartera(db, ELLA, Decimal("200"))     # saca del cajero
    casa.anotar_texto(db, ELLA, "45 súper")             # efectivo por defecto
    casa.anotar_texto(db, ELLA, "-30 gasolina con tarjeta")  # no sale de la cartera
    assert casa.cartera_de(db, ELLA).esperado == Decimal("175")
    r = casa.contar_cartera(db, ELLA, Decimal("100"))
    assert r.sin_detallar == Decimal("75")
    hueco = db.get(GastoCasa, r.movimiento.gasto_id)
    assert hueco.concepto == casa.SIN_DETALLAR and hueco.efectivo
    # Tras contar, lo que debería haber es lo contado.
    assert casa.cartera_de(db, ELLA).esperado == Decimal("100")
    resumen = casa.resumen(db, USUARIO, HOY.replace(day=1), HOY)
    assert resumen.sin_detallar == Decimal("75") and resumen.total == Decimal("150")


def test_si_sobra_no_se_inventa_nada(db, pareja):
    casa.contar_cartera(db, ELLA, Decimal("20"))
    r = casa.contar_cartera(db, ELLA, Decimal("50"))
    assert r.sobra == Decimal("30") and r.sin_detallar == 0
    assert db.query(GastoCasa).count() == 0


def test_lo_apuntado_tarde_se_descuenta_de_lo_sin_detallar(db, pareja, monkeypatch):
    # Un recuento de ayer con 40 sin detallar; hoy ella se acuerda de que
    # anteayer pagó 15 de frutería. No puede contar dos veces.
    ayer = HOY - timedelta(days=1)
    monkeypatch.setattr(casa, "hoy_local", lambda: ayer)
    casa.contar_cartera(db, ELLA, Decimal("100"))
    r = casa.contar_cartera(db, ELLA, Decimal("60"))
    assert r.sin_detallar == Decimal("40")
    monkeypatch.setattr(casa, "hoy_local", lambda: HOY)
    casa.crear_gasto(db, ELLA, "Frutería", Decimal("15"), HOY - timedelta(days=2), efectivo=True)
    db.expire_all()
    assert db.get(GastoCasa, r.movimiento.gasto_id).importe == Decimal("25")
    total = casa.resumen(db, USUARIO, HOY - timedelta(days=5), HOY).total
    assert total == Decimal("40")  # 25 sin detallar + 15 de frutería
    # Y no cambia lo que debería haber ahora.
    assert casa.cartera_de(db, ELLA).esperado == Decimal("60")


def test_cada_uno_su_cartera(db, pareja):
    casa.contar_cartera(db, ELLA, Decimal("50"))
    casa.contar_cartera(db, USUARIO, Decimal("10"))
    casa.anotar_texto(db, USUARIO, "20 pan")
    carteras = {c.nombre: c.esperado for c in casa.carteras(db, ELLA)}
    assert carteras == {"Yoa": Decimal("-10"), "María": Decimal("50")}


def test_deshacer_un_recuento_se_lleva_su_hueco(db, pareja):
    casa.contar_cartera(db, ELLA, Decimal("50"))
    r = casa.contar_cartera(db, ELLA, Decimal("20"))
    casa.deshacer_movimiento(db, ELLA, r.movimiento.id)
    assert db.query(GastoCasa).count() == 0
    with pytest.raises(casa.NoEncontrado):
        casa.deshacer_movimiento(db, USUARIO, casa.movimientos_cartera(db, ELLA)[0].id)


def test_me_quedan_35_de_yoa_va_a_su_cartera_no_al_negocio(db, pareja):
    class _M:
        text = "me quedan 35"
        caption = None
        from_user = type("U", (), {"id": USUARIO})()

    assert bot_casa._DE_CASA.filter(_M())
    hecho = casa.anotar_libre(db, USUARIO, "me quedan 35")
    assert hecho.recuento and hecho.recuento.contado == Decimal("35")


def test_borrar_el_hueco_a_mano_no_rompe(db, pareja):
    casa.contar_cartera(db, ELLA, Decimal("50"))
    r = casa.contar_cartera(db, ELLA, Decimal("20"))
    casa.borrar_gasto(db, ELLA, r.movimiento.gasto_id)
    db.expire_all()
    assert casa.movimientos_cartera(db, ELLA)[0].gasto_id is None


class _Consulta:
    def __init__(self, data):
        self.data = data
        self.message = None
        self.texto = None

    async def answer(self, *_a, **_k):
        pass

    async def edit_message_text(self, texto, reply_markup=None):
        self.texto = texto


def _pulsar(data, user_id):
    consulta = _Consulta(data)
    usuario = type("U", (), {"id": user_id})()
    return type("Up", (), {"callback_query": consulta, "effective_user": usuario})(), consulta


@pytest.mark.asyncio
async def test_boton_si_cuadra_y_deshacer(db, pareja):
    casa.contar_cartera(db, ELLA, Decimal("50"))
    casa.anotar_texto(db, ELLA, "20 pan")
    up, consulta = _pulsar("ca:rc:3000", ELLA)
    await bot_casa.tocar(up, None)
    assert "Cuadra" in consulta.texto
    ultimo = casa.movimientos_cartera(db, ELLA)[0]
    up, consulta = _pulsar(f"ca:dm:{ultimo.id}", ELLA)
    await bot_casa.tocar(up, None)
    db.expire_all()
    assert casa.cartera_de(db, ELLA).esperado == Decimal("30")


@pytest.mark.asyncio
async def test_boton_efectivo_tarjeta(db, pareja):
    g = casa.anotar_texto(db, ELLA, "20 pan")
    up, consulta = _pulsar(f"ca:ef:{g.id}", ELLA)
    await bot_casa.tocar(up, None)
    db.expire_all()
    assert not db.get(GastoCasa, g.id).efectivo and "tarjeta" in consulta.texto


@pytest.mark.asyncio
async def test_el_domingo_solo_se_pregunta_a_quien_usa_la_cartera(db, pareja):
    casa.contar_cartera(db, ELLA, Decimal("50"))
    enviados = []

    class _Bot:
        async def send_message(self, chat_id, text, reply_markup=None):
            enviados.append((chat_id, text))

    await bot_casa.preguntar_carteras(type("C", (), {"bot": _Bot()})())
    assert [c for c, _ in enviados] == [ELLA]
    assert "50,00 €" in enviados[0][1]


def test_api_carteras(db, pareja):
    from fastapi.testclient import TestClient

    from app.main import crear_api
    from app.servicios.auth import generar_token

    cab = {"Authorization": f"Bearer {generar_token(db, ELLA)}"}
    with TestClient(crear_api()) as c:
        r = c.post("/casa/cartera/recuento", headers=cab, json={"importe": "50"}).json()
        assert r["esperado"] is None and r["contado"] == "50.00"
        assert c.post("/casa/cartera/entrada", headers=cab, json={"importe": "100"}).status_code == 201
        g = c.post("/casa/gastos", headers=cab, json={"concepto": "Pan", "importe": "10"}).json()
        assert g["efectivo"]  # como paga casi siempre
        mias = {x["nombre"]: x for x in c.get("/casa/carteras", headers=cab).json()}
        assert mias["María"]["esperado"] == "140.00" and mias["Yoa"]["esperado"] is None
        r = c.post("/casa/cartera/recuento", headers=cab, json={"importe": "100"}).json()
        assert r["sin_detallar"] == "40.00"
        hoy = hoy_local().isoformat()
        res = c.get(f"/casa/resumen?desde={hoy}&hasta={hoy}", headers=cab).json()
        assert res["sin_detallar"] == "40.00" and res["efectivo"] == "50.00"
        assert c.patch("/casa/yo", headers=cab, json={"efectivo": False}).json()["efectivo"] is False
        movs = c.get("/casa/cartera/movimientos", headers=cab).json()
        assert c.delete(f"/casa/cartera/{movs[0]['id']}", headers=cab).status_code == 204
