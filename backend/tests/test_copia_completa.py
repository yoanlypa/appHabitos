"""La copia de seguridad completa: el ZIP con todo, y su vuelta.

Lo que se prueba es lo que solo se descubre el día que hace falta: que algo
no vaya en la copia, que vuelva suelto de su trabajo o su cliente, que
restaurar dos veces duplique, que la vista previa escriba en la base o diga
otra cosa que lo que luego pasa, y que la copia del domingo no salga por no
haber anotado nada ese día.

La copia de partida sale siempre de `generar()`, lo mismo que manda el bot.
"""
import io
import json
import zipfile
from datetime import date, time, timedelta
from decimal import Decimal

import pytest

from app.bot import copias
from app.bot import restaurar as bot_restaurar
from app.dominio import copia_completa as dominio
from app.dominio.copia_csv import CopiaNoValida, decodificar, leer_copia
from app.dominio.models import (
    Ajuste,
    Apunte,
    ArticuloCompra,
    Cita,
    Cliente,
    EmisorPropio,
    Factura,
    GastoCasa,
    Habito,
    HabitoHecho,
    Hogar,
    InvitacionHogar,
    MiembroHogar,
    MovimientoCartera,
    TokenAcceso,
    Trabajo,
)
from app.nucleo.tiempo import hoy_local
from app.servicios import casa
from app.servicios import habitos as servicio_habitos
from app.servicios.agenda import crear_cita
from app.servicios.apuntes import crear_apunte, crear_movimiento, crear_nota, marcar_cobrado
from app.servicios.clientes import crear_cliente
from app.servicios.copia_completa import generar, planificar, restaurar, usuarios_con_datos
from app.servicios.restauracion import restaurar as restaurar_csv
from app.servicios.trabajos import crear_trabajo
from tests.conftest import USUARIO

ESPOSA = 777888999
HOY = hoy_local()
AYER = HOY - timedelta(days=1)

_TODO = (
    MovimientoCartera, GastoCasa, ArticuloCompra, InvitacionHogar, MiembroHogar, Hogar,
    EmisorPropio, Factura, HabitoHecho, Habito, Apunte, Cita, Trabajo, Cliente, Ajuste, TokenAcceso,
)


def perderlo_todo(db) -> None:
    """Como en Railway sin volumen: la base vuelve a estar vacía."""
    for modelo in _TODO:
        db.query(modelo).delete()
    db.commit()


def cuantos(db) -> dict:
    return {modelo.__tablename__: db.query(modelo).count() for modelo in _TODO}


def un_poco_de_todo(db):
    """Un mes cualquiera de Yoa, con los enlaces que más duele perder."""
    ana = crear_cliente(db, USUARIO, "Ana Ruiz", telefono="600111222")
    obra = crear_trabajo(db, USUARIO, "Reforma baño", cliente_id=ana.id, fecha_inicio=AYER, facturado=True)
    cobro = crear_movimiento(db, USUARIO, "trabajo", "Reforma baño", Decimal("980.50"), AYER, True, "web", trabajo_id=obra.id)
    cobro.cliente_id = ana.id
    crear_movimiento(db, USUARIO, "gasto", "azulejos", Decimal("120"), AYER, False, "web", trabajo_id=obra.id)
    crear_apunte(db, USUARIO, "-45 gasolina", origen="bot")
    crear_nota(db, USUARIO, "llamar al fontanero", origen="bot")
    crear_cita(db, USUARIO, HOY + timedelta(days=2), "Rematar baño", hora=time(10, 0), cliente_id=ana.id, trabajo_id=obra.id)
    correr = servicio_habitos.crear(db, USUARIO, "Correr", [0, 1, 2, 3, 4, 5, 6])
    servicio_habitos.marcar(db, USUARIO, correr.id, HOY)
    db.add(Ajuste(user_id=USUARIO, avisos_activos=True, correo="yoa@example.com"))
    db.add(EmisorPropio(user_id=USUARIO, nif="X0000000T", nombre="Yoa", iban="ES00 1234"))
    casa.asegurar_casa(db, USUARIO, "Yoa")
    casa.crear_gasto(db, USUARIO, "Mercadona", Decimal("62.30"), fecha=AYER, efectivo=True)
    casa.meter_en_cartera(db, USUARIO, Decimal("200"), fecha=AYER)
    casa.anadir(db, USUARIO, ["leche", "huevos"])
    db.commit()
    return obra


