"""El bot con botones, el día delante del apunte y la importación en bloque.

Lo que se prueba es lo que puede salir mal sin que se note: que un apunte
acabe en el día que no es, que una nota con saltos de línea se trocee en
apuntes, que dos capturas del mismo historial metan los pagos dos veces,
que un botón viejo borre lo que no debe, o que algo se guarde antes de
haber dicho que sí.
"""
import io
from datetime import timedelta
from decimal import Decimal

import pytest

from app.bot import acciones, handlers, importar, menu
from app.bot import restaurar as bot_restaurar
from app.dominio.importacion import (
    ImportacionNoValida,
    Movimiento,
    de_lectura,
    filas_de_csv,
    leer_lineas,
    leer_tabla,
    marca_lista,
)
from app.dominio.models import Apunte
from app.dominio.parsing import interpretar_con_fecha, suena_a_gasto
from app.nucleo.hojas import HojaNoLegible, filas_de_xlsx
from app.nucleo.tiempo import hoy_local
from app.servicios import importacion
from app.servicios.apuntes import anotar, crear_apunte
from app.servicios.clientes import crear_cliente
from tests.conftest import USUARIO

OTRO = 111222333
HOY = hoy_local()
AYER = HOY - timedelta(days=1)


# --- Dobles de Telegram -------------------------------------------------------


class _Chat:
    async def send_action(self, _accion):
        pass


class _Mensaje:
    def __init__(self, texto=None, caption=None, document=None, photo=None):
        self.text = texto
        self.caption = caption
        self.document = document
        self.photo = photo
        self.chat = _Chat()
        self.respuestas = []

    async def reply_text(self, texto, reply_markup=None, **_):
        self.respuestas.append((texto, reply_markup))

    async def reply_document(self, document=None, caption=None, reply_markup=None, **_):
        self.respuestas.append((caption, reply_markup))


class _Consulta:
    def __init__(self, data, user_id=USUARIO):
        self.data = data
        self.from_user = type("Usuario", (), {"id": user_id})()
        self.message = _Mensaje()
        self.texto = None
        self.botones = None

    async def answer(self):
        pass

    async def edit_message_text(self, texto, reply_markup=None):
        self.texto, self.botones = texto, reply_markup

    async def edit_message_reply_markup(self, reply_markup=None):
        self.botones = reply_markup


class _Fichero:
    def __init__(self, datos):
        self.datos = datos

    async def download_as_bytearray(self):
        return bytearray(self.datos)


class _Bot:
    def __init__(self, datos=b""):
        self.datos = datos

    async def get_file(self, _file_id):
        return _Fichero(self.datos)


def _contexto(user_data, datos=b"", args=None):
    return type("C", (), {"bot": _Bot(datos), "user_data": user_data, "args": args or []})()


def _escribir(texto, user_id=USUARIO):
    mensaje = _Mensaje(texto)
    usuario = type("Usuario", (), {"id": user_id})()
    return type("U", (), {"message": mensaje, "effective_user": usuario})(), mensaje


def _pulsar(data, user_id=USUARIO):
    consulta = _Consulta(data, user_id)
    return type("U", (), {"callback_query": consulta})(), consulta


def _datos_de(botones) -> list[str]:
    return [b.callback_data for fila in botones.inline_keyboard for b in fila]


def _boton(botones, empieza: str) -> str:
    return next(d for d in _datos_de(botones) if d.startswith(empieza))


# --- El día delante del apunte -----------------------------------------------


