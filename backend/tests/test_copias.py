"""La copia de seguridad por Telegram.

Se prueba de verdad el contenido del fichero, no solo que se llame a la API
de Telegram: una copia que llegue vacía o ilegible no sirve de nada, y de
eso uno se entera el día que la necesita.
"""
import pytest

from app.bot import copias
from app.servicios.apuntes import crear_apunte
from tests.conftest import USUARIO


class BotFalso:
    def __init__(self, falla=False):
        self.enviados = []
        self.falla = falla

    async def send_document(self, chat_id, document, caption=None):
        if self.falla:
            from telegram.error import Forbidden

            raise Forbidden("bot bloqueado")
        self.enviados.append(
            {
                "chat_id": chat_id,
                "nombre": document.name,
                "contenido": document.getvalue().decode("utf-8-sig"),
                "caption": caption,
            }
        )


def contexto_con(bot):
    return type("C", (), {"bot": bot})()


@pytest.mark.asyncio
async def test_la_copia_lleva_los_apuntes(db):
    crear_apunte(db, USUARIO, "Cambio de grifo 120,50", origen="bot")
    crear_apunte(db, USUARIO, "-45 gasolina", origen="web")

    bot = BotFalso()
    assert await copias.enviar_copia(contexto_con(bot), USUARIO) is True

    enviado = bot.enviados[0]
    assert enviado["chat_id"] == USUARIO
    assert enviado["nombre"].endswith(".csv")

    lineas = enviado["contenido"].strip().splitlines()
    assert lineas[0] == "fecha,tipo,concepto,importe,pendiente,origen"
    assert len(lineas) == 3, "cabecera y dos apuntes"
    assert "120.50" in enviado["contenido"], "importes con dos decimales"


@pytest.mark.asyncio
async def test_las_tildes_sobreviven_al_excel(db):
    """Sin BOM, Excel abre 'Reforma baño' como 'Reforma baÃ±o'."""
    crear_apunte(db, USUARIO, "Reforma baño 980", origen="bot")

    bot = BotFalso()
    await copias.enviar_copia(contexto_con(bot), USUARIO)

    assert "Reforma baño" in bot.enviados[0]["contenido"]


@pytest.mark.asyncio
async def test_sin_apuntes_no_se_manda_una_copia_vacia(db):
    bot = BotFalso()
    assert await copias.enviar_copia(contexto_con(bot), USUARIO) is False
    assert bot.enviados == []


@pytest.mark.asyncio
async def test_si_el_envio_falla_no_revienta(db):
    """Que uno haya bloqueado el bot no puede tumbar la copia de los demás."""
    crear_apunte(db, USUARIO, "Trabajo 100", origen="bot")

    assert await copias.enviar_copia(contexto_con(BotFalso(falla=True)), USUARIO) is False