def zip_de(db, user_id=USUARIO) -> bytes:
    resultado = generar(db, user_id)
    assert resultado is not None
    return resultado[0]


class TestLaCopia:
    def test_lleva_el_json_y_el_csv_de_siempre(self, db):
        un_poco_de_todo(db)
        datos = zip_de(db)

        with zipfile.ZipFile(io.BytesIO(datos)) as z:
            assert set(z.namelist()) == {"copia.json", "apuntes.csv"}
            csv = z.read("apuntes.csv")
        assert csv.startswith(b"\xef\xbb\xbf"), "sin BOM, Excel rompe las tildes"
        # El CSV de dentro sigue valiendo para restaurar por el camino antiguo.
        filas = leer_copia(decodificar(csv))
        assert len(filas) == 4

    def test_no_lleva_tokens_de_la_web(self, db):
        """Un ZIP reenviado por despiste no puede abrir la cuenta de nadie."""
        un_poco_de_todo(db)
        db.add(TokenAcceso(user_id=USUARIO, token="secreto-de-verdad"))
        db.commit()
        with zipfile.ZipFile(io.BytesIO(zip_de(db))) as z:
            assert b"secreto-de-verdad" not in z.read("copia.json")

    def test_sin_nada_no_hay_copia(self, db):
        assert generar(db, USUARIO) is None

    def test_quien_solo_usa_casa_tambien_tiene_copia(self, db):
        casa.crear_gasto(db, ESPOSA, "Farmacia", Decimal("12.50"))
        assert generar(db, ESPOSA) is not None