class TestFechaDelante:
    def test_ayer_delante_de_un_gasto(self):
        r, fecha = interpretar_con_fecha("ayer -45 gasolina", HOY)
        assert (r.tipo, r.concepto, r.importe, fecha) == ("gasto", "gasolina", Decimal("45"), AYER)

    def test_anteayer(self):
        _, fecha = interpretar_con_fecha("anteayer -3 parking", HOY)
        assert fecha == HOY - timedelta(days=2)

    def test_dia_y_mes_delante_de_un_trabajo(self):
        dia = HOY - timedelta(days=5)
        r, fecha = interpretar_con_fecha(f"{dia.day}/{dia.month} Cambio de grifo Ana 120", HOY)
        assert (r.tipo, r.concepto, fecha) == ("trabajo", "Cambio de grifo Ana", dia)

    def test_sin_fecha_es_none_y_el_texto_no_cambia(self):
        r, fecha = interpretar_con_fecha("Cambio de grifo Ana 120", HOY)
        assert fecha is None
        assert r.concepto == "Cambio de grifo Ana"

    def test_un_concepto_que_empieza_por_numero_no_es_una_fecha(self):
        r, fecha = interpretar_con_fecha("2 grifos Ana 120", HOY)
        assert fecha is None
        assert r.concepto == "2 grifos Ana"

    def test_una_fecha_futura_no_se_consume(self):
        r, fecha = interpretar_con_fecha("mañana Cambio de grifo 120", HOY)
        assert fecha is None
        assert r.concepto == "mañana Cambio de grifo"

    def test_el_apunte_queda_en_su_dia(self, db):
        apunte = crear_apunte(db, USUARIO, "ayer -45 gasolina", origen="bot")
        assert (apunte.fecha, apunte.tipo, apunte.concepto) == (AYER, "gasto", "gasolina")

    def test_sin_fecha_sigue_siendo_de_hoy(self, db):
        assert crear_apunte(db, USUARIO, "-45 gasolina", origen="bot").fecha == HOY

    def test_una_nota_con_fecha_delante_no_pierde_la_fecha(self, db):
        anotado = anotar(db, USUARIO, "15/10 llamar a Ana", origen="bot", admite_nota=True)
        assert (anotado.apunte.tipo, anotado.apunte.concepto) == ("nota", "15/10 llamar a Ana")


class TestSuenaAGasto:
    @pytest.mark.parametrize("concepto", ["gasolina", "Parking centro", "Ferretería Paco", "peaje AP-7"])
    def test_palabras_de_gasto(self, concepto):
        assert suena_a_gasto(concepto) is not None

    @pytest.mark.parametrize(
        "concepto", ["Cambio de grifo Ana", "Reforma baño", "material baño Luis", "Seguros Pérez"]
    )
    def test_lo_que_puede_ser_un_trabajo_no_se_pregunta(self, concepto):
        assert suena_a_gasto(concepto) is None


# --- Los botones del apunte ---------------------------------------------------


