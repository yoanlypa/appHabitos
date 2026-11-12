"""El recordatorio de una cita el mismo día, por Telegram y por correo.

Lo que se rompería en silencio: que no avise (el fallo que lo motivó, una
cita a las 14:00 sin aviso ese día), que avise cada minuto, que avise tarde,
que no vuelva a avisar al mover la cita, o que un correo que falla tire el
aviso de Telegram.
"""
from datetime import date, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient

from app.bot import citas as bot_citas
from app.bot import formato
from app.dominio.models import Cita
from app.dominio.recordatorios import toca_avisar
from app.main import crear_api
from app.nucleo import correo as nucleo_correo
from app.servicios import avisos
from app.servicios.agenda import actualizar_cita, crear_cita
from app.servicios.auth import generar_token
from tests.conftest import USUARIO

HOY = date(2026, 11, 12)
UNA_HORA = timedelta(hours=1)
OCHO = time(8, 0)


def _a_las(h, m=0, dia=HOY):
    return datetime.combine(dia, time(h, m))


# ---------- La regla ----------


@pytest.mark.parametrize(
    "ahora,toca",
    [
        (_a_las(12, 59), False),  # antes de la hora de antelación
        (_a_las(13, 0), True),
        (_a_las(13, 45), True),  # el bot estaba caído a la una: todavía sirve
        (_a_las(14, 0), False),  # ya empezó: un aviso tarde es ruido
        (_a_las(13, 30, HOY - timedelta(days=1)), False),  # otro día
    ],
)
def test_con_hora_se_avisa_desde_una_hora_antes_hasta_la_hora(ahora, toca):
    assert toca_avisar(ahora, HOY, time(14, 0), False, None, UNA_HORA, OCHO) is toca


def test_sin_hora_a_primera_hora_y_media_hora_de_margen():
    assert toca_avisar(_a_las(8, 0), HOY, None, False, None, UNA_HORA, OCHO)
    assert toca_avisar(_a_las(8, 29), HOY, None, False, None, UNA_HORA, OCHO)
    assert not toca_avisar(_a_las(8, 30), HOY, None, False, None, UNA_HORA, OCHO)
    assert not toca_avisar(_a_las(7, 59), HOY, None, False, None, UNA_HORA, OCHO)


def test_ni_hecha_ni_avisada_ya():
    assert not toca_avisar(_a_las(13, 30), HOY, time(14), True, None, UNA_HORA, OCHO)
    assert not toca_avisar(_a_las(13, 30), HOY, time(14), False, HOY, UNA_HORA, OCHO)
    # Avisada para otro día (se movió): vuelve a tocar.
    assert toca_avisar(_a_las(13, 30), HOY, time(14), False, HOY - timedelta(days=3), UNA_HORA, OCHO)


# ---------- Con la base ----------


def test_citas_por_recordar_una_vez_y_solo_a_quien_no_los_apago(db):
    a_las_14 = crear_cita(db, USUARIO, HOY, "Medir cocina", hora=time(14, 0))
    crear_cita(db, USUARIO, HOY, "A las 18", hora=time(18, 0))  # aún no
    crear_cita(db, USUARIO, HOY + timedelta(days=1), "Mañana", hora=time(14, 0))
    hecha = crear_cita(db, USUARIO, HOY, "Ya hecha", hora=time(14, 0))
    hecha.hecha = True
    de_otro = crear_cita(db, 111, HOY, "De otro", hora=time(14, 0))
    avisos.activar_avisos(db, 111, False)

    debidas = avisos.citas_por_recordar(db, _a_las(13, 10))
    assert [c.id for c in debidas] == [a_las_14.id]
    assert de_otro not in debidas

    avisos.marcar_avisada(db, a_las_14)
    assert avisos.citas_por_recordar(db, _a_las(13, 11)) == []  # no cada minuto


def test_moverla_de_hora_vuelve_a_avisar(db):
    cita = crear_cita(db, USUARIO, HOY, "Presupuesto", hora=time(14, 0))
    avisos.marcar_avisada(db, cita)
    actualizar_cita(db, USUARIO, cita.id, titulo="Presupuesto baño")  # el texto no cuenta
    assert cita.avisada_el == HOY
    actualizar_cita(db, USUARIO, cita.id, hora=time(17, 0))
    assert cita.avisada_el is None
    assert avisos.citas_por_recordar(db, _a_las(16, 30)) == [cita]


def test_el_primer_dia_de_una_cita_de_varios(db):
    crear_cita(db, USUARIO, HOY - timedelta(days=1), "Reforma", fecha_fin=HOY + timedelta(days=1))
    assert avisos.citas_por_recordar(db, _a_las(8, 5)) == []


# ---------- El correo ----------


def test_guardar_correo_lo_limpia_y_rechaza_lo_que_no_es(db):
    assert avisos.guardar_correo(db, USUARIO, "  Nombre@Ejemplo.COM ") == "nombre@ejemplo.com"
    with pytest.raises(avisos.CorreoNoValido):
        avisos.guardar_correo(db, USUARIO, "esto no es un correo")
    assert avisos.correo_de(db, USUARIO) == "nombre@ejemplo.com"
    assert avisos.guardar_correo(db, USUARIO, "") is None
    # Guardar el correo no apaga los avisos de nadie.
    assert avisos.avisos_activos(db, USUARIO)


class _BotFalso:
    def __init__(self, falla=False):
        self.mandados, self.falla = [], falla

    async def send_message(self, chat_id, text, **_):
        from telegram.error import TelegramError

        if self.falla:
            raise TelegramError("bloqueado")
        self.mandados.append((chat_id, text))


