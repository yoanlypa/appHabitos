"""Las notas de voz: transcribir, anotar y no perder nunca lo dictado.

Lo que se prueba aquí es lo que puede romperse en silencio: que una nota
sin importe no se descarte, que al guardarse como nota no se cuele en las
cuentas del mes, y que cuando el transcriptor falle el bot lo diga en vez
de tragárselo.
"""
from decimal import Decimal

import pytest

from app.bot import handlers
from app.dominio.models import Apunte
from app.nucleo import transcripcion
from app.servicios import voz
from app.servicios.clientes import crear_cliente
from app.servicios.resumen import resumen_dia
from tests.conftest import USUARIO


class RespuestaFalsa:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


def transcriptor_falso(monkeypatch, respuesta):
    """Sustituye la llamada HTTP y guarda con qué se llamó."""
    llamadas = []

    class ClienteFalso:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, data=None, files=None):
            llamadas.append({"url": url, "headers": headers, "data": data, "files": files})
            return respuesta

    monkeypatch.setattr(transcripcion.httpx, "AsyncClient", ClienteFalso)
    monkeypatch.setattr(transcripcion, "OPENAI_API_KEY", "clave-de-mentira")
    return llamadas


class TestTranscribir:
    @pytest.mark.asyncio
    async def test_devuelve_el_texto_sin_espacios(self, monkeypatch):
        transcriptor_falso(monkeypatch, RespuestaFalsa(200, "  Cambio de grifo Ana 120 euros.\n"))
        assert await transcripcion.transcribir(b"audio") == "Cambio de grifo Ana 120 euros."

    @pytest.mark.asyncio
    async def test_manda_modelo_idioma_y_extension(self, monkeypatch):
        """La extensión importa: el servicio deduce el formato del nombre."""
        llamadas = transcriptor_falso(monkeypatch, RespuestaFalsa(200, "hola"))
        monkeypatch.setattr(transcripcion, "MODELO_TRANSCRIPCION", "modelo-x")
        monkeypatch.setattr(transcripcion, "IDIOMA_VOZ", "es")

        await transcripcion.transcribir(b"audio", "nota.ogg")

        enviado = llamadas[0]
        assert enviado["data"]["model"] == "modelo-x"
        assert enviado["data"]["language"] == "es"
        assert enviado["files"]["file"][0] == "nota.ogg"
        assert enviado["headers"]["Authorization"].startswith("Bearer ")

    @pytest.mark.asyncio
    async def test_sin_clave_lo_dice_claro(self, monkeypatch):
        monkeypatch.setattr(transcripcion, "OPENAI_API_KEY", "")
        with pytest.raises(transcripcion.TranscripcionNoDisponible):
            await transcripcion.transcribir(b"audio")

    @pytest.mark.asyncio
    async def test_un_error_del_servicio_cuenta_el_motivo(self, monkeypatch):
        """Sin el cuerpo de la respuesta no hay forma de saber qué arreglar."""
        transcriptor_falso(monkeypatch, RespuestaFalsa(429, "insufficient_quota"))
        with pytest.raises(transcripcion.ErrorDeTranscripcion) as exc:
            await transcripcion.transcribir(b"audio")
        assert "insufficient_quota" in str(exc.value)

    @pytest.mark.asyncio
    async def test_un_audio_enorme_no_se_llega_a_mandar(self, monkeypatch):
        llamadas = transcriptor_falso(monkeypatch, RespuestaFalsa(200, "hola"))
        with pytest.raises(transcripcion.ErrorDeTranscripcion):
            await transcripcion.transcribir(b"x" * (transcripcion.TAMANO_MAXIMO + 1))
        assert llamadas == [], "ni se intenta: se pagaría por nada"


def oir(monkeypatch, texto):
    async def falso(audio, nombre="nota.ogg"):
        return texto

    monkeypatch.setattr(voz, "transcribir", falso)