class TestBotonesDelApunte:
    async def test_lo_anotado_lleva_sus_botones(self, db):
        update, mensaje = _escribir("-45 gasolina")
        await handlers.anotar(update, _contexto({}))

        texto, botones = mensaje.respuestas[0]
        assert "Gasto anotado" in texto
        apunte = db.query(Apunte).one()
        assert _datos_de(botones) == [
            f"ap:tipo:{apunte.id}",
            f"ap:fec:{apunte.id}",
            f"ap:del:{apunte.id}",
        ]

    async def test_gasolina_sin_guion_se_pregunta_y_se_corrige_con_un_toque(self, db):
        update, mensaje = _escribir("gasolina 45")
        await handlers.anotar(update, _contexto({}))

        texto, botones = mensaje.respuestas[0]
        assert "suena a gasto" in texto
        apunte = db.query(Apunte).one()
        assert apunte.tipo == "trabajo", "la regla de siempre no cambia: se pregunta, no se supone"

        update, consulta = _pulsar(_boton(botones, "ap:tipo:"))
        await acciones.tocar(update, _contexto({}))

        db.expire_all()
        assert db.query(Apunte).one().tipo == "gasto"
        assert "GASTO" in consulta.texto

    async def test_un_trabajo_normal_no_pregunta_nada(self, db):
        update, mensaje = _escribir("Cambio de grifo 120")
        await handlers.anotar(update, _contexto({}))
        assert "suena a gasto" not in mensaje.respuestas[0][0]

    async def test_con_cliente_nombrado_no_se_pregunta(self, db):
        crear_cliente(db, USUARIO, "Luz Marina")
        update, mensaje = _escribir("Luz Marina 80")
        await handlers.anotar(update, _contexto({}))
        assert "suena a gasto" not in mensaje.respuestas[0][0]

    async def test_un_pendiente_se_cobra_con_su_boton(self, db):
        update, mensaje = _escribir("pendiente Reforma baño 980")
        await handlers.anotar(update, _contexto({}))
        _, botones = mensaje.respuestas[0]

        update, consulta = _pulsar(_boton(botones, "ap:cob:"))
        await acciones.tocar(update, _contexto({}))

        db.expire_all()
        assert db.query(Apunte).one().pendiente is False
        assert "cobrado" in consulta.texto
        assert not any(d.startswith("ap:cob:") for d in _datos_de(consulta.botones))

    async def test_ayer_con_dos_toques(self, db):
        apunte = crear_apunte(db, USUARIO, "-45 gasolina", origen="bot")

        update, consulta = _pulsar(f"ap:fec:{apunte.id}")
        await acciones.tocar(update, _contexto({}))
        update, consulta = _pulsar(_boton(consulta.botones, f"ap:fd:{apunte.id}:1"))
        await acciones.tocar(update, _contexto({}))

        db.expire_all()
        assert db.query(Apunte).one().fecha == AYER
        assert "ayer" in consulta.texto

    async def test_escribir_el_dia_mueve_el_apunte_y_no_anota_nada(self, db):
        apunte = crear_apunte(db, USUARIO, "-45 gasolina", origen="bot")
        user_data = {}
        update, _ = _pulsar(f"ap:fo:{apunte.id}")
        await acciones.tocar(update, _contexto(user_data))

        dia = HOY - timedelta(days=4)
        update, mensaje = _escribir(f"{dia.day}/{dia.month}")
        await handlers.anotar(update, _contexto(user_data))

        db.expire_all()
        assert db.query(Apunte).one().fecha == dia, "ni una nota nueva, ni otro apunte"
        assert "Movido" in mensaje.respuestas[0][0]

    async def test_si_en_vez_del_dia_se_escribe_otro_apunte_se_anota(self, db):
        apunte = crear_apunte(db, USUARIO, "-45 gasolina", origen="bot")
        user_data = {}
        update, _ = _pulsar(f"ap:fo:{apunte.id}")
        await acciones.tocar(update, _contexto(user_data))

        update, _ = _escribir("-3 parking")
        await handlers.anotar(update, _contexto(user_data))
        # Y lo siguiente ya no se toma por una fecha de aquel apunte.
        update, _ = _escribir("ayer")
        await handlers.anotar(update, _contexto(user_data))

        db.expire_all()
        apuntes = db.query(Apunte).order_by(Apunte.id).all()
        assert [(a.tipo, a.concepto, a.fecha) for a in apuntes] == [
            ("gasto", "gasolina", HOY),
            ("gasto", "parking", HOY),
            ("nota", "ayer", HOY),
        ]

    async def test_borrar_pide_confirmacion(self, db):
        apunte = crear_apunte(db, USUARIO, "-45 gasolina", origen="bot")

        update, consulta = _pulsar(f"ap:del:{apunte.id}")
        await acciones.tocar(update, _contexto({}))
        assert db.query(Apunte).count() == 1, "el primer toque solo pregunta"
        assert "¿Borro esto?" in consulta.texto

        update, consulta = _pulsar(_boton(consulta.botones, "ap:dely:"))
        await acciones.tocar(update, _contexto({}))
        assert db.query(Apunte).count() == 0
        assert "Borrado" in consulta.texto

    async def test_decir_que_no_lo_deja_como_estaba(self, db):
        apunte = crear_apunte(db, USUARIO, "-45 gasolina", origen="bot")
        update, consulta = _pulsar(f"ap:del:{apunte.id}")
        await acciones.tocar(update, _contexto({}))
        update, consulta = _pulsar(_boton(consulta.botones, "ap:ver:"))
        await acciones.tocar(update, _contexto({}))

        assert db.query(Apunte).count() == 1
        assert "Gasto anotado" in consulta.texto

    async def test_un_boton_de_un_apunte_ya_borrado_no_revienta(self, db):
        update, consulta = _pulsar("ap:cob:99999")
        await acciones.tocar(update, _contexto({}))
        assert "ya no está" in consulta.texto

    async def test_nadie_toca_los_apuntes_de_otro(self, db):
        apunte = crear_apunte(db, USUARIO, "-45 gasolina", origen="bot")
        for data in (f"ap:dely:{apunte.id}", f"ap:tipo:{apunte.id}", f"ap:fd:{apunte.id}:1"):
            update, consulta = _pulsar(data, user_id=OTRO)
            await acciones.tocar(update, _contexto({}))
            assert "ya no está" in consulta.texto

        db.expire_all()
        suyo = db.query(Apunte).one()
        assert (suyo.tipo, suyo.fecha) == ("gasto", HOY)

    async def test_deben_se_cobra_tocando_y_la_lista_se_acorta(self, db):
        crear_apunte(db, USUARIO, "pendiente Reforma baño 980", origen="bot")
        crear_apunte(db, USUARIO, "pendiente Cocina 300", origen="bot")
        update, mensaje = _escribir("/deben")
        await handlers.deben(update, _contexto({}))
        texto, botones = mensaje.respuestas[0]
        assert len(_datos_de(botones)) == 2

        update, consulta = _pulsar(_datos_de(botones)[0])
        await acciones.cobrar_de_la_lista(update, _contexto({}))

        assert "300,00" in consulta.texto and "980,00" not in consulta.texto
        assert len(_datos_de(consulta.botones)) == 1