class TestIdaYVuelta:
    def test_vuelve_todo_y_con_sus_enlaces(self, db):
        un_poco_de_todo(db)
        datos = zip_de(db)
        antes = cuantos(db)
        perderlo_todo(db)

        restaurar(db, USUARIO, dominio.leer(datos))

        despues = cuantos(db)
        assert despues == antes
        obra = db.query(Trabajo).one()
        assert obra.facturado and obra.cliente.nombre == "Ana Ruiz"
        assert {a.concepto for a in obra.apuntes} == {"Reforma baño", "azulejos"}, "vuelven dentro de su obra"
        cobro = next(a for a in obra.apuntes if a.tipo == "trabajo")
        assert cobro.pendiente and cobro.importe == Decimal("980.50")
        assert cobro.cliente.nombre == "Ana Ruiz"
        cita = db.query(Cita).one()
        assert cita.trabajo_id == obra.id and cita.hora == time(10, 0)
        assert [h.fecha for h in db.query(HabitoHecho)] == [HOY]
        assert db.query(Ajuste).one().correo == "yoa@example.com"
        gasto = db.query(GastoCasa).one()
        assert gasto.efectivo and gasto.importe == Decimal("62.30")
        assert db.query(MiembroHogar).one().titular
        assert {a.texto for a in db.query(ArticuloCompra)} == {"Leche", "Huevos"}

    def test_restaurar_dos_veces_no_duplica(self, db):
        un_poco_de_todo(db)
        datos = zip_de(db)
        antes = cuantos(db)

        plan = restaurar(db, USUARIO, dominio.leer(datos))

        assert not plan.hay_algo
        assert cuantos(db) == antes

    def test_la_vista_previa_no_escribe_y_dice_lo_mismo_que_pasa(self, db):
        un_poco_de_todo(db)
        datos = zip_de(db)
        perderlo_todo(db)
        copia = dominio.leer(datos)

        previa = planificar(db, USUARIO, copia)
        assert sum(cuantos(db).values()) == 0, "enseñar no puede escribir nada"

        hecho = restaurar(db, USUARIO, copia)
        assert dict(previa.nuevos) == dict(hecho.nuevos)

    def test_dos_gastos_iguales_el_mismo_dia_son_dos(self, db):
        crear_apunte(db, USUARIO, "-45 gasolina", origen="bot")
        crear_apunte(db, USUARIO, "-45 gasolina", origen="bot")
        datos = zip_de(db)
        db.query(Apunte).filter(Apunte.id == db.query(Apunte).first().id).delete()
        db.commit()

        plan = restaurar(db, USUARIO, dominio.leer(datos))

        assert plan.nuevos == {"apuntes": 1}
        assert db.query(Apunte).count() == 2

    def test_lo_cobrado_despues_no_vuelve_a_ser_deuda(self, db):
        apunte = crear_apunte(db, USUARIO, "pendiente Cocina 300", origen="bot")
        datos = zip_de(db)
        marcar_cobrado(db, USUARIO, apunte.id)

        restaurar(db, USUARIO, dominio.leer(datos))

        assert db.query(Apunte).one().pendiente is False

    def test_lo_restaurado_del_csv_vuelve_a_su_trabajo(self, db):
        """El caso de antes: restaurar el CSV devolvía los apuntes sueltos."""
        un_poco_de_todo(db)
        datos = zip_de(db)
        with zipfile.ZipFile(io.BytesIO(datos)) as z:
            csv = z.read("apuntes.csv")
        perderlo_todo(db)
        restaurar_csv(db, USUARIO, leer_copia(decodificar(csv)))
        assert db.query(Apunte).filter(Apunte.trabajo_id.isnot(None)).count() == 0

        plan = restaurar(db, USUARIO, dominio.leer(datos))

        assert "apuntes" not in plan.nuevos, "ya estaban: no se duplican"
        assert plan.reenlazados == 2
        obra = db.query(Trabajo).one()
        assert {a.concepto for a in obra.apuntes} == {"Reforma baño", "azulejos"}

    def test_un_apunte_metido_en_otro_trabajo_se_queda_donde_esta(self, db):
        """Rellenar huecos sí; mover lo que ya está colocado, no."""
        obra = un_poco_de_todo(db)
        datos = zip_de(db)
        otra = crear_trabajo(db, USUARIO, "Cocina")
        azulejos = db.query(Apunte).filter(Apunte.concepto == "azulejos").one()
        azulejos.trabajo_id = otra.id
        db.commit()

        restaurar(db, USUARIO, dominio.leer(datos))

        db.refresh(azulejos)
        assert azulejos.trabajo_id == otra.id != obra.id

    def test_un_cobro_con_su_factura_sigue_yendo_a_la_gestoria(self, db):
        """La foto no vuelve; sin la marca, el cobro saldría del parte."""
        cobro = crear_apunte(db, USUARIO, "Instalación 500", origen="bot")
        db.add(Factura(user_id=USUARIO, apunte_id=cobro.id, ruta="x.pdf", mime="application/pdf", tamano=1, emitida=True))
        db.commit()
        db.refresh(cobro)
        assert cobro.gestoria
        datos = zip_de(db)
        perderlo_todo(db)

        restaurar(db, USUARIO, dominio.leer(datos))

        assert db.query(Apunte).one().gestoria

    def test_casa_vuelve_con_las_dos_personas_y_la_cartera_enlazada(self, db):
        casa.asegurar_casa(db, USUARIO, "Yoa")
        codigo = casa.crear_invitacion(db, USUARIO)
        casa.unirse(db, codigo, ESPOSA, "Marta")
        casa.crear_gasto(db, ESPOSA, "Farmacia", Decimal("12.50"), fecha=AYER, efectivo=True)
        casa.contar_cartera(db, ESPOSA, Decimal("100"))
        datos = zip_de(db)
        perderlo_todo(db)

        restaurar(db, USUARIO, dominio.leer(datos))

        miembros = {m.user_id: m for m in db.query(MiembroHogar)}
        assert miembros[USUARIO].titular and not miembros[ESPOSA].titular
        assert miembros[ESPOSA].hogar_id == miembros[USUARIO].hogar_id
        assert db.query(GastoCasa).one().user_id == ESPOSA, "sigue diciendo quién pagó"
        assert db.query(MovimientoCartera).one().user_id == ESPOSA

    def test_la_copia_de_casa_de_ella_no_la_hace_titular(self, db):
        casa.asegurar_casa(db, USUARIO, "Yoa")
        casa.unirse(db, casa.crear_invitacion(db, USUARIO), ESPOSA, "Marta")
        casa.crear_gasto(db, ESPOSA, "Farmacia", Decimal("12.50"))
        datos = zip_de(db, ESPOSA)
        perderlo_todo(db)

        restaurar(db, ESPOSA, dominio.leer(datos))

        miembros = {m.user_id: m for m in db.query(MiembroHogar)}
        assert miembros[USUARIO].titular and not miembros[ESPOSA].titular


