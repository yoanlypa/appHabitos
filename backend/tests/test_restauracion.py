"""Restaurar una copia de seguridad.

Lo que se prueba es lo que puede salir mal sin que se note: que restaurar
duplique lo que ya estaba, que dos gastos iguales del mismo día se queden en
uno, que un trabajo cobrado vuelva a ser deuda, o que el bot escriba en la
base antes de que se haya dicho que sí.

La copia de partida se genera siempre con `exportar_todo()`, la misma
función que usa el bot para mandarla: si su formato cambia, estos tests
tienen que enterarse.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.bot import restaurar as bot_restaurar
from app.dominio.copia_csv import CopiaNoValida, FilaCopia, decodificar, leer_copia
from app.dominio.models import Apunte
from app.servicios import notas as buzon
from app.servicios.apuntes import borrar_apunte, crear_apunte, marcar_cobrado
from app.servicios.export import exportar_todo
from app.servicios.restauracion import planificar, restaurar
from tests.conftest import USUARIO

OTRO = 111222333
CABECERA = "fecha,tipo,concepto,importe,pendiente,origen\n"


def copia_de(db, user_id=USUARIO) -> bytes:
    """Los bytes exactos que manda el bot: utf-8 con BOM."""
    return exportar_todo(db, user_id).encode("utf-8-sig")


def perderlo_todo(db) -> None:
    db.query(Apunte).delete()
    db.commit()


class TestLeerCopia:
    def test_la_copia_tal_cual_la_manda_el_bot(self, db):
        crear_apunte(db, USUARIO, "Reforma baño 980,50", origen="bot")
        crear_apunte(db, USUARIO, "-45 gasolina", origen="web")
        crear_apunte(db, USUARIO, "pendiente Cocina 300", origen="bot")

        filas = leer_copia(decodificar(copia_de(db)))

        assert [(f.tipo, f.concepto, f.importe, f.pendiente, f.origen) for f in filas] == [
            ("trabajo", "Reforma baño", Decimal("980.50"), False, "bot"),
            ("gasto", "gasolina", Decimal("45"), False, "web"),
            ("trabajo", "Cocina", Decimal("300"), True, "bot"),
        ]

    def test_guardada_con_excel_en_espanol(self):
        """Punto y coma, coma decimal, fecha a la española y otra codificación."""
        texto = (
            "fecha;tipo;concepto;importe;pendiente;origen\n"
            "10/09/2026;trabajo;Reforma baño;1.234,50;sí;bot\n"
        )

        filas = leer_copia(decodificar(texto.encode("cp1252")))

        assert filas == [
            FilaCopia(date(2026, 9, 10), "trabajo", "Reforma baño", Decimal("1234.50"), True, "bot")
        ]

    def test_una_linea_mala_no_deja_restaurar_a_medias(self):
        texto = CABECERA + "2026-09-10,trabajo,Grifo,120.00,no,bot\n2026-09-10,trabajo,Grifo,doce,no,bot\n"
        with pytest.raises(CopiaNoValida, match="línea 3"):
            leer_copia(texto)

    def test_un_fichero_que_no_es_una_copia(self):
        with pytest.raises(CopiaNoValida, match="columnas"):
            leer_copia("nombre,telefono\nAna,600111222\n")

    def test_tres_decimales_no_se_redondean_en_silencio(self):
        with pytest.raises(CopiaNoValida, match="dos decimales"):
            leer_copia(CABECERA + "2026-09-10,gasto,Tornillos,1.234,no,bot\n")

    def test_una_copia_vacia_no_es_una_copia(self):
        with pytest.raises(CopiaNoValida, match="ningún apunte"):
            leer_copia(CABECERA)


class TestRestaurar:
    def test_lo_perdido_vuelve_con_su_fecha_e_importe(self, db):
        crear_apunte(db, USUARIO, "Reforma baño 980,50", origen="bot")
        crear_apunte(db, USUARIO, "-45 gasolina", origen="web")
        filas = leer_copia(decodificar(copia_de(db)))
        fecha = filas[0].fecha
        perderlo_todo(db)

        assert restaurar(db, USUARIO, filas) == 2

        vueltos = db.query(Apunte).order_by(Apunte.id).all()
        assert [(a.fecha, a.concepto, a.importe) for a in vueltos] == [
            (fecha, "Reforma baño", Decimal("980.50")),
            (fecha, "gasolina", Decimal("45")),
        ]

    def test_restaurar_dos_veces_no_duplica(self, db):
        crear_apunte(db, USUARIO, "Cambio de grifo 120", origen="bot")
        filas = leer_copia(decodificar(copia_de(db)))

        assert restaurar(db, USUARIO, filas) == 0
        assert restaurar(db, USUARIO, filas) == 0
        assert db.query(Apunte).count() == 1

    def test_dos_gastos_iguales_el_mismo_dia_son_dos(self, db):
        """Dos repostajes de 45 el mismo día son dos, no uno repetido."""
        crear_apunte(db, USUARIO, "-45 gasolina", origen="bot")
        segundo = crear_apunte(db, USUARIO, "-45 gasolina", origen="bot")
        filas = leer_copia(decodificar(copia_de(db)))
        borrar_apunte(db, USUARIO, segundo.id)

        plan = planificar(db, USUARIO, filas)
        assert (len(plan.nuevas), plan.ya_estaban) == (1, 1)

        restaurar(db, USUARIO, filas)
        assert db.query(Apunte).count() == 2

    def test_lo_cobrado_despues_no_vuelve_a_ser_deuda(self, db):
        """La copia se hizo con el trabajo pendiente; luego se cobró. Manda la base."""
        trabajo = crear_apunte(db, USUARIO, "pendiente Cocina 300", origen="bot")
        filas = leer_copia(decodificar(copia_de(db)))
        marcar_cobrado(db, USUARIO, trabajo.id)

        assert restaurar(db, USUARIO, filas) == 0
        db.refresh(trabajo)
        assert trabajo.pendiente is False

    def test_lo_borrado_a_proposito_vuelve_y_por_eso_se_pregunta_antes(self, db):
        """La copia no sabe qué se borró adrede: el bot tiene que enseñarlo antes."""
        malo = crear_apunte(db, USUARIO, "Cambio de grifo 1200", origen="bot")
        filas = leer_copia(decodificar(copia_de(db)))
        borrar_apunte(db, USUARIO, malo.id)

        assert [f.concepto for f in planificar(db, USUARIO, filas).nuevas] == ["Cambio de grifo"]

    def test_se_restaura_en_la_cuenta_de_quien_la_manda(self, db):
        crear_apunte(db, USUARIO, "Cambio de grifo 120", origen="bot")
        filas = leer_copia(decodificar(copia_de(db)))

        assert restaurar(db, OTRO, filas) == 1
        assert db.query(Apunte).filter(Apunte.user_id == USUARIO).count() == 1
        assert db.query(Apunte).filter(Apunte.user_id == OTRO).count() == 1

    def test_las_notas_vuelven_como_notas_y_sin_marcar(self, db):
        """La copia no dice si una nota estaba hecha: vuelve al buzón."""
        nota = buzon.crear(db, USUARIO, "Revisar el coche", origen="bot")
        buzon.marcar_hecha(db, USUARIO, nota.id)
        filas = leer_copia(decodificar(copia_de(db)))
        perderlo_todo(db)

        restaurar(db, USUARIO, filas)

        assert [(n.concepto, n.hecha) for n in buzon.listar_notas(db, USUARIO)] == [
            ("Revisar el coche", False)
        ]


class _Documento:
    def __init__(self, tamano):
        self.file_id = "id-de-mentira"
        self.file_size = tamano


class _Mensaje:
    def __init__(self, tamano):
        self.document = _Documento(tamano)
        self.respuestas = []

    async def reply_text(self, texto, reply_markup=None):
        self.respuestas.append((texto, reply_markup))


class _Fichero:
    def __init__(self, datos):
        self.datos = datos

    async def download_as_bytearray(self):
        return bytearray(self.datos)


class _Bot:
    def __init__(self, datos):
        self.datos = datos

    async def get_file(self, file_id):
        return _Fichero(self.datos)


class _Consulta:
    def __init__(self, data):
        self.data = data
        self.from_user = type("Usuario", (), {"id": USUARIO})()
        self.editado = None

    async def answer(self):
        pass

    async def edit_message_text(self, texto):
        self.editado = texto


def _contexto(datos, user_data):
    return type("C", (), {"bot": _Bot(datos), "user_data": user_data})()


def _reenviar(datos):
    mensaje = _Mensaje(len(datos))
    update = type(
        "U", (), {"message": mensaje, "effective_user": type("Usuario", (), {"id": USUARIO})()}
    )()
    return update, mensaje


def _pulsar(data):
    consulta = _Consulta(data)
    return type("U", (), {"callback_query": consulta})(), consulta


class TestPorElBot:
    @pytest.mark.asyncio
    async def test_primero_enseña_y_solo_restaura_al_confirmar(self, db):
        crear_apunte(db, USUARIO, "Cambio de grifo 120", origen="bot")
        crear_apunte(db, USUARIO, "-45 gasolina", origen="bot")
        datos = copia_de(db)
        perderlo_todo(db)
        user_data = {}

        update, mensaje = _reenviar(datos)
        await bot_restaurar.recibir_copia(update, _contexto(datos, user_data))

        texto, botones = mensaje.respuestas[0]
        assert "Faltan 2" in texto
        assert botones is not None, "sin botón no hay forma de confirmar"
        assert db.query(Apunte).count() == 0, "enseñar no puede escribir nada"

        update, consulta = _pulsar("rest:si")
        await bot_restaurar.confirmar(update, _contexto(datos, user_data))

        assert "Restaurados 2" in consulta.editado
        assert db.query(Apunte).count() == 2

    @pytest.mark.asyncio
    async def test_un_segundo_toque_no_restaura_dos_veces(self, db):
        crear_apunte(db, USUARIO, "Cambio de grifo 120", origen="bot")
        datos = copia_de(db)
        perderlo_todo(db)
        user_data = {}

        update, _ = _reenviar(datos)
        await bot_restaurar.recibir_copia(update, _contexto(datos, user_data))
        for _ in range(2):
            update, consulta = _pulsar("rest:si")
            await bot_restaurar.confirmar(update, _contexto(datos, user_data))

        assert "Ya no tengo esa copia" in consulta.editado
        assert db.query(Apunte).count() == 1

    @pytest.mark.asyncio
    async def test_cancelar_no_toca_nada(self, db):
        crear_apunte(db, USUARIO, "Cambio de grifo 120", origen="bot")
        datos = copia_de(db)
        perderlo_todo(db)
        user_data = {}

        update, _ = _reenviar(datos)
        await bot_restaurar.recibir_copia(update, _contexto(datos, user_data))
        update, consulta = _pulsar("rest:no")
        await bot_restaurar.confirmar(update, _contexto(datos, user_data))

        assert "Cancelado" in consulta.editado
        assert db.query(Apunte).count() == 0

    @pytest.mark.asyncio
    async def test_si_ya_estaba_todo_no_pregunta(self, db):
        crear_apunte(db, USUARIO, "Cambio de grifo 120", origen="bot")
        datos = copia_de(db)

        update, mensaje = _reenviar(datos)
        await bot_restaurar.recibir_copia(update, _contexto(datos, {}))

        texto, botones = mensaje.respuestas[0]
        assert "ya los tienes todos" in texto
        assert botones is None

    @pytest.mark.asyncio
    async def test_un_csv_que_no_es_una_copia_se_explica(self, db):
        datos = "nombre,telefono\nAna,600111222\n".encode("utf-8")

        update, mensaje = _reenviar(datos)
        await bot_restaurar.recibir_copia(update, _contexto(datos, {}))

        assert "No puedo restaurar" in mensaje.respuestas[0][0]