class TestMenu:
    async def test_los_botones_de_abajo_no_se_anotan_como_notas(self, db):
        for etiqueta in ("📊 Hoy", "📅 Mes", "💰 Me deben", "🗓 Agenda", "📝 Notas"):
            update, mensaje = _escribir(etiqueta)
            await menu.tocado(update, _contexto({}))
            assert mensaje.respuestas, etiqueta
        assert db.query(Apunte).count() == 0

    def test_el_bot_se_monta_con_todos_sus_handlers(self, monkeypatch):
        from app.bot import main

        monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "123456:ABC-de-mentira")
        app = main.construir_app()
        registrados = [h for grupo in app.handlers.values() for h in grupo]
        # El que anota cualquier texto tiene que ser el último de los de
        # mensajes: si no, se comería los botones del teclado.
        ultimo = [h for h in registrados if getattr(h, "callback", None) is handlers.anotar]
        de_menu = [h for h in registrados if getattr(h, "callback", None) is menu.tocado]
        assert registrados.index(de_menu[0]) < registrados.index(ultimo[0])

    def test_los_comandos_del_menu_existen(self, monkeypatch):
        from app.bot import main

        monkeypatch.setattr(main, "TELEGRAM_BOT_TOKEN", "123456:ABC-de-mentira")
        app = main.construir_app()
        atendidos = set()
        for grupo in app.handlers.values():
            for h in grupo:
                atendidos |= set(getattr(h, "commands", ()))
        assert {nombre for nombre, _ in menu.COMANDOS} <= atendidos


# --- Importar: las reglas -----------------------------------------------------


class TestLineas:
    def test_un_apunte_por_linea(self):
        dia = HOY - timedelta(days=3)
        texto = f"{dia.day}/{dia.month} -2,75 parking\nayer -45 gasolina\nCambio de grifo Ana 120"
        assert leer_lineas(texto, HOY) == [
            Movimiento(dia, "gasto", "parking", Decimal("2.75")),
            Movimiento(AYER, "gasto", "gasolina", Decimal("45")),
            Movimiento(HOY, "trabajo", "Cambio de grifo Ana", Decimal("120")),
        ]

    def test_una_nota_con_saltos_de_linea_sigue_siendo_una_nota(self):
        assert leer_lineas("Comprar:\ntornillos\nsilicona 2", HOY) is None

    def test_una_sola_linea_no_es_una_lista(self):
        assert leer_lineas("-45 gasolina", HOY) is None


class TestTabla:
    def test_csv_de_excel_en_español(self):
        texto = "Fecha;Concepto;Importe\n03/11/2025;Parking Sector 2;2,75\n04/11/2025;Peaje;1.234,50\n"
        movimientos = leer_tabla(filas_de_csv(texto), HOY)
        assert [(m.fecha.isoformat(), m.tipo, m.concepto, m.importe) for m in movimientos] == [
            ("2025-11-03", None, "Parking Sector 2", Decimal("2.75")),
            ("2025-11-04", None, "Peaje", Decimal("1234.50")),
        ]

    def test_con_columna_de_tipo(self):
        texto = "fecha,tipo,concepto,importe\n2025-11-03,gasto,Parking,2.75\n2025-11-03,ingreso,Grifo,120\n"
        assert [m.tipo for m in leer_tabla(filas_de_csv(texto), HOY)] == ["gasto", "trabajo"]

    def test_un_extracto_con_signos_se_reparte_solo(self):
        texto = "fecha,descripcion,importe\n2025-11-03,Gasolinera,-45.00\n2025-11-04,Transferencia Ana,120.00\n"
        movimientos = leer_tabla(filas_de_csv(texto), HOY)
        assert [(m.tipo, m.importe) for m in movimientos] == [
            ("gasto", Decimal("45.00")),
            ("trabajo", Decimal("120.00")),
        ]

    def test_sin_las_tres_columnas_se_dice_cual_falta(self):
        with pytest.raises(ImportacionNoValida, match="fecha, importe"):
            leer_tabla(filas_de_csv("nombre,telefono\nAna,600111222\n"), HOY)

    def test_una_fila_mala_y_no_entra_ninguna(self):
        texto = "fecha,concepto,importe\n2025-11-03,Parking,2.75\n2025-11-04,Peaje,doce\n"
        with pytest.raises(ImportacionNoValida, match="fila 3"):
            leer_tabla(filas_de_csv(texto), HOY)

    def test_una_fecha_futura_no_entra(self):
        manana = HOY + timedelta(days=1)
        with pytest.raises(ImportacionNoValida, match="futura"):
            leer_tabla(filas_de_csv(f"fecha,concepto,importe\n{manana.isoformat()},Parking,2.75\n"), HOY)

    def test_excel(self):
        from openpyxl import Workbook

        libro = Workbook()
        hoja = libro.active
        hoja.append(["Fecha", "Concepto", "Importe"])
        hoja.append([AYER, "Parking Sector 2", 2.75])
        hoja.append([AYER, "Peaje", 12])
        salida = io.BytesIO()
        libro.save(salida)

        movimientos = leer_tabla(filas_de_xlsx(salida.getvalue()), HOY)
        assert [(m.fecha, m.concepto, m.importe) for m in movimientos] == [
            (AYER, "Parking Sector 2", Decimal("2.75")),
            (AYER, "Peaje", Decimal("12")),
        ]

    def test_un_fichero_que_no_es_excel(self):
        with pytest.raises(HojaNoLegible):
            filas_de_xlsx(b"esto no es un excel")