class TestLeer:
    def test_una_ficha_mala_no_deja_restaurar_a_medias(self, db):
        un_poco_de_todo(db)
        datos = zip_de(db)
        with zipfile.ZipFile(io.BytesIO(datos)) as z:
            contenido = json.loads(z.read("copia.json"))
        contenido["apuntes"][1]["importe"] = "doce"
        salida = io.BytesIO()
        with zipfile.ZipFile(salida, "w") as z:
            z.writestr("copia.json", json.dumps(contenido))

        with pytest.raises(CopiaNoValida, match="apuntes nº 2"):
            dominio.leer(salida.getvalue())

    def test_un_zip_cualquiera_no_es_una_copia(self):
        salida = io.BytesIO()
        with zipfile.ZipFile(salida, "w") as z:
            z.writestr("fotos.txt", "hola")
        with pytest.raises(CopiaNoValida, match="no es una de mis copias"):
            dominio.leer(salida.getvalue())

    def test_una_copia_de_una_version_mas_nueva_no_se_lee_a_ciegas(self):
        salida = io.BytesIO()
        with zipfile.ZipFile(salida, "w") as z:
            z.writestr("copia.json", json.dumps({"formato": "parte-del-dia", "version": 99}))
        with pytest.raises(CopiaNoValida, match="versión más nueva"):
            dominio.leer(salida.getvalue())

    def test_tres_decimales_no_se_redondean_en_silencio(self, db):
        crear_apunte(db, USUARIO, "Trabajo 100", origen="bot")
        with zipfile.ZipFile(io.BytesIO(zip_de(db))) as z:
            contenido = json.loads(z.read("copia.json"))
        contenido["apuntes"][0]["importe"] = "100.005"
        salida = io.BytesIO()
        with zipfile.ZipFile(salida, "w") as z:
            z.writestr("copia.json", json.dumps(contenido))
        with pytest.raises(CopiaNoValida, match="dos decimales"):
            dominio.leer(salida.getvalue())


class TestElDomingo:
    def test_sale_aunque_no_se_haya_anotado_nada_ese_dia(self, db):
        """Antes solo la recibía quien tenía aviso esa noche."""
        crear_movimiento(db, USUARIO, "trabajo", "Pintura", Decimal("300"), HOY - timedelta(days=10), False, "web")
        assert USUARIO in usuarios_con_datos(db)

    def test_no_se_manda_a_quien_entro_solo_por_la_web(self, db):
        casa.crear_gasto(db, -5, "Pan", Decimal("1.20"))
        assert -5 not in usuarios_con_datos(db)


# --- Por el bot ---------------------------------------------------------------


class _Bot:
    def __init__(self, datos=b""):
        self.datos = datos
        self.enviados = []

    async def send_document(self, chat_id, document, caption=None):
        self.enviados.append({"chat_id": chat_id, "nombre": document.name, "datos": document.getvalue(), "caption": caption})

    async def get_file(self, file_id):
        datos = self.datos

        class _Fichero:
            async def download_as_bytearray(self):
                return bytearray(datos)

        return _Fichero()


class _Mensaje:
    def __init__(self, tamano):
        self.document = type("D", (), {"file_id": "x", "file_size": tamano})()
        self.respuestas = []

    async def reply_text(self, texto, reply_markup=None):
        self.respuestas.append((texto, reply_markup))


