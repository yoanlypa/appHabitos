"""Casa en el bot: que lo de ella vaya a Casa y lo de Yoa siga en el negocio.

El error caro aquí es silencioso: un "45 súper" de la esposa anotado como un
cobro de 45 € en el negocio de Yoa, o un "-45 gasolina" de Yoa que se va a
Casa. También que el handler de Casa se registre después del que anota.
"""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.bot import casa as bot_casa
from app.bot import handlers
from app.dominio.models import Apunte, GastoCasa
from app.nucleo.tiempo import hoy_local
from app.servicios import casa
from tests.conftest import USUARIO

ELLA = 111222333


class _Chat:
    async def send_action(self, _accion):
        pass


class _Usuario:
    def __init__(self, user_id, nombre="María"):
        self.id = user_id
        self.first_name = nombre
        self.username = None


class _Mensaje:
    def __init__(self, texto=None, user_id=ELLA, caption=None):
        self.text = texto
        self.caption = caption
        self.from_user = _Usuario(user_id)
        self.chat = _Chat()
        self.respuestas = []

    async def reply_text(self, texto, reply_markup=None, **_):
        self.respuestas.append((texto, reply_markup))


def _update(mensaje, user_id=ELLA):
    return type("U", (), {"message": mensaje, "effective_user": _Usuario(user_id)})()


def _contexto(args=None):
    return type("C", (), {"args": args or [], "user_data": {}})()


@pytest.fixture
def ella_en_casa(db):
    casa.asegurar_casa(db, USUARIO, "Yoa")
    casa.unirse(db, casa.crear_invitacion(db, USUARIO), ELLA, "María")


def test_el_filtro_solo_se_queda_lo_de_casa(db, ella_en_casa):
    assert bot_casa._DE_CASA.filter(_Mensaje("45 súper", ELLA))
    assert not bot_casa._DE_CASA.filter(_Mensaje("-45 gasolina", USUARIO))  # Yoa: negocio
    assert bot_casa._DE_CASA.filter(_Mensaje("casa -45 súper", USUARIO))
    assert not bot_casa._DE_CASA.filter(_Mensaje("casado con la obra 120", USUARIO))
    assert not bot_casa._MIEMBRO.filter(_Mensaje("/start", USUARIO))


@pytest.mark.asyncio
async def test_lo_de_ella_va_a_casa_y_no_al_negocio(db, ella_en_casa):
    m = _Mensaje("45 súper")
    await bot_casa.texto(_update(m), _contexto())
    assert "Gasto de casa" in m.respuestas[0][0] and "pagó María" in m.respuestas[0][0]
    assert db.query(Apunte).count() == 0
    assert db.query(GastoCasa).one().importe == Decimal("45")

    m = _Mensaje("leche, huevos y pan")
    await bot_casa.texto(_update(m), _contexto())
    assert "A la lista" in m.respuestas[0][0]
    assert len(casa.listar_articulos(db, USUARIO)) == 3


@pytest.mark.asyncio
async def test_yoa_manda_a_casa_con_el_prefijo(db, ella_en_casa):
    m = _Mensaje("casa -80 mercadona", USUARIO)
    await bot_casa.texto(_update(m, USUARIO), _contexto())
    gasto = db.query(GastoCasa).one()
    assert gasto.concepto == "Mercadona" and gasto.user_id == USUARIO


@pytest.mark.asyncio
async def test_tachar_desde_la_lista(db, ella_en_casa):
    leche, = casa.anadir(db, ELLA, ["Leche"])

    class _Consulta:
        data = f"ca:hay:{leche.id}"
        message = _Mensaje()

        async def answer(self, *_a, **_k):
            pass

        async def edit_message_text(self, texto, reply_markup=None):
            self.texto = texto

    consulta = _Consulta()
    await bot_casa.tocar(type("U", (), {"callback_query": consulta, "effective_user": _Usuario(USUARIO)})(), None)
    db.expire_all()
    assert casa.listar_articulos(db, ELLA)[0].hay
    assert "En casa: Leche" in consulta.texto


@pytest.mark.asyncio
async def test_unirme_por_telegram(db):
    codigo = casa.crear_invitacion(db, USUARIO)
    m = _Mensaje(f"/unirme {codigo}")
    await bot_casa.unirme(_update(m), _contexto([codigo]))
    assert "Hecho, María" in m.respuestas[0][0]
    assert casa.solo_casa(db, ELLA)


def test_casa_va_antes_que_el_handler_que_anota(monkeypatch):
    from app.bot import main

    monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "123456:ABC-de-mentira")
    app = main.construir_app()
    registrados = app.handlers[0]
    de_casa = next(i for i, h in enumerate(registrados) if getattr(h, "callback", None) is bot_casa.texto)
    anota = next(i for i, h in enumerate(registrados) if getattr(h, "callback", None) is handlers.anotar)
    assert de_casa < anota
    # La voz tiene un solo handler para todos: decide `servicios/casa.es_de_casa`
    # (tests/test_voz.py), no el orden de registro.
    assert not hasattr(bot_casa, "voz")