class TestLecturaDeCaptura:
    def test_se_queda_con_lo_que_se_sostiene(self):
        leido = {
            "movimientos": [
                {"fecha": AYER.isoformat(), "concepto": "Parking Sector 2 Málaga", "importe": 2.75, "tipo": "gasto"},
                {"fecha": AYER.strftime("%d/%m/%Y"), "concepto": "Parking Sector 2 Málaga", "importe": "1,32"},
                {"fecha": None, "concepto": "Sin fecha", "importe": 3},
                {"fecha": AYER.isoformat(), "concepto": "Sin importe", "importe": None},
                {"fecha": (HOY + timedelta(days=3)).isoformat(), "concepto": "Futuro", "importe": 3},
                {"fecha": "2001-01-01", "concepto": "Prehistoria", "importe": 3},
                {"fecha": AYER.isoformat(), "concepto": "  ", "importe": 3},
                {"fecha": AYER.isoformat(), "concepto": "Absurdo", "importe": 999999},
                "basura",
            ]
        }
        assert de_lectura(leido, HOY) == [
            Movimiento(AYER, "gasto", "Parking Sector 2 Málaga", Decimal("2.75")),
            Movimiento(AYER, "gasto", "Parking Sector 2 Málaga", Decimal("1.32")),
        ]

    def test_una_respuesta_rara_no_revienta(self):
        assert de_lectura({}, HOY) == []
        assert de_lectura({"movimientos": "nada"}, HOY) == []

    def test_la_marca_es_la_palabra_sola(self):
        assert marca_lista("lista") and marca_lista(" Historial. ")
        assert not marca_lista("lista de materiales baño")
        assert not marca_lista(None)


# --- Importar: sin repetir ----------------------------------------------------


def _parking(dia, importe):
    return Movimiento(dia, "gasto", "Parking Sector 2 Málaga", Decimal(importe))


