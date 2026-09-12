"""La alarma de "los datos no se están guardando".

Tres cosas que tienen que cumplirse, y cada una ha fallado en otro sitio
alguna vez: que avise cuando la base no persiste, que no diga nada cuando
sí (una alarma falsa enseña a ignorar las de verdad), y que avise una vez
por persona y no en cada mensaje, que es la forma de que se deje de leer.
"""
import pytest
from telegram.error import TelegramError

from app.bot import alarma
from app.nucleo.almacenamiento import EstadoAlmacenamiento


def _estado(persistente: bool) -> EstadoAlmacenamiento:
    return EstadoAlmacenamiento(
        motor="sqlite",
        ruta="/data/parte_del_dia.db" if persistente else "./parte_del_dia.db",
        persistente=persistente,
        existe=True,
        tamano_bytes=4096,
        aviso=None if persistente else "La base está en una ruta relativa",
    )


class _Bot:
    def __init__(self, falla=False):
        self.enviados = []
        self.falla = falla

    async def send_message(self, chat_id, text):
        if self.falla:
            raise TelegramError("bot bloqueado")
        self.enviados.append((chat_id, text))


def _contexto(bot):
    # bot_data tiene que sobrevivir entre mensajes: es donde se recuerda a quién
    # se avisó ya.
    return type("C", (), {"bot": bot, "bot_data": {}})()


def _mensaje_de(user_id):
    persona = type("Persona", (), {"id": user_id})()
    return type("U", (), {"effective_user": persona, "effective_chat": persona})()


class TestEnElPrimerMensaje:
    @pytest.mark.asyncio
    async def test_si_la_base_no_se_guarda_lo_dice(self, monkeypatch):
        monkeypatch.setattr(alarma, "estado", lambda: _estado(False))
        bot = _Bot()

        await alarma.avisar_en_el_primer_mensaje(_mensaje_de(1), _contexto(bot))

        assert len(bot.enviados) == 1
        chat_id, texto = bot.enviados[0]
        assert chat_id == 1
        assert "NO SE ESTÁN GUARDANDO" in texto
        assert "ruta relativa" in texto, "tiene que decir por qué, o no se puede arreglar"

    @pytest.mark.asyncio
    async def test_una_vez_por_persona_no_en_cada_mensaje(self, monkeypatch):
        monkeypatch.setattr(alarma, "estado", lambda: _estado(False))
        bot = _Bot()
        contexto = _contexto(bot)

        for _ in range(3):
            await alarma.avisar_en_el_primer_mensaje(_mensaje_de(1), contexto)
        await alarma.avisar_en_el_primer_mensaje(_mensaje_de(2), contexto)

        assert [chat_id for chat_id, _ in bot.enviados] == [1, 2]

    @pytest.mark.asyncio
    async def test_si_se_guarda_no_dice_nada(self, monkeypatch):
        monkeypatch.setattr(alarma, "estado", lambda: _estado(True))
        bot = _Bot()

        await alarma.avisar_en_el_primer_mensaje(_mensaje_de(1), _contexto(bot))

        assert bot.enviados == []

    @pytest.mark.asyncio
    async def test_si_telegram_falla_el_mensaje_sigue_su_camino(self, monkeypatch):
        monkeypatch.setattr(alarma, "estado", lambda: _estado(False))

        await alarma.avisar_en_el_primer_mensaje(_mensaje_de(1), _contexto(_Bot(falla=True)))


class TestAlArrancar:
    @pytest.mark.asyncio
    async def test_avisa_a_los_ids_configurados(self, monkeypatch):
        monkeypatch.setattr(alarma, "estado", lambda: _estado(False))
        monkeypatch.setattr(alarma, "ALARMA_TELEGRAM_IDS", [6529038645, 42])
        bot = _Bot()

        await alarma.avisar_al_arrancar(_contexto(bot))

        assert [chat_id for chat_id, _ in bot.enviados] == [6529038645, 42]

    @pytest.mark.asyncio
    async def test_con_la_base_bien_no_molesta(self, monkeypatch):
        monkeypatch.setattr(alarma, "estado", lambda: _estado(True))
        monkeypatch.setattr(alarma, "ALARMA_TELEGRAM_IDS", [6529038645])
        bot = _Bot()

        await alarma.avisar_al_arrancar(_contexto(bot))

        assert bot.enviados == []

    @pytest.mark.asyncio
    async def test_si_un_id_falla_no_revienta(self, monkeypatch):
        monkeypatch.setattr(alarma, "estado", lambda: _estado(False))
        monkeypatch.setattr(alarma, "ALARMA_TELEGRAM_IDS", [1])

        await alarma.avisar_al_arrancar(_contexto(_Bot(falla=True)))