class _Consulta:
    def __init__(self, data):
        self.data = data
        self.from_user = type("Usuario", (), {"id": USUARIO})()
        self.editado = None

    async def answer(self):
        pass

    async def edit_message_text(self, texto):
        self.editado = texto


def _contexto(bot, user_data):
    return type("C", (), {"bot": bot, "user_data": user_data})()


def _reenviar(datos, user_id=USUARIO):
    mensaje = _Mensaje(len(datos))
    usuario = type("Usuario", (), {"id": user_id})()
    return type("U", (), {"message": mensaje, "effective_user": usuario})(), mensaje


class TestPorElBot:
    @pytest.mark.asyncio
    async def test_el_bot_manda_el_zip_y_dice_lo_que_lleva(self, db):
        un_poco_de_todo(db)
        bot = _Bot()
        assert await copias.enviar_copia(_contexto(bot, {}), USUARIO) is True

        enviado = bot.enviados[0]
        assert enviado["nombre"].endswith(".zip")
        assert "1 trabajo" in enviado["caption"] and "1 cliente" in enviado["caption"]
        assert dominio.leer(enviado["datos"]).trabajos[0]["titulo"] == "Reforma baño"

    @pytest.mark.asyncio
    async def test_primero_enseña_y_solo_restaura_al_confirmar(self, db):
        un_poco_de_todo(db)
        datos = zip_de(db)
        perderlo_todo(db)
        user_data = {}

        update, mensaje = _reenviar(datos)
        await bot_restaurar.recibir_copia_completa(update, _contexto(_Bot(datos), user_data))

        texto, botones = mensaje.respuestas[0]
        assert "4 apuntes" in texto and "1 trabajo\n" in texto
        assert botones is not None
        assert sum(cuantos(db).values()) == 0, "enseñar no puede escribir nada"

        consulta = _Consulta("restc:si")
        await bot_restaurar.confirmar_completa(
            type("U", (), {"callback_query": consulta})(), _contexto(_Bot(datos), user_data)
        )
        assert "Restaurado" in consulta.editado
        assert db.query(Trabajo).count() == 1

        # Un segundo toque no restaura dos veces.
        consulta = _Consulta("restc:si")
        await bot_restaurar.confirmar_completa(
            type("U", (), {"callback_query": consulta})(), _contexto(_Bot(datos), user_data)
        )
        assert "Ya no tengo esa copia" in consulta.editado

    @pytest.mark.asyncio
    async def test_la_copia_de_otra_cuenta_se_avisa(self, db):
        crear_apunte(db, ESPOSA, "Trabajo 100", origen="bot")
        datos = zip_de(db, ESPOSA)

        update, mensaje = _reenviar(datos, USUARIO)
        await bot_restaurar.recibir_copia_completa(update, _contexto(_Bot(datos), {}))

        assert "OTRA cuenta" in mensaje.respuestas[0][0]

    @pytest.mark.asyncio
    async def test_un_zip_roto_se_explica(self, db):
        datos = b"PK\x03\x04 esto no es un zip"
        update, mensaje = _reenviar(datos)
        await bot_restaurar.recibir_copia_completa(update, _contexto(_Bot(datos), {}))
        assert "No puedo restaurar" in mensaje.respuestas[0][0]


class TestPorLaWeb:
    def test_se_descarga_la_misma_copia(self, db):
        from fastapi.testclient import TestClient

        from app.main import crear_api
        from app.servicios.auth import generar_token

        cabeceras = {"Authorization": f"Bearer {generar_token(db, USUARIO)}"}
        with TestClient(crear_api()) as cliente:
            assert cliente.get("/export/copia", headers=cabeceras).status_code == 204
            un_poco_de_todo(db)
            respuesta = cliente.get("/export/copia", headers=cabeceras)

        assert respuesta.status_code == 200
        assert respuesta.headers["content-type"] == "application/zip"
        assert "attachment" in respuesta.headers["content-disposition"]
        assert dominio.leer(respuesta.content).trabajos[0]["titulo"] == "Reforma baño"