class TestSinRepetir:
    def test_dos_capturas_que_se_solapan_no_meten_nada_dos_veces(self, db):
        """El caso real: dos capturas del historial del parking, con filas en común."""
        d = [HOY - timedelta(days=n) for n in range(6)]
        primera = [_parking(d[0], "1.84"), _parking(d[0], "0.55"), _parking(d[0], "2.75"),
                   _parking(d[1], "2.20"), _parking(d[1], "2.75"), _parking(d[2], "1.32")]
        # La segunda repite una fila, y el modelo la ha llamado de otra manera.
        segunda = [Movimiento(d[2], "gasto", "Estacionamiento Sector 2", Decimal("1.32")),
                   _parking(d[2], "2.75"), _parking(d[4], "0.69"), _parking(d[4], "2.75"),
                   _parking(d[5], "2.75")]

        assert len(importacion.importar(db, USUARIO, primera, origen="bot")) == 6
        plan = importacion.planificar(db, USUARIO, segunda)
        assert (len(plan.nuevos), len(plan.repetidos)) == (4, 1)
        assert len(importacion.importar(db, USUARIO, segunda, origen="bot")) == 4

        assert db.query(Apunte).count() == 10
        assert sum(a.importe for a in db.query(Apunte)) == Decimal("20.35")

    def test_importar_lo_mismo_dos_veces_no_duplica(self, db):
        lista = [_parking(AYER, "2.75"), _parking(AYER, "2.75"), _parking(HOY, "1.32")]
        assert len(importacion.importar(db, USUARIO, lista, origen="bot")) == 3
        assert importacion.importar(db, USUARIO, lista, origen="bot") == []
        assert db.query(Apunte).count() == 3

    def test_dos_iguales_el_mismo_dia_son_dos(self, db):
        crear_apunte(db, USUARIO, "-2,75 parking", origen="bot")
        plan = importacion.planificar(db, USUARIO, [_parking(HOY, "2.75"), _parking(HOY, "2.75")])
        assert (len(plan.nuevos), len(plan.repetidos)) == (1, 1)

    def test_lo_apartado_por_repetido_se_puede_meter_igual(self, db):
        crear_apunte(db, USUARIO, "-2,75 café y tostada", origen="bot")
        lista = [_parking(HOY, "2.75")]
        assert importacion.importar(db, USUARIO, lista, origen="bot") == []
        assert len(importacion.importar(db, USUARIO, lista, origen="bot", todo=True)) == 1

    def test_lo_de_otro_usuario_no_cuenta_como_repetido(self, db):
        importacion.importar(db, OTRO, [_parking(HOY, "2.75")], origen="bot")
        assert len(importacion.planificar(db, USUARIO, [_parking(HOY, "2.75")]).nuevos) == 1

    def test_un_gasto_y_un_cobro_del_mismo_importe_no_son_lo_mismo(self, db):
        crear_apunte(db, USUARIO, "Cambio de grifo 120", origen="bot")
        plan = importacion.planificar(db, USUARIO, [Movimiento(HOY, "gasto", "Material", Decimal("120"))])
        assert len(plan.nuevos) == 1

    def test_sin_saber_si_son_gastos_o_cobros_no_entra_nada(self, db):
        with pytest.raises(ValueError):
            importacion.importar(db, USUARIO, [Movimiento(HOY, None, "Parking", Decimal("2"))], origen="bot")
        assert db.query(Apunte).count() == 0

    def test_el_cliente_nombrado_se_cuelga_solo(self, db):
        ana = crear_cliente(db, USUARIO, "Ana Ruiz")
        apuntes = importacion.importar(
            db, USUARIO, [Movimiento(HOY, "trabajo", "Grifo Ana Ruiz", Decimal("120"))], origen="bot"
        )
        assert apuntes[0].cliente_id == ana.id

    def test_deshacer_quita_solo_lo_importado(self, db):
        suyo = crear_apunte(db, USUARIO, "-45 gasolina", origen="bot")
        apuntes = importacion.importar(db, USUARIO, [_parking(AYER, "2.75"), _parking(AYER, "1.32")], origen="bot")
        ids = [a.id for a in apuntes]

        assert importacion.borrar_importados(db, OTRO, ids) == 0, "ni con los números en la mano"
        assert importacion.borrar_importados(db, USUARIO, ids) == 2
        assert [a.id for a in db.query(Apunte)] == [suyo.id]


# --- Importar: por el bot -----------------------------------------------------


