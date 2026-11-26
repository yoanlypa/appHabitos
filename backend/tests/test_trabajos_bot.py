"""Los trabajos desde el bot: crearlos, meter en ellos un gasto y ver sus cuentas.

Lo que puede romperse en silencio: que el nombre del trabajo se coma un
apunte que se escribió después de tocar el botón, que un trabajo se cuelgue
de la Ana equivocada, que la lista ofrezca obras terminadas, o que las
cuentas del bot digan otra cosa que la ficha de la web.
"""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.bot import acciones, handlers, trabajos as bot_trabajos
from app.dominio.models import Apunte, Trabajo
from app.nucleo.tiempo import hoy_local
from app.servicios.apuntes import crear_apunte, crear_movimiento
from app.servicios.clientes import crear_cliente
from app.servicios.trabajos import crear_por_texto, crear_trabajo, en_curso, ficha_trabajo
from tests.conftest import USUARIO
from tests.test_bot_mejoras import _boton, _contexto, _datos_de, _escribir, _pulsar

HOY = hoy_local()


class TestServicio:
    def test_crear_por_texto_reconoce_al_cliente(self, db):
        ana = crear_cliente(db, USUARIO, "Ana Ruiz")
        nuevo = crear_por_texto(db, USUARIO, "Reforma baño Ana Ruiz")
        assert nuevo.trabajo.cliente_id == ana.id
        assert nuevo.trabajo.fecha_inicio == HOY
        assert nuevo.candidatos == []

    def test_con_dos_anas_no_se_adivina(self, db):
        crear_cliente(db, USUARIO, "Ana Ruiz")
        crear_cliente(db, USUARIO, "Ana López")
        nuevo = crear_por_texto(db, USUARIO, "Cocina de Ana")
        assert nuevo.trabajo.cliente_id is None
        assert len(nuevo.candidatos) == 2

    def test_en_curso_no_ofrece_lo_terminado(self, db):
        crear_trabajo(db, USUARIO, "Viejo", fecha_inicio=HOY - timedelta(days=30), fecha_fin=HOY - timedelta(days=1))
        acaba_hoy = crear_trabajo(db, USUARIO, "Acaba hoy", fecha_inicio=HOY, fecha_fin=HOY)
        abierto = crear_trabajo(db, USUARIO, "Abierto")
        assert {t.id for t in en_curso(db, USUARIO)} == {acaba_hoy.id, abierto.id}


class TestBotonDelApunte:
    @pytest.mark.asyncio
    async def test_meter_un_gasto_en_un_trabajo_con_dos_toques(self, db):
        obra = crear_trabajo(db, USUARIO, "Reforma baño")
        gasto = crear_apunte(db, USUARIO, "-120 azulejos", origen="bot")

        update, consulta = _pulsar(f"ap:trab:{gasto.id}")
        await acciones.tocar(update, _contexto({}))
        assert f"ap:tj:{gasto.id}:{obra.id}" in _datos_de(consulta.botones)

        update, consulta = _pulsar(f"ap:tj:{gasto.id}:{obra.id}")
        await acciones.tocar(update, _contexto({}))

        db.refresh(gasto)
        assert gasto.trabajo_id == obra.id
        assert "📁 Reforma baño" in consulta.texto, "se dice dónde ha quedado"

    @pytest.mark.asyncio
    async def test_sacarlo_del_trabajo(self, db):
        obra = crear_trabajo(db, USUARIO, "Reforma baño")
        gasto = crear_movimiento(db, USUARIO, "gasto", "azulejos", Decimal("120"), HOY, False, "bot", trabajo_id=obra.id)

        update, consulta = _pulsar(f"ap:trab:{gasto.id}")
        await acciones.tocar(update, _contexto({}))
        assert f"ap:tj:{gasto.id}:{obra.id}" not in _datos_de(consulta.botones), "no se ofrece el que ya tiene"

        update, _ = _pulsar(_boton(consulta.botones, f"ap:tj:{gasto.id}:0"))
        await acciones.tocar(update, _contexto({}))
        db.refresh(gasto)
        assert gasto.trabajo_id is None

    @pytest.mark.asyncio
    async def test_trabajo_nuevo_escribiendo_su_nombre(self, db):
        ana = crear_cliente(db, USUARIO, "Ana Ruiz")
        gasto = crear_apunte(db, USUARIO, "-120 azulejos", origen="bot")
        user_data = {}

        update, _ = _pulsar(f"ap:tn:{gasto.id}")
        await acciones.tocar(update, _contexto(user_data))

        update, mensaje = _escribir("Reforma baño Ana Ruiz")
        await handlers.anotar(update, _contexto(user_data))

        obra = db.query(Trabajo).one()
        assert obra.titulo == "Reforma baño Ana Ruiz" and obra.cliente_id == ana.id
        db.refresh(gasto)
        assert gasto.trabajo_id == obra.id
        assert db.query(Apunte).count() == 1, "el nombre no se ha anotado como nota"
        assert "Trabajo creado" in mensaje.respuestas[0][0]

    @pytest.mark.asyncio
    async def test_el_nombre_no_se_come_un_apunte(self, db):
        """Tocar "Trabajo nuevo" y escribir otro gasto: se anota, no se vuelve trabajo."""
        gasto = crear_apunte(db, USUARIO, "-120 azulejos", origen="bot")
        user_data = {}
        update, _ = _pulsar(f"ap:tn:{gasto.id}")
        await acciones.tocar(update, _contexto(user_data))

        update, _ = _escribir("-45 gasolina")
        await handlers.anotar(update, _contexto(user_data))

        assert db.query(Trabajo).count() == 0
        assert db.query(Apunte).filter(Apunte.concepto == "gasolina").count() == 1
        # Y ya no se espera: lo siguiente sin importe es una nota, no un trabajo.
        update, _ = _escribir("llamar a Ana")
        await handlers.anotar(update, _contexto(user_data))
        assert db.query(Trabajo).count() == 0


