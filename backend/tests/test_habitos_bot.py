"""Los hábitos por Telegram: botones y recordatorios.

Lo que no puede pasar: que el botón del recordatorio desmarque algo que ya
se había marcado desde la web, que un recordatorio llegue dos veces, o que
/habitos ofrezca marcar un hábito que hoy no toca.
"""
from datetime import date, datetime, time

import pytest

from app.bot import habitos as bot_habitos
from app.dominio.models import Habito
from app.servicios import habitos as servicio
from tests.conftest import USUARIO

MIERCOLES = date(2026, 9, 9)
TODOS = list(range(7))


@pytest.fixture
def hoy(monkeypatch):
    monkeypatch.setattr(servicio, "hoy_local", lambda: MIERCOLES)
    monkeypatch.setattr(bot_habitos, "ahora_local", lambda: datetime.combine(MIERCOLES, time(12, 5)))


class _Mensaje:
    def __init__(self):
        self.respuestas = []

    async def reply_text(self, texto, reply_markup=None):
        self.respuestas.append((texto, reply_markup))


class _Consulta:
    def __init__(self, data):
        self.data = data
        self.from_user = type("Usuario", (), {"id": USUARIO})()
        self.avisos = []
        self.editado = None

    async def answer(self, texto=None, show_alert=False):
        self.avisos.append(texto)

    async def edit_message_text(self, texto, reply_markup=None):
        self.editado = (texto, reply_markup)


class _Bot:
    def __init__(self):
        self.enviados = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.enviados.append((chat_id, text, reply_markup))


def _update_con_mensaje():
    mensaje = _Mensaje()
    usuario = type("Usuario", (), {"id": USUARIO})()
    return type("U", (), {"message": mensaje, "effective_user": usuario})(), mensaje


def _pulsar(data):
    consulta = _Consulta(data)
    return type("U", (), {"callback_query": consulta})(), consulta


def _botones(teclado):
    return [boton.text for fila in teclado.inline_keyboard for boton in fila]


class TestHabitos:
    @pytest.mark.asyncio
    async def test_solo_ofrece_botones_para_lo_que_toca_hoy(self, db, hoy):
        servicio.crear(db, USUARIO, "Beber agua", TODOS)
        servicio.crear(db, USUARIO, "Limpiar la furgo", [5, 6])  # fines de semana

        update, mensaje = _update_con_mensaje()
        await bot_habitos.habitos(update, None)

        texto, teclado = mensaje.respuestas[0]
        assert "Beber agua" in texto
        assert "Hoy no tocan: Limpiar la furgo" in texto
        assert _botones(teclado) == ["⬜ Beber agua"]

    @pytest.mark.asyncio
    async def test_tocar_marca_y_otra_vez_desmarca(self, db, hoy):
        habito = servicio.crear(db, USUARIO, "Beber agua", TODOS)

        update, consulta = _pulsar(f"hab:{habito.id}:lista")
        await bot_habitos.tocar(update, None)
        texto, teclado = consulta.editado
        assert "✅ Beber agua — 1 día seguido" in texto
        assert _botones(teclado) == ["✅ Beber agua"]

        update, consulta = _pulsar(f"hab:{habito.id}:lista")
        await bot_habitos.tocar(update, None)
        assert "⬜ Beber agua" in consulta.editado[0]

    @pytest.mark.asyncio
    async def test_el_boton_del_recordatorio_nunca_desmarca(self, db, hoy):
        """Marcado en la web y luego tocado el recordatorio: sigue marcado."""
        habito = servicio.crear(db, USUARIO, "Beber agua", TODOS)
        servicio.marcar(db, USUARIO, habito.id)

        update, consulta = _pulsar(f"hab:{habito.id}:aviso")
        await bot_habitos.tocar(update, None)

        assert servicio.resumen(db, USUARIO, habito.id).hecho_hoy is True
        assert consulta.editado[0].startswith("✅ Beber agua")

    @pytest.mark.asyncio
    async def test_un_habito_borrado_se_explica(self, db, hoy):
        update, consulta = _pulsar("hab:999999:lista")
        await bot_habitos.tocar(update, None)

        assert consulta.avisos == ["Ese hábito ya no existe."]


class TestRecordatorios:
    @pytest.mark.asyncio
    async def test_llega_una_sola_vez_con_su_boton(self, db, hoy):
        habito = servicio.crear(db, USUARIO, "Beber agua", TODOS, time(12, 0))
        bot = _Bot()
        contexto = type("C", (), {"bot": bot})()

        await bot_habitos.recordar(contexto)
        await bot_habitos.recordar(contexto)  # el minuto siguiente

        assert len(bot.enviados) == 1
        chat_id, texto, teclado = bot.enviados[0]
        assert chat_id == USUARIO
        assert "Beber agua" in texto
        assert _botones(teclado) == ["Hecho ✓"]
        db.expire_all()
        assert db.get(Habito, habito.id).recordado_el == MIERCOLES