class TestImportarPorElBot:
    async def test_varias_lineas_se_enseñan_y_solo_entran_al_confirmar(self, db):
        user_data = {}
        update, mensaje = _escribir("ayer -2,75 parking\nayer -1,32 parking\n-45 gasolina")
        await handlers.anotar(update, _contexto(user_data))

        texto, botones = mensaje.respuestas[0]
        assert "3 movimientos nuevos" in texto and "49,07" in texto
        assert db.query(Apunte).count() == 0, "enseñar no puede escribir nada"

        update, consulta = _pulsar(_boton(botones, "imp:si:"))
        await importar.confirmar(update, _contexto(user_data))

        assert "Añadidos 3" in consulta.texto
        assert [(a.fecha, a.tipo) for a in db.query(Apunte).order_by(Apunte.id)] == [
            (AYER, "gasto"), (AYER, "gasto"), (HOY, "gasto"),
        ]

    async def test_un_segundo_toque_no_importa_dos_veces(self, db):
        user_data = {}
        update, mensaje = _escribir("-2,75 parking\n-1,32 parking")
        await handlers.anotar(update, _contexto(user_data))
        data = _boton(mensaje.respuestas[0][1], "imp:si:")
        for _ in range(2):
            update, consulta = _pulsar(data)
            await importar.confirmar(update, _contexto(user_data))

        assert "Ya no tengo esa lista" in consulta.texto
        assert db.query(Apunte).count() == 2

    async def test_cancelar_no_guarda_nada(self, db):
        user_data = {}
        update, mensaje = _escribir("-2,75 parking\n-1,32 parking")
        await handlers.anotar(update, _contexto(user_data))
        update, consulta = _pulsar(_boton(mensaje.respuestas[0][1], "imp:no:"))
        await importar.confirmar(update, _contexto(user_data))

        assert "Cancelado" in consulta.texto
        assert db.query(Apunte).count() == 0

    async def test_dos_listas_seguidas_no_se_pisan(self, db):
        user_data = {}
        update, primero = _escribir("-2,75 parking\n-1,32 parking")
        await handlers.anotar(update, _contexto(user_data))
        update, segundo = _escribir("-45 gasolina\n-12 peaje\n-3 café")
        await handlers.anotar(update, _contexto(user_data))

        update, _ = _pulsar(_boton(primero.respuestas[0][1], "imp:si:"))
        await importar.confirmar(update, _contexto(user_data))
        assert db.query(Apunte).count() == 2

        update, _ = _pulsar(_boton(segundo.respuestas[0][1], "imp:si:"))
        await importar.confirmar(update, _contexto(user_data))
        assert db.query(Apunte).count() == 5

    async def test_deshacer_la_importacion(self, db):
        user_data = {}
        update, mensaje = _escribir("-2,75 parking\n-1,32 parking")
        await handlers.anotar(update, _contexto(user_data))
        update, consulta = _pulsar(_boton(mensaje.respuestas[0][1], "imp:si:"))
        await importar.confirmar(update, _contexto(user_data))

        update, consulta = _pulsar(_boton(consulta.botones, "imp:deshacer:"))
        await importar.confirmar(update, _contexto(user_data))

        assert "Deshecho" in consulta.texto
        assert db.query(Apunte).count() == 0

    async def test_un_csv_sin_tipo_pregunta_si_son_gastos_o_cobros(self, db):
        datos = "Fecha;Concepto;Importe\n03/11/2025;Parking Sector 2;2,75\n04/11/2025;Parking Sector 2;1,32\n".encode()
        user_data = {}
        mensaje = _Mensaje(document=type("D", (), {"file_id": "x", "file_size": len(datos)})())
        update = type("U", (), {"message": mensaje, "effective_user": type("Usuario", (), {"id": USUARIO})()})()
        await bot_restaurar.recibir_copia(update, _contexto(user_data, datos))

        texto, botones = mensaje.respuestas[0]
        assert "¿Qué son?" in texto
        assert db.query(Apunte).count() == 0

        update, consulta = _pulsar(_boton(botones, "imp:gasto:"))
        await importar.confirmar(update, _contexto(user_data))
        assert "2 movimientos nuevos" in consulta.texto
        assert db.query(Apunte).count() == 0, "decir qué son todavía no es decir que sí"

        update, consulta = _pulsar(_boton(consulta.botones, "imp:si:"))
        await importar.confirmar(update, _contexto(user_data))
        assert [(a.tipo, a.fecha.isoformat()) for a in db.query(Apunte).order_by(Apunte.id)] == [
            ("gasto", "2025-11-03"), ("gasto", "2025-11-04"),
        ]

    async def test_una_copia_con_una_fila_rota_no_se_cuela_como_lista(self, db):
        datos = (
            "fecha,tipo,concepto,importe,pendiente,origen\n"
            "2025-11-03,gasto,Parking,-2.75,no,bot\n"
        ).encode()
        mensaje = _Mensaje(document=type("D", (), {"file_id": "x", "file_size": len(datos)})())
        update = type("U", (), {"message": mensaje, "effective_user": type("Usuario", (), {"id": USUARIO})()})()
        await bot_restaurar.recibir_copia(update, _contexto({}, datos))

        texto, botones = mensaje.respuestas[0]
        assert "importe negativo" in texto and botones is None

    async def test_una_captura_con_varios_pagos_se_propone_en_vez_de_fallar(self, db, monkeypatch):
        async def lee(_imagen, _mime):
            return {
                "movimientos": [
                    {"fecha": AYER.isoformat(), "concepto": "Parking Sector 2 Málaga", "importe": 2.75, "tipo": "gasto"},
                    {"fecha": AYER.isoformat(), "concepto": "Parking Sector 2 Málaga", "importe": 1.32, "tipo": "gasto"},
                ]
            }

        monkeypatch.setattr(importacion, "leer_movimientos", lee)
        user_data = {}
        mensaje = _Mensaje()
        assert await importar.proponer_captura(mensaje, _contexto(user_data), USUARIO, b"png", "image/png")

        texto, botones = mensaje.respuestas[0]
        assert "2 movimientos nuevos" in texto and "4,07" in texto
        update, _ = _pulsar(_boton(botones, "imp:si:"))
        await importar.confirmar(update, _contexto(user_data))
        assert db.query(Apunte).count() == 2

    async def test_una_captura_con_un_solo_pago_no_es_una_lista(self, db, monkeypatch):
        async def lee(_imagen, _mime):
            return {"movimientos": [{"fecha": AYER.isoformat(), "concepto": "Parking", "importe": 2.75}]}

        monkeypatch.setattr(importacion, "leer_movimientos", lee)
        mensaje = _Mensaje()
        assert not await importar.proponer_captura(mensaje, _contexto({}), USUARIO, b"png", "image/png")
        assert mensaje.respuestas == []