class TestComandos:
    @pytest.mark.asyncio
    async def test_crear_y_ver_la_ficha_con_sus_cuentas(self, db):
        update, mensaje = _escribir("/trabajo Reforma baño")
        await bot_trabajos.trabajo(update, _contexto({}, args=["Reforma", "baño"]))
        obra = db.query(Trabajo).one()
        assert "Trabajo creado: Reforma baño" in mensaje.respuestas[0][0]

        crear_movimiento(db, USUARIO, "trabajo", "Reforma baño", Decimal("980.50"), HOY, True, "bot", trabajo_id=obra.id)
        crear_movimiento(db, USUARIO, "gasto", "azulejos", Decimal("120"), HOY, False, "bot", trabajo_id=obra.id)

        update, consulta = _pulsar(f"tr:ver:{obra.id}")
        await bot_trabajos.tocar(update, _contexto({}))

        cuentas = ficha_trabajo(db, USUARIO, obra.id).cuentas
        assert cuentas.beneficio == Decimal("860.50")
        assert "Queda 860,50 €" in consulta.texto, "las mismas cuentas que la web"
        assert "Por cobrar 980,50 €" in consulta.texto

    @pytest.mark.asyncio
    async def test_terminar_y_facturar_desde_la_ficha(self, db):
        obra = crear_trabajo(db, USUARIO, "Pintura", fecha_inicio=HOY - timedelta(days=3))

        update, _ = _pulsar(f"tr:fin:{obra.id}")
        await bot_trabajos.tocar(update, _contexto({}))
        update, consulta = _pulsar(f"tr:fac:{obra.id}")
        await bot_trabajos.tocar(update, _contexto({}))

        db.refresh(obra)
        assert obra.fecha_fin == HOY and obra.facturado
        assert "Facturado: sí" in consulta.texto

    @pytest.mark.asyncio
    async def test_la_lista_sin_trabajos_explica_como_crear_uno(self, db):
        update, mensaje = _escribir("/trabajos")
        await bot_trabajos.trabajos(update, _contexto({}))
        assert "/trabajo Reforma baño" in mensaje.respuestas[0][0]

    @pytest.mark.asyncio
    async def test_dos_anas_se_pregunta_y_se_elige(self, db):
        crear_cliente(db, USUARIO, "Ana Ruiz")
        lopez = crear_cliente(db, USUARIO, "Ana López")

        update, mensaje = _escribir("/trabajo Cocina de Ana")
        await bot_trabajos.trabajo(update, _contexto({}, args=["Cocina", "de", "Ana"]))

        pregunta, botones = mensaje.respuestas[1]
        assert "¿De qué Ana" in pregunta
        obra = db.query(Trabajo).one()
        update, _ = _pulsar(f"tr:cli:{obra.id}:{lopez.id}")
        await bot_trabajos.tocar(update, _contexto({}))
        db.refresh(obra)
        assert obra.cliente_id == lopez.id

    @pytest.mark.asyncio
    async def test_un_trabajo_de_otro_no_se_ve(self, db):
        ajeno = crear_trabajo(db, 111222333, "Lo de otro")
        update, consulta = _pulsar(f"tr:ver:{ajeno.id}")
        await bot_trabajos.tocar(update, _contexto({}))
        assert consulta.texto == "Ese trabajo ya no está."