class TestAnotarAudio:
    @pytest.mark.asyncio
    async def test_lo_dictado_se_anota_como_lo_escrito(self, db, monkeypatch):
        oir(monkeypatch, "Cambio de grifo Ana 120 euros")

        escuchada = await voz.anotar_audio(db, USUARIO, b"audio", "nota.ogg", origen="bot")

        assert escuchada.texto == "Cambio de grifo Ana 120 euros"
        assert escuchada.apunte.tipo == "trabajo"
        assert escuchada.apunte.importe == Decimal("120")

    @pytest.mark.asyncio
    async def test_sin_importe_se_guarda_como_nota(self, db, monkeypatch):
        """Quien escribe puede corregir; quien habla ya lo ha dicho."""
        oir(monkeypatch, "Llamar al fontanero el martes")

        escuchada = await voz.anotar_audio(db, USUARIO, b"audio", "nota.ogg", origen="bot")

        assert escuchada.apunte.tipo == "nota"
        assert escuchada.apunte.importe == Decimal("0")
        assert escuchada.apunte.concepto == "Llamar al fontanero el martes"

    @pytest.mark.asyncio
    async def test_una_nota_no_mueve_las_cuentas(self, db, monkeypatch):
        """Si una nota contara como cobrado, el mes cuadraría mal y en silencio."""
        oir(monkeypatch, "Llamar al fontanero el martes")
        await voz.anotar_audio(db, USUARIO, b"audio", "nota.ogg", origen="bot")

        r = resumen_dia(db, USUARIO)
        assert (r.cobrado, r.pendiente, r.gastos, r.neto) == (
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
        )

    @pytest.mark.asyncio
    async def test_la_nota_tambien_se_cuelga_del_cliente(self, db, monkeypatch):
        cliente = crear_cliente(db, USUARIO, "Ana Ruiz")
        oir(monkeypatch, "Pasar a ver la caldera de Ana Ruiz")

        escuchada = await voz.anotar_audio(db, USUARIO, b"audio", "nota.ogg", origen="bot")

        assert escuchada.apunte.cliente_id == cliente.id

    @pytest.mark.asyncio
    async def test_un_audio_mudo_no_crea_nada(self, db, monkeypatch):
        oir(monkeypatch, "   ")

        with pytest.raises(voz.NadaQueAnotar):
            await voz.anotar_audio(db, USUARIO, b"audio", "nota.ogg", origen="bot")
        assert db.query(Apunte).count() == 0


class AudioFalso:
    file_id = "id-de-mentira"
    file_size = 4096
    mime_type = "audio/ogg"


class FicheroFalso:
    async def download_as_bytearray(self):
        return bytearray(b"OggS-lo-que-sea")


class ChatFalso:
    def __init__(self):
        self.acciones = []

    async def send_action(self, accion):
        self.acciones.append(accion)


class MensajeFalso:
    def __init__(self, audio):
        self.voice = audio
        self.audio = None
        self.chat = ChatFalso()
        self.respuestas = []

    async def reply_text(self, texto, reply_markup=None):
        self.respuestas.append(texto)


def update_falso(audio=None):
    mensaje = MensajeFalso(audio if audio is not None else AudioFalso())
    return type(
        "U",
        (),
        {"message": mensaje, "effective_user": type("Usr", (), {"id": USUARIO})()},
    )()


def contexto_falso():
    class BotFalso:
        async def get_file(self, file_id):
            return FicheroFalso()

    return type("C", (), {"bot": BotFalso()})()


class TestHandlerDeVoz:
    @pytest.mark.asyncio
    async def test_contesta_lo_que_ha_oido_y_lo_anotado(self, db, monkeypatch):
        oir(monkeypatch, "Cambio de grifo 120 euros")
        update = update_falso()

        await handlers.nota_de_voz(update, contexto_falso())

        respuesta = update.message.respuestas[0]
        assert "Cambio de grifo 120 euros" in respuesta, "hay que poder ver si oyó mal"
        assert "120,00 €" in respuesta
        assert db.query(Apunte).count() == 1

    @pytest.mark.asyncio
    async def test_sin_clave_lo_dice_y_no_se_calla(self, db, monkeypatch):
        async def sin_clave(audio, nombre="nota.ogg"):
            raise transcripcion.TranscripcionNoDisponible("falta OPENAI_API_KEY")

        monkeypatch.setattr(voz, "transcribir", sin_clave)
        update = update_falso()

        await handlers.nota_de_voz(update, contexto_falso())

        assert "OPENAI_API_KEY" in update.message.respuestas[0]
        assert db.query(Apunte).count() == 0

    @pytest.mark.asyncio
    async def test_un_audio_larguisimo_ni_se_descarga(self, db, monkeypatch):
        grande = type(
            "Grande",
            (),
            {
                "file_id": "x",
                "file_size": transcripcion.TAMANO_MAXIMO + 1,
                "mime_type": "audio/ogg",
            },
        )()
        update = update_falso(grande)

        await handlers.nota_de_voz(update, contexto_falso())

        assert "larga" in update.message.respuestas[0]
        assert db.query(Apunte).count() == 0