# --- La foto: ticket o lista --------------------------------------------------


def _jpg() -> bytes:
    from PIL import Image

    salida = io.BytesIO()
    Image.new("RGB", (300, 400), "white").save(salida, format="JPEG")
    return salida.getvalue()


def _foto(datos, caption=None):
    mensaje = _Mensaje(caption=caption, photo=[type("F", (), {"file_id": "x"})()])
    usuario = type("Usuario", (), {"id": USUARIO})()
    return type("U", (), {"message": mensaje, "effective_user": usuario})(), mensaje


def _dos_parkings():
    async def lee(_imagen, _mime):
        return {
            "movimientos": [
                {"fecha": AYER.isoformat(), "concepto": "Parking Sector 2", "importe": 2.75, "tipo": "gasto"},
                {"fecha": AYER.isoformat(), "concepto": "Parking Sector 2", "importe": 1.32, "tipo": "gasto"},
            ]
        }

    return lee


class TestFotoDeVariosPagos:
    async def test_una_captura_que_no_es_un_ticket_se_lee_como_lista(self, db, monkeypatch):
        from app.dominio.models import Factura
        from app.servicios import facturas

        async def no_es_ticket(_imagen, _mime):
            return {"total": None}

        monkeypatch.setattr(facturas, "leer_ticket", no_es_ticket)
        monkeypatch.setattr(importacion, "leer_movimientos", _dos_parkings())
        datos, user_data = _jpg(), {}

        update, mensaje = _foto(datos)
        await handlers.foto_de_ticket(update, _contexto(user_data, datos))

        texto, botones = mensaje.respuestas[0]
        assert "2 movimientos nuevos" in texto
        assert db.query(Apunte).count() == 0
        assert db.query(Factura).count() == 0, "una captura no es una factura que guardar"

        update, _ = _pulsar(_boton(botones, "imp:si:"))
        await importar.confirmar(update, _contexto(user_data))
        assert db.query(Apunte).count() == 2

    async def test_con_lista_escrito_no_se_intenta_leer_como_ticket(self, db, monkeypatch):
        from app.servicios import facturas

        async def no_deberia(_imagen, _mime):
            raise AssertionError("con «lista» no se paga la lectura de ticket")

        monkeypatch.setattr(facturas, "leer_ticket", no_deberia)
        monkeypatch.setattr(importacion, "leer_movimientos", _dos_parkings())
        datos = _jpg()

        update, mensaje = _foto(datos, caption="Lista")
        await handlers.foto_de_ticket(update, _contexto({}, datos))
        assert "2 movimientos nuevos" in mensaje.respuestas[0][0]

    async def test_un_ticket_de_verdad_sigue_siendo_un_gasto_con_sus_botones(self, db, monkeypatch):
        from app.servicios import facturas

        async def ticket(_imagen, _mime):
            return {"total": "23,40", "fecha": None, "comercio": "Ferretería Paco", "concepto": "silicona"}

        async def no_deberia(_imagen, _mime):
            raise AssertionError("un ticket con total no es una lista")

        monkeypatch.setattr(facturas, "leer_ticket", ticket)
        monkeypatch.setattr(importacion, "leer_movimientos", no_deberia)
        datos = _jpg()

        update, mensaje = _foto(datos)
        await handlers.foto_de_ticket(update, _contexto({}, datos))

        texto, botones = mensaje.respuestas[0]
        apunte = db.query(Apunte).one()
        assert (apunte.tipo, apunte.importe) == ("gasto", Decimal("23.40"))
        assert "Gasto anotado" in texto
        # Sin "es un cobro": lo que sale de un ticket tiene /emitida.
        assert _datos_de(botones) == [f"ap:fec:{apunte.id}", f"ap:del:{apunte.id}"]

    async def test_si_no_es_ni_ticket_ni_lista_se_dice_y_no_se_anota(self, db, monkeypatch):
        from app.servicios import facturas

        async def nada(_imagen, _mime):
            return {"total": None}

        async def tampoco(_imagen, _mime):
            return {"movimientos": []}

        monkeypatch.setattr(facturas, "leer_ticket", nada)
        monkeypatch.setattr(importacion, "leer_movimientos", tampoco)
        datos = _jpg()

        update, mensaje = _foto(datos)
        await handlers.foto_de_ticket(update, _contexto({}, datos))
        assert "No he sabido leer el total" in mensaje.respuestas[0][0]
        assert db.query(Apunte).count() == 0
