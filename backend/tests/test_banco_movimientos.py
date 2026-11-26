"""Los pagos nuevos de la cuenta: se lee cada poco y se pregunta por cada uno.

Lo que se notaría tarde: preguntar dos veces por el mismo pago (o apuntarlo
dos veces), preguntar al conectar por un mes entero, apuntar algo sin que
se haya dicho de qué es, que un gasto de Casa acabe en las cuentas del
negocio, o que se pierda un pago porque Telegram falló al preguntar.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.bot import banco as bot_banco
from app.dominio.banco import concepto_de_banco, referencia_de
from app.dominio.models import Apunte, ConexionBanco, GastoCasa, MovimientoLeido
from app.nucleo import banco as enable
from app.nucleo.tiempo import hoy_local
from app.servicios import banco as servicio
from app.servicios import casa
from app.servicios.apuntes import crear_apunte, crear_movimiento
from app.servicios.resumen import resumen_mes
from tests.conftest import USUARIO

HOY = hoy_local()
AYER = HOY - timedelta(days=1)
OTRO = 111222333


def mov(ref, importe, texto, dia=AYER, sentido="DBIT", estado="BOOK"):
    return {
        "entry_reference": ref,
        "transaction_amount": {"amount": importe, "currency": "EUR"},
        "credit_debit_indicator": sentido,
        "status": estado,
        "booking_date": dia.isoformat(),
        "value_date": dia.isoformat(),
        "remittance_information": [texto],
    }


@pytest.fixture
def cuenta(monkeypatch):
    """La cuenta del banco de mentira: una lista a la que se añaden movimientos."""
    lista = []
    llamadas = []

    async def movimientos(uid, desde):
        llamadas.append(desde)
        return list(lista)

    monkeypatch.setattr(enable, "movimientos", movimientos)
    return type("Cuenta", (), {"movs": lista, "llamadas": llamadas})()


@pytest.fixture
def conexion(db):
    c = ConexionBanco(
        user_id=USUARIO,
        banco="Banco Santander",
        estado="activa",
        sesion="ses-1",
        valido_hasta=datetime.now(timezone.utc) + timedelta(days=170),
        cuentas='[{"uid": "cta-1", "nombre": "Cuenta", "tipo": "CACC", "final_iban": "…8286"}]',
    )
    db.add(c)
    db.commit()
    return c


async def con_un_pago_nuevo(db, conexion, cuenta, *movimientos):
    """Conecta (primera lectura, que no pregunta) y luego llega lo nuevo."""
    await servicio.leer_nuevos(db, conexion)
    cuenta.movs.extend(movimientos)
    return await servicio.leer_nuevos(db, conexion)


class TestConceptoDelBanco:
    @pytest.mark.parametrize(
        "texto, concepto",
        [
            ("COMPRA EN MERCADONA, CON LA TARJETA : 5489XXXXXXXX1234 EL 2026-11-24", "Mercadona"),
            ("Pago Movil En Repsol Estacion 123, Madrid, Tarj. :*123456", "Repsol Estacion 123, Madrid"),
            ("Compra Internet En Amazon.es, Tarj. :*123456", "Amazon.es"),
            ("COMPRA TARJ. 5402XXXXXXXX1234 REPSOL", "Repsol"),
            ("Transferencia De Ana Ruiz, Concepto Reforma Baño.", "Ana Ruiz · Reforma Baño"),
            ("Recibo Endesa Energia Nº Recibo 0049123456", "Endesa Energia"),
            ("LEROY MERLIN ALCOBENDAS", "Leroy Merlin Alcobendas"),
        ],
    )
    def test_queda_la_tienda_o_la_persona(self, texto, concepto):
        assert concepto_de_banco(texto) == concepto

    def test_si_no_queda_nada_no_se_inventa(self):
        assert concepto_de_banco("5489XXXXXXXX1234") == "5489XXXXXXXX1234"

    def test_sin_referencia_se_usa_una_huella_que_no_cambia(self):
        sin = mov(None, "45.30", "COMPRA EN REPSOL")
        assert referencia_de(sin) == referencia_de(dict(sin)) and referencia_de(sin).startswith("h:")


class TestLeer:
    @pytest.mark.asyncio
    async def test_al_conectar_no_pregunta_por_lo_que_ya_habia(self, db, conexion, cuenta):
        cuenta.movs.extend([mov("r1", "45.30", "COMPRA EN REPSOL"), mov("r2", "62.10", "COMPRA EN MERCADONA")])

        nuevos = await servicio.leer_nuevos(db, conexion)

        assert nuevos == [] and servicio.por_preguntar(db) == []
        assert {m.estado for m in db.query(MovimientoLeido)} == {"antiguo"}
        assert cuenta.llamadas[0] == HOY - timedelta(days=30)

    @pytest.mark.asyncio
    async def test_lo_nuevo_se_pregunta_una_sola_vez(self, db, conexion, cuenta):
        nuevos = await con_un_pago_nuevo(db, conexion, cuenta, mov("r9", "45.30", "COMPRA EN REPSOL"))
        assert [m.concepto for m in nuevos] == ["Repsol"]

        otra_vez = await servicio.leer_nuevos(db, conexion)

        assert otra_vez == [] and db.query(MovimientoLeido).count() == 1
        assert cuenta.llamadas[-1] == HOY - timedelta(days=7), "después, una semana de solape"

    @pytest.mark.asyncio
    async def test_lo_pendiente_espera_a_estar_cargado(self, db, conexion, cuenta):
        await con_un_pago_nuevo(db, conexion, cuenta, mov("p1", "45.30", "COMPRA EN REPSOL", estado="PDNG"))
        assert db.query(MovimientoLeido).count() == 0

    @pytest.mark.asyncio
    async def test_con_el_permiso_caducado_ni_se_llama_al_banco(self, db, conexion, cuenta):
        conexion.valido_hasta = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
        assert await servicio.leer_nuevos(db, conexion) == [] and cuenta.llamadas == []


class TestDecidir:
    @pytest.mark.asyncio
    async def test_casa_lo_apunta_en_casa_con_tarjeta_y_no_toca_el_negocio(self, db, conexion, cuenta):
        (m,) = await con_un_pago_nuevo(db, conexion, cuenta, mov("r1", "62.10", "COMPRA EN MERCADONA"))

        d = servicio.decidir(db, USUARIO, m.id, "casa")

        gasto = db.query(GastoCasa).one()
        assert (gasto.concepto, gasto.importe, gasto.efectivo, gasto.origen) == ("Mercadona", Decimal("62.10"), False, "banco")
        assert gasto.categoria == "Súper" and gasto.fecha == AYER
        assert d.gasto.id == gasto.id and m.estado == "casa"
        assert db.query(Apunte).count() == 0
        assert resumen_mes(db, USUARIO, HOY.year, HOY.month).gastos == 0, "el súper no es del negocio"

    @pytest.mark.asyncio
    async def test_negocio_lo_apunta_como_gasto_del_negocio(self, db, conexion, cuenta):
        (m,) = await con_un_pago_nuevo(db, conexion, cuenta, mov("r1", "120.00", "COMPRA EN LEROY MERLIN"))

        d = servicio.decidir(db, USUARIO, m.id, "negocio")

        assert (d.apunte.tipo, d.apunte.concepto, d.apunte.importe, d.apunte.origen) == ("gasto", "Leroy Merlin", Decimal("120.00"), "banco")
        assert db.query(GastoCasa).count() == 0

    @pytest.mark.asyncio
    async def test_un_ingreso_puede_ser_el_cobro_de_un_trabajo_pendiente(self, db, conexion, cuenta):
        pendiente = crear_apunte(db, USUARIO, "pendiente Reforma baño Ana 980", origen="bot")
        (m,) = await con_un_pago_nuevo(
            db, conexion, cuenta, mov("r1", "980.00", "Transferencia De Ana Ruiz, Concepto Reforma", sentido="CRDT")
        )

        pregunta = servicio.pregunta_de(db, m)
        assert [a.id for a in pregunta.cobros] == [pendiente.id]

        servicio.decidir(db, USUARIO, m.id, "cobro", pendiente.id)

        db.refresh(pendiente)
        assert pendiente.pendiente is False
        assert db.query(Apunte).count() == 1, "no se crea otro cobro: es el mismo"

    @pytest.mark.asyncio
    async def test_dos_toques_no_apuntan_dos_veces(self, db, conexion, cuenta):
        (m,) = await con_un_pago_nuevo(db, conexion, cuenta, mov("r1", "62.10", "COMPRA EN MERCADONA"))
        servicio.decidir(db, USUARIO, m.id, "casa")

        d = servicio.decidir(db, USUARIO, m.id, "negocio")

        assert d.ya_decidido and d.gasto is not None
        assert db.query(GastoCasa).count() == 1 and db.query(Apunte).count() == 0

    @pytest.mark.asyncio
    async def test_lo_de_otro_no_se_toca(self, db, conexion, cuenta):
        (m,) = await con_un_pago_nuevo(db, conexion, cuenta, mov("r1", "62.10", "COMPRA EN MERCADONA"))
        with pytest.raises(servicio.MovimientoNoEncontrado):
            servicio.decidir(db, OTRO, m.id, "casa")

    @pytest.mark.asyncio
    async def test_el_ticket_ya_escaneado_se_reconoce(self, db, conexion, cuenta):
        crear_movimiento(db, USUARIO, "gasto", "Repsol gasoil", Decimal("45.30"), HOY - timedelta(days=3), False, "bot")
        (m,) = await con_un_pago_nuevo(db, conexion, cuenta, mov("r1", "45.30", "COMPRA EN REPSOL"))

        pregunta = servicio.pregunta_de(db, m)

        assert pregunta.parecido and "Repsol gasoil" in pregunta.parecido

    @pytest.mark.asyncio
    async def test_lo_apuntado_en_casa_tambien_se_reconoce(self, db, conexion, cuenta):
        casa.crear_gasto(db, USUARIO, "Súper", Decimal("62.10"), fecha=AYER)
        (m,) = await con_un_pago_nuevo(db, conexion, cuenta, mov("r1", "62.10", "COMPRA EN MERCADONA"))
        assert "en Casa" in servicio.pregunta_de(db, m).parecido


class TestCaducidad:
    def test_se_avisa_una_vez_una_semana_antes(self, db, conexion):
        conexion.valido_hasta = datetime.now(timezone.utc) + timedelta(days=5)
        db.commit()
        assert [c.id for c in servicio.avisar_de_caducidad(db)] == [conexion.id]
        assert servicio.avisar_de_caducidad(db) == []

    def test_lejos_de_caducar_no_se_avisa(self, db, conexion):
        assert servicio.avisar_de_caducidad(db) == []


# --- Por el bot -----------------------------------------------------------------


class _Bot:
    def __init__(self, falla=False):
        self.enviados = []
        self.falla = falla

    async def send_message(self, chat_id, text, reply_markup=None):
        if self.falla:
            from telegram.error import NetworkError

            raise NetworkError("sin red")
        self.enviados.append((chat_id, text, reply_markup))


class _Consulta:
    def __init__(self, data, user_id=USUARIO):
        self.data = data
        self.from_user = type("U", (), {"id": user_id})()
        self.message = None
        self.texto = self.botones = None

    async def answer(self):
        pass

    async def edit_message_text(self, texto, reply_markup=None):
        self.texto, self.botones = texto, reply_markup


def _datos(botones):
    return [b.callback_data for fila in botones.inline_keyboard for b in fila]


class TestPorElBot:
    @pytest.mark.asyncio
    async def test_pregunta_con_casa_primero(self, db, conexion, cuenta):
        await con_un_pago_nuevo(db, conexion, cuenta, mov("r1", "62.10", "COMPRA EN MERCADONA"))
        bot = _Bot()

        assert await bot_banco.preguntar(bot, db) == 1

        chat, texto, botones = bot.enviados[0]
        m = db.query(MovimientoLeido).one()
        assert chat == USUARIO and "−62,10 € · Mercadona" in texto
        assert _datos(botones) == [f"bk:casa:{m.id}", f"bk:neg:{m.id}", f"bk:ign:{m.id}"]
        assert m.estado == "preguntado"
        assert await bot_banco.preguntar(bot, db) == 0, "no se pregunta dos veces"

    @pytest.mark.asyncio
    async def test_si_telegram_falla_se_vuelve_a_intentar(self, db, conexion, cuenta):
        await con_un_pago_nuevo(db, conexion, cuenta, mov("r1", "62.10", "COMPRA EN MERCADONA"))

        assert await bot_banco.preguntar(_Bot(falla=True), db) == 0

        assert db.query(MovimientoLeido).one().estado == "nuevo"
        assert await bot_banco.preguntar(_Bot(), db) == 1

    @pytest.mark.asyncio
    async def test_tocar_casa_lo_apunta_y_enseña_sus_botones(self, db, conexion, cuenta):
        await con_un_pago_nuevo(db, conexion, cuenta, mov("r1", "62.10", "COMPRA EN MERCADONA"))
        m = db.query(MovimientoLeido).one()
        consulta = _Consulta(f"bk:casa:{m.id}")

        await bot_banco.tocar(type("U", (), {"callback_query": consulta})(), None)

        assert "Gasto de casa: Mercadona" in consulta.texto and "💳 tarjeta" in consulta.texto
        assert any(d.startswith("ca:bg:") for d in _datos(consulta.botones)), "se puede borrar"

    @pytest.mark.asyncio
    async def test_tocar_negocio_deja_meterlo_en_un_trabajo(self, db, conexion, cuenta):
        await con_un_pago_nuevo(db, conexion, cuenta, mov("r1", "120.00", "COMPRA EN LEROY MERLIN"))
        m = db.query(MovimientoLeido).one()
        consulta = _Consulta(f"bk:neg:{m.id}")

        await bot_banco.tocar(type("U", (), {"callback_query": consulta})(), None)

        assert "Gasto anotado: Leroy Merlin" in consulta.texto
        assert any(d.startswith("ap:trab:") for d in _datos(consulta.botones))

    @pytest.mark.asyncio
    async def test_un_ingreso_ofrece_los_cobros_pendientes(self, db, conexion, cuenta):
        pendiente = crear_apunte(db, USUARIO, "pendiente Reforma baño Ana 980", origen="bot")
        await con_un_pago_nuevo(
            db, conexion, cuenta, mov("r1", "980.00", "Transferencia De Ana Ruiz", sentido="CRDT")
        )
        bot = _Bot()
        await bot_banco.preguntar(bot, db)

        _, texto, botones = bot.enviados[0]
        m = db.query(MovimientoLeido).one()
        assert "+980,00 € · Ana Ruiz" in texto
        assert f"bk:cob:{m.id}:{pendiente.id}" in _datos(botones)
        assert f"bk:casa:{m.id}" not in _datos(botones), "un ingreso no es un gasto de Casa"

    @pytest.mark.asyncio
    async def test_la_revision_lee_avisa_y_pregunta(self, db, conexion, cuenta):
        await servicio.leer_nuevos(db, conexion)
        cuenta.movs.append(mov("r1", "62.10", "COMPRA EN MERCADONA"))
        conexion.valido_hasta = datetime.now(timezone.utc) + timedelta(days=3)
        db.commit()
        bot = _Bot()

        await bot_banco.revisar(type("C", (), {"bot": bot})())

        textos = [t for _, t, _ in bot.enviados]
        assert any("caduca" in t for t in textos)
        assert any("Mercadona" in t for t in textos)