class _Contexto:
    def __init__(self, bot):
        self.bot = bot


@pytest.fixture
def correos(monkeypatch):
    enviados = []

    async def enviar(para, asunto, texto):
        enviados.append((para, asunto, texto))

    monkeypatch.setattr(nucleo_correo, "RESEND_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(nucleo_correo, "enviar_correo", enviar)
    return enviados


@pytest.mark.asyncio
async def test_avisa_por_telegram_y_por_correo_y_no_repite(db, monkeypatch, correos):
    cita = crear_cita(db, USUARIO, HOY, "Medir cocina", hora=time(14, 0), direccion="C/ Mayor 12")
    avisos.guardar_correo(db, USUARIO, "nombre@ejemplo.com")
    monkeypatch.setattr(bot_citas, "ahora_local", lambda: _a_las(13, 5))
    bot = _BotFalso()

    await bot_citas.recordar(_Contexto(bot))
    assert bot.mandados == [(USUARIO, "⏰ Hoy a las 14:00: Medir cocina\nEn C/ Mayor 12")]
    assert correos == [("nombre@ejemplo.com", "Hoy 14:00 · Medir cocina", bot.mandados[0][1])]

    await bot_citas.recordar(_Contexto(bot))
    assert len(bot.mandados) == 1 and len(correos) == 1
    db.refresh(cita)
    assert cita.avisada_el == HOY


@pytest.mark.asyncio
async def test_si_telegram_falla_el_correo_sale_igual(db, monkeypatch, correos):
    crear_cita(db, USUARIO, HOY, "Medir cocina", hora=time(14, 0))
    avisos.guardar_correo(db, USUARIO, "nombre@ejemplo.com")
    monkeypatch.setattr(bot_citas, "ahora_local", lambda: _a_las(13, 5))
    await bot_citas.recordar(_Contexto(_BotFalso(falla=True)))
    assert len(correos) == 1


@pytest.mark.asyncio
async def test_si_el_correo_falla_telegram_sale_igual(db, monkeypatch):
    async def falla(*_):
        raise nucleo_correo.ErrorDeCorreo("403: solo a la dirección de la cuenta")

    monkeypatch.setattr(nucleo_correo, "RESEND_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(nucleo_correo, "enviar_correo", falla)
    crear_cita(db, USUARIO, HOY, "Medir cocina", hora=time(14, 0))
    avisos.guardar_correo(db, USUARIO, "nombre@ejemplo.com")
    monkeypatch.setattr(bot_citas, "ahora_local", lambda: _a_las(13, 5))
    bot = _BotFalso()
    await bot_citas.recordar(_Contexto(bot))
    assert len(bot.mandados) == 1


@pytest.mark.asyncio
async def test_sin_correo_puesto_o_sin_clave_no_se_intenta(db, monkeypatch, correos):
    crear_cita(db, USUARIO, HOY, "Medir cocina", hora=time(14, 0))
    monkeypatch.setattr(bot_citas, "ahora_local", lambda: _a_las(13, 5))
    await bot_citas.recordar(_Contexto(_BotFalso()))
    assert correos == []


def test_el_texto_lleva_cliente_y_telefono(db):
    from app.servicios.clientes import crear_cliente

    ana = crear_cliente(db, USUARIO, "Ana Ruiz", telefono="600 111 222")
    cita = crear_cita(db, USUARIO, HOY, "Medir cocina", cliente_id=ana.id)
    assert formato.recordatorio_cita(cita) == "⏰ Hoy: Medir cocina\nCon Ana Ruiz (600 111 222)"
    assert formato.asunto_recordatorio_cita(cita) == "Hoy Medir cocina"


# ---------- Por la web ----------


def test_ajustes_por_http(db, monkeypatch, correos):
    cab = {"Authorization": f"Bearer {generar_token(db, USUARIO)}"}
    with TestClient(crear_api()) as c:
        assert c.get("/ajustes").status_code == 401
        assert c.get("/ajustes", headers=cab).json() == {
            "avisos_activos": True, "correo": None, "correo_disponible": True,
            "aviso_cita_minutos": 120}
        assert c.post("/ajustes/correo/prueba", headers=cab).status_code == 422  # sin correo
        assert c.patch("/ajustes", headers=cab, json={"correo": "mal"}).status_code == 422
        r = c.patch("/ajustes", headers=cab, json={"correo": "Nombre@Ejemplo.com"})
        assert r.json()["correo"] == "nombre@ejemplo.com"
        assert c.post("/ajustes/correo/prueba", headers=cab).json() == {"enviado_a": "nombre@ejemplo.com"}
        assert correos[0][0] == "nombre@ejemplo.com"
        # Un PATCH sin el campo no lo borra; con null sí.
        assert c.patch("/ajustes", headers=cab, json={}).json()["correo"] == "nombre@ejemplo.com"
        assert c.patch("/ajustes", headers=cab, json={"correo": None}).json()["correo"] is None


def test_sin_clave_la_prueba_dice_que_falta(db, monkeypatch):
    monkeypatch.setattr(nucleo_correo, "RESEND_API_KEY", "")
    cab = {"Authorization": f"Bearer {generar_token(db, USUARIO)}"}
    avisos.guardar_correo(db, USUARIO, "nombre@ejemplo.com")
    with TestClient(crear_api()) as c:
        r = c.post("/ajustes/correo/prueba", headers=cab)
        assert r.status_code == 503 and "RESEND_API_KEY" in r.json()["detail"]
        assert c.get("/ajustes", headers=cab).json()["correo_disponible"] is False
