"""La conexión con el banco (Enable Banking): la prueba de que llega bien.

Enable Banking se sustituye: lo que se prueba es lo nuestro. Que se elija
el banco bueno, que se pida el permiso más largo que deja, que un pago se
lea como gasto y un ingreso como ingreso, y sobre todo que la página de
vuelta, que no lleva token, no se pueda usar dos veces ni con una clave
inventada para colgarle la cuenta a otro.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.bot import banco as bot_banco
from app.dominio.banco import elegir_banco, final_del_iban, hasta_del_permiso, leer_movimiento
from app.dominio.models import ConexionBanco
from app.main import crear_api
from app.nucleo import banco as enable
from app.servicios import banco as servicio
from tests.conftest import USUARIO
from tests.test_bot_mejoras import _contexto, _escribir

AHORA = datetime(2026, 11, 26, 10, 0, tzinfo=timezone.utc)
SANTANDER = {"name": "Banco Santander", "country": "ES", "maximum_consent_validity": 180 * 86400}
PAGO = {
    "transaction_amount": {"amount": "45.30", "currency": "EUR"},
    "credit_debit_indicator": "DBIT",
    "creditor": {"name": "REPSOL ESTACION 123"},
    "remittance_information": ["COMPRA TARJ. 5402XXXXXXXX1234 REPSOL"],
    "booking_date": "2026-11-24",
    "status": "BOOK",
}
NOMINA = {
    "transaction_amount": {"amount": "980.00", "currency": "EUR"},
    "credit_debit_indicator": "CRDT",
    "debtor": {"name": "ANA RUIZ"},
    "booking_date": "2026-11-20",
    "status": "BOOK",
}


class TestReglas:
    def test_elige_banco_santander_y_no_otro_con_ese_nombre(self):
        lista = [{"name": "Santander Consumer Finance"}, {"name": "Banco Santander"}, {"name": "BBVA"}]
        assert elegir_banco(lista, "Santander")["name"] == "Banco Santander"
        assert elegir_banco(lista, "ING") is None

    def test_pide_el_maximo_del_banco_menos_un_dia(self):
        assert hasta_del_permiso(AHORA, 180 * 86400) == AHORA + timedelta(days=179)
        assert hasta_del_permiso(AHORA, 400 * 86400) == AHORA + timedelta(days=179), "PSD2: 180 como mucho"
        assert hasta_del_permiso(AHORA, 86400) == AHORA + timedelta(days=1), "si solo deja uno, uno"
        assert hasta_del_permiso(AHORA, None) == AHORA + timedelta(days=1)

    def test_un_pago_con_tarjeta_es_un_gasto_con_el_nombre_de_la_tienda(self):
        m = leer_movimiento(PAGO)
        assert (m.importe, m.es_gasto, m.concepto) == (Decimal("45.30"), True, "REPSOL ESTACION 123")
        assert m.fecha.isoformat() == "2026-11-24" and not m.pendiente

    def test_un_ingreso_dice_quien_paga(self):
        m = leer_movimiento(NOMINA)
        assert (m.es_gasto, m.concepto) == (False, "ANA RUIZ")

    def test_sin_nombre_se_usa_el_texto_del_banco(self):
        sin_nombre = {**PAGO, "creditor": None}
        assert leer_movimiento(sin_nombre).concepto == "COMPRA TARJ. 5402XXXXXXXX1234 REPSOL"

    def test_un_importe_raro_no_se_cuela(self):
        assert leer_movimiento({"transaction_amount": {"amount": "abc"}}) is None

    def test_del_iban_solo_lo_ultimo(self):
        assert final_del_iban("ES12 0049 1234 5678 9012 3456") == "…3456"


class TestFirma:
    def test_cada_peticion_va_firmada_con_la_clave_y_su_id(self, monkeypatch):
        privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = privada.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode()
        monkeypatch.setattr(enable, "ENABLE_BANKING_APP_ID", "app-123")
        monkeypatch.setattr(enable, "ENABLE_BANKING_CLAVE", pem)

        token = enable._cabeceras()["Authorization"].split()[1]

        assert jwt.get_unverified_header(token)["kid"] == "app-123"
        datos = jwt.decode(token, privada.public_key(), algorithms=["RS256"], audience="api.enablebanking.com")
        assert datos["iss"] == "enablebanking.com" and datos["exp"] - datos["iat"] <= 3600

    def test_sin_configurar_lo_dice(self, monkeypatch):
        monkeypatch.setattr(enable, "ENABLE_BANKING_APP_ID", "")
        with pytest.raises(enable.BancoNoDisponible):
            enable._cabeceras()

    def test_una_clave_mal_pegada_lo_dice(self, monkeypatch):
        monkeypatch.setattr(enable, "ENABLE_BANKING_APP_ID", "app-123")
        monkeypatch.setattr(enable, "ENABLE_BANKING_CLAVE", "esto no es una clave")
        with pytest.raises(enable.BancoNoDisponible, match="BEGIN a END"):
            enable._cabeceras()


@pytest.fixture
def banco_falso(monkeypatch):
    """Enable Banking de mentira: Santander, una cuenta y dos movimientos."""
    pedidos = {}

    async def bancos(pais):
        return [{"name": "Santander Consumer Finance"}, SANTANDER]

    async def autorizar(nombre, pais, hasta, estado, vuelta):
        pedidos.update(nombre=nombre, hasta=hasta, estado=estado, vuelta=vuelta)
        return f"https://banco.example/auth?state={estado}"

    async def crear_sesion(codigo):
        pedidos["codigo"] = codigo
        return {
            "session_id": "ses-1",
            "access": {"valid_until": "2027-05-24T10:00:00+00:00"},
            "accounts": [
                {"uid": "cta-1", "name": "Cuenta casa", "cash_account_type": "CACC",
                 "account_id": {"iban": "ES1200491234567890123456"}},
            ],
        }

    async def movimientos(uid, desde):
        return [PAGO, NOMINA]

    for nombre, funcion in (("bancos", bancos), ("autorizar", autorizar), ("crear_sesion", crear_sesion), ("movimientos", movimientos)):
        monkeypatch.setattr(enable, nombre, funcion)
    monkeypatch.setattr(servicio, "URL_API", "https://api.example")
    return pedidos


@pytest.fixture
def cliente():
    with TestClient(crear_api()) as c:
        yield c


class TestConectar:
    @pytest.mark.asyncio
    async def test_iniciar_pide_el_permiso_largo_y_vuelve_a_la_api(self, db, banco_falso):
        url = await servicio.iniciar(db, USUARIO)

        assert url.startswith("https://banco.example/auth")
        assert banco_falso["nombre"] == "Banco Santander"
        assert banco_falso["vuelta"] == "https://api.example/banco/vuelta"
        assert (banco_falso["hasta"] - datetime.now(timezone.utc)).days >= 178
        conexion = db.query(ConexionBanco).one()
        assert conexion.estado == "pendiente" and conexion.clave_vuelta == banco_falso["estado"]

    @pytest.mark.asyncio
    async def test_la_vuelta_conecta_y_enseña_lo_que_ve(self, db, banco_falso, cliente):
        await servicio.iniciar(db, USUARIO)

        r = cliente.get(f"/banco/vuelta?state={banco_falso['estado']}&code=cod-1")

        assert r.status_code == 200
        assert "Cuenta conectada" in r.text and "…3456" in r.text
        assert "ES1200491234567890123456" not in r.text, "el IBAN no se enseña entero"
        assert "REPSOL ESTACION 123" in r.text and "45,30 €" in r.text
        db.expire_all()
        conexion = db.query(ConexionBanco).one()
        assert conexion.estado == "activa" and conexion.sesion == "ses-1"
        assert conexion.clave_vuelta is None

    @pytest.mark.asyncio
    async def test_la_vuelta_no_vale_dos_veces(self, db, banco_falso, cliente):
        await servicio.iniciar(db, USUARIO)
        estado = banco_falso["estado"]
        cliente.get(f"/banco/vuelta?state={estado}&code=cod-1")

        r = cliente.get(f"/banco/vuelta?state={estado}&code=cod-2")

        assert r.status_code == 400 and "ya no vale" in r.text

    def test_una_clave_inventada_no_conecta_nada(self, db, banco_falso, cliente):
        r = cliente.get("/banco/vuelta?state=inventada&code=cod-1")
        assert r.status_code == 400
        assert "codigo" not in banco_falso, "ni se llega a pedir la sesión"

    @pytest.mark.asyncio
    async def test_un_enlace_viejo_ha_caducado(self, db, banco_falso, cliente):
        await servicio.iniciar(db, USUARIO)
        conexion = db.query(ConexionBanco).one()
        conexion.creado = datetime.now(timezone.utc) - timedelta(hours=2)
        db.commit()

        r = cliente.get(f"/banco/vuelta?state={banco_falso['estado']}&code=cod-1")

        assert r.status_code == 400 and "caducado" in r.text

    def test_si_el_banco_dice_que_no(self, cliente):
        r = cliente.get("/banco/vuelta?error=access_denied&error_description=Cancelado por el usuario")
        assert r.status_code == 400 and "Cancelado por el usuario" in r.text

    @pytest.mark.asyncio
    async def test_conectar_otra_vez_sustituye_la_anterior(self, db, banco_falso):
        await servicio.iniciar(db, USUARIO)
        await servicio.completar(db, banco_falso["estado"], "cod-1")
        await servicio.iniciar(db, USUARIO)
        await servicio.completar(db, banco_falso["estado"], "cod-2")

        estados = sorted(c.estado for c in db.query(ConexionBanco))
        assert estados == ["activa", "sustituida"]


class TestPorElBot:
    @pytest.mark.asyncio
    async def test_sin_conexion_da_el_boton(self, db, banco_falso):
        update, mensaje = _escribir("/banco")
        await bot_banco.banco(update, _contexto({}))

        texto, botones = mensaje.respuestas[0]
        assert "confirma en la app de tu banco" in texto
        assert botones.inline_keyboard[0][0].url.startswith("https://banco.example/auth")

    @pytest.mark.asyncio
    async def test_con_conexion_enseña_lo_que_llega(self, db, banco_falso):
        await servicio.iniciar(db, USUARIO)
        await servicio.completar(db, banco_falso["estado"], "cod-1")

        update, mensaje = _escribir("/banco")
        await bot_banco.banco(update, _contexto({}))

        texto = mensaje.respuestas[0][0]
        assert "Conectado con Banco Santander" in texto
        assert "Cuenta casa" in texto and "…3456" in texto
        assert "REPSOL ESTACION 123 −45,30 €" in texto

    @pytest.mark.asyncio
    async def test_sin_configurar_lo_explica(self, db, monkeypatch):
        async def sin_clave(pais):
            raise enable.BancoNoDisponible("faltan ENABLE_BANKING_APP_ID y ENABLE_BANKING_CLAVE en el entorno")

        monkeypatch.setattr(enable, "bancos", sin_clave)
        monkeypatch.setattr(servicio, "URL_API", "https://api.example")
        update, mensaje = _escribir("/banco")
        await bot_banco.banco(update, _contexto({}))
        assert "ENABLE_BANKING_APP_ID" in mensaje.respuestas[0][0]
