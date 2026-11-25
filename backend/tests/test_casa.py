"""Casa: gastos compartidos, lista de la compra, invitaciones y recetas.

Lo que se rompería en silencio: un gasto de casa que se cuela en las cuentas
del negocio, alguien que ve la casa de otro, una invitación que vale dos
veces, "2 kilos de tomates" anotado como 2 €, o una lista que repite lo que
ya estaba.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.dominio import casa as reglas
from app.main import crear_api
from app.nucleo import recetas as cocina
from app.nucleo.tiempo import hoy_local
from app.servicios import casa
from app.servicios.auth import generar_token
from app.servicios.resumen import resumen_mes
from tests.conftest import USUARIO

OTRO = 111222333
HOY = date(2026, 11, 24)


@pytest.fixture
def c():
    with TestClient(crear_api()) as cliente:
        yield cliente


@pytest.fixture
def cab(db):
    return {"Authorization": f"Bearer {generar_token(db, USUARIO)}"}


# --- Reglas -----------------------------------------------------------------


@pytest.mark.parametrize("texto,concepto,importe", [
    ("-45 súper", "Súper", "45"),
    ("súper 45", "Súper", "45"),  # en casa no se cobra: sin guion también es gasto
    ("pagué 60 de luz", "Luz", "60"),
    ("he pagado 120 euros de luz", "Luz", "120"),
    ("ayer 12,50 farmacia", "Farmacia", "12.50"),
    ("gasto de 30 en gasolina", "Gasolina", "30"),
])
def test_entiende_gastos(texto, concepto, importe):
    leido = reglas.interpretar_gasto(texto, HOY)
    assert leido.concepto == concepto and leido.importe == Decimal(importe)


@pytest.mark.parametrize("texto", ["leche", "2 kilos de tomates", "comprar 6 huevos", "1 litro de aceite", "pan y 3 latas de atún"])
def test_una_cantidad_no_es_dinero(texto):
    assert reglas.interpretar_gasto(texto, HOY) is None


def test_la_fecha_delante_vale():
    assert reglas.interpretar_gasto("ayer 12,50 farmacia", HOY).fecha == HOY - timedelta(days=1)


def test_parte_la_lista():
    assert reglas.articulos_de("comprar leche, huevos y pan") == ["Leche", "Huevos", "Pan"]
    assert reglas.articulos_de("añade tomates a la lista") == ["Tomates"]
    assert reglas.articulos_de("leche\nLeche\npan") == ["Leche", "Pan"]
    assert reglas.es_para_la_lista("comprar pan") and not reglas.es_para_la_lista("pan")


def test_categorias():
    assert reglas.categoria_de("Mercadona") == "Súper"
    assert reglas.categoria_de("Luz noviembre") == "Facturas"
    assert reglas.categoria_de("Farmacia") == "Salud"
    assert reglas.categoria_de("cosas varias") == "Otros"


def test_coincide_con_el_ticket():
    assert reglas.coincide("Leche", "LECHE ENTERA HACENDADO 6X1L")
    assert reglas.coincide("Tomates", "TOMATE PERA KG")
    assert not reglas.coincide("Leche de avena", "LECHE ENTERA")


# --- La casa y quién entra --------------------------------------------------


def test_la_casa_aparece_sola_y_su_creador_es_titular(db):
    yo = casa.asegurar_casa(db, USUARIO, "Yoa")
    assert yo.titular and casa.asegurar_casa(db, USUARIO).id == yo.id
    assert not casa.solo_casa(db, USUARIO)


def test_invitacion_vale_una_vez(db):
    codigo = casa.crear_invitacion(db, USUARIO)
    ella = casa.unirse(db, codigo.lower(), OTRO, "María")
    assert not ella.titular and casa.solo_casa(db, OTRO)
    assert ella.hogar_id == casa.miembro_de(db, USUARIO).hogar_id
    with pytest.raises(casa.InvitacionNoValida):
        casa.unirse(db, codigo, 999, "Otra")


def test_solo_el_titular_invita(db):
    casa.unirse(db, casa.crear_invitacion(db, USUARIO), OTRO, "María")
    with pytest.raises(casa.SoloTitular):
        casa.crear_invitacion(db, OTRO)


def test_al_entrar_se_trae_lo_que_ya_habia_anotado(db):
    casa.crear_gasto(db, OTRO, "Farmacia", Decimal("8"))
    casa.anadir(db, OTRO, ["Pan"])
    casa.unirse(db, casa.crear_invitacion(db, USUARIO), OTRO, "María")
    assert [g.concepto for g in casa.listar_gastos(db, USUARIO, HOY - timedelta(days=400), hoy_local())] == ["Farmacia"]
    assert [a.texto for a in casa.listar_articulos(db, USUARIO)] == ["Pan"]


def test_quien_ya_comparte_casa_no_se_mueve(db):
    casa.unirse(db, casa.crear_invitacion(db, USUARIO), OTRO, "María")
    otra = casa.crear_invitacion(db, 555)
    with pytest.raises(casa.YaEnOtraCasa):
        casa.unirse(db, otra, OTRO, "María")


# --- Gastos -----------------------------------------------------------------


def test_un_gasto_de_casa_no_toca_el_negocio(db):
    hoy = hoy_local()
    antes = resumen_mes(db, USUARIO, hoy.year, hoy.month)
    casa.anotar_texto(db, USUARIO, "-80 mercadona")
    despues = resumen_mes(db, USUARIO, hoy.year, hoy.month)
    assert despues.gastos == antes.gastos and despues.neto == antes.neto


def test_resumen_por_persona_y_categoria(db):
    casa.unirse(db, casa.crear_invitacion(db, USUARIO), OTRO, "María")
    casa.anotar_texto(db, USUARIO, "-80 mercadona")
    casa.anotar_texto(db, OTRO, "farmacia 12,50")
    casa.anotar_texto(db, OTRO, "-20 lidl")
    r = casa.resumen(db, USUARIO, hoy_local().replace(day=1), hoy_local())
    assert r.total == Decimal("112.50")
    assert {p.nombre: p.total for p in r.por_categoria} == {"Súper": Decimal("100"), "Salud": Decimal("12.50")}
    personas = {p.nombre: p.total for p in r.por_persona}
    assert personas["María"] == Decimal("32.50")


def test_no_se_ve_la_casa_de_otro(db):
    g = casa.crear_gasto(db, USUARIO, "Luz", Decimal("60"))
    casa.asegurar_casa(db, 555)
    with pytest.raises(casa.NoEncontrado):
        casa.borrar_gasto(db, 555, g.id)
    assert casa.listar_gastos(db, 555, date(2000, 1, 1), hoy_local()) == []


def test_fecha_futura_no(db):
    with pytest.raises(casa.DatoNoValido):
        casa.crear_gasto(db, USUARIO, "Luz", Decimal("60"), hoy_local() + timedelta(days=1))


# --- Lista ------------------------------------------------------------------


def test_lo_que_se_acaba_vuelve_a_la_lista_sin_repetirse(db):
    leche, = casa.anadir(db, USUARIO, ["Leche"])
    assert len(casa.anadir(db, USUARIO, ["leche"])) == 1
    assert len(casa.listar_articulos(db, USUARIO)) == 1
    casa.marcar(db, USUARIO, leche.id, True)
    casa.anadir(db, USUARIO, ["Leche"])  # se acabó: vuelve a faltar
    unico, = casa.listar_articulos(db, USUARIO)
    assert unico.id == leche.id and not unico.hay


def test_el_ticket_tacha_lo_comprado(db):
    casa.anadir(db, USUARIO, ["Leche", "Tomates", "Pilas"])
    tachados = casa.tachar_comprado(db, USUARIO, ["LECHE ENTERA 1L", "TOMATE PERA"])
    assert sorted(a.texto for a in tachados) == ["Leche", "Tomates"]


# --- API --------------------------------------------------------------------


def test_api_casa_de_punta_a_punta(c, cab, db):
    yo = c.get("/casa", headers=cab).json()
    assert yo["yo"]["titular"] and not yo["solo_casa"] and "Súper" in yo["categorias"]

    codigo = c.post("/casa/invitacion", headers=cab).json()["codigo"]
    vista = c.get(f"/casa/invitacion/{codigo}")  # sin token: quien llega aún no tiene
    assert vista.status_code == 200
    token = c.post("/casa/unirse", json={"codigo": codigo, "nombre": "María"}).json()["token"]
    ella = {"Authorization": f"Bearer {token}"}
    suya = c.get("/casa", headers=ella).json()
    assert suya["solo_casa"] and suya["yo"]["user_id"] < 0 and len(suya["miembros"]) == 2
    assert c.post("/casa/unirse", json={"codigo": codigo, "nombre": "Otra"}).status_code == 422

    r = c.post("/casa/gastos/texto", headers=ella, json={"texto": "-45,5 mercadona"})
    assert r.status_code == 201 and r.json()["importe"] == "45.50" and r.json()["categoria"] == "Súper"
    assert c.post("/casa/gastos/texto", headers=ella, json={"texto": "leche"}).status_code == 422
    hoy = hoy_local().isoformat()
    lista = c.get(f"/casa/gastos?desde={hoy}&hasta={hoy}", headers=cab).json()
    assert len(lista) == 1  # lo de ella lo ve él
    gid = lista[0]["id"]
    assert c.patch(f"/casa/gastos/{gid}", headers=cab, json={"categoria": "Casa"}).json()["categoria"] == "Casa"
    res = c.get(f"/casa/resumen?desde={hoy}&hasta={hoy}", headers=cab).json()
    assert res["total"] == "45.50"

    arts = c.post("/casa/lista", headers=ella, json={"texto": "leche, huevos y pan"}).json()
    assert [a["texto"] for a in arts] == ["Leche", "Huevos", "Pan"]
    assert c.patch(f"/casa/lista/{arts[0]['id']}", headers=cab, json={"hay": True}).json()["hay"]
    assert c.delete(f"/casa/lista/{arts[1]['id']}", headers=cab).status_code == 204
    assert len(c.get("/casa/lista", headers=ella).json()) == 2
    assert c.delete(f"/casa/gastos/{gid}", headers=ella).status_code == 204


def test_api_recetas(c, cab, db, monkeypatch):
    async def falsas(ingredientes, preferencias=""):
        assert "Huevos" in ingredientes
        return cocina.limpiar({"recetas": [{"nombre": "Tortilla", "minutos": "20", "usa": ["Huevos"], "pasos": ["Batir", "Cuajar"]}, {"nombre": "Sin pasos"}]})

    monkeypatch.setattr(cocina, "pedir_recetas", falsas)
    assert c.post("/casa/recetas", headers=cab, json={}).status_code == 422  # sin nada no hay qué pensar
    huevos, = c.post("/casa/lista", headers=cab, json={"texto": "huevos"}).json()
    c.patch(f"/casa/lista/{huevos['id']}", headers=cab, json={"hay": True})
    recetas = c.post("/casa/recetas", headers=cab, json={"preferencias": "rápido"}).json()
    assert [r["nombre"] for r in recetas] == ["Tortilla"] and recetas[0]["minutos"] == 20


@pytest.mark.parametrize("texto,importe", [("45 súper", "45"), ("ayer 30 farmacia", "30"), ("casa -45 súper", None)])
def test_el_importe_delante(texto, importe):
    leido = reglas.interpretar_gasto(texto, HOY)
    if importe is None:
        _, resto = reglas.quitar_prefijo_casa(texto)
        assert reglas.interpretar_gasto(resto, HOY).importe == Decimal("45")
    else:
        assert leido.importe == Decimal(importe)


def test_seis_huevos_es_para_la_lista():
    assert reglas.interpretar_gasto("6 huevos", HOY) is None


class TestVolverPorLaWeb:
    """Quien entró solo por la web y cierra sesión vuelve siendo la misma persona.

    Antes, con otra invitación entraba alguien nuevo: salía dos veces en
    Personas y lo que había anotado se quedaba con la ficha vieja.
    """

    def _entra(self, c, cab, **cuerpo):
        codigo = c.post("/casa/invitacion", headers=cab).json()["codigo"]
        return codigo, c.post("/casa/unirse", json={"codigo": codigo, **cuerpo})

    def test_eligiendo_su_nombre_en_la_lista(self, c, cab, db):
        _, r = self._entra(c, cab, nombre="María")
        antes = c.get("/casa", headers={"Authorization": f"Bearer {r.json()['token']}"}).json()["yo"]

        codigo = c.post("/casa/invitacion", headers=cab).json()["codigo"]
        vista = c.get(f"/casa/invitacion/{codigo}").json()
        assert [p["nombre"] for p in vista["volver"]] == ["María"], "el titular no sale: no entra así"
        r = c.post("/casa/unirse", json={"codigo": codigo, "miembro_id": vista["volver"][0]["id"]})

        despues = c.get("/casa", headers={"Authorization": f"Bearer {r.json()['token']}"}).json()
        assert despues["yo"]["user_id"] == antes["user_id"]
        assert len(despues["miembros"]) == 2, "no sale dos veces en Personas"

    def test_escribiendo_el_mismo_nombre(self, c, cab, db):
        _, r = self._entra(c, cab, nombre="María")
        suyo = c.get("/casa", headers={"Authorization": f"Bearer {r.json()['token']}"}).json()["yo"]["user_id"]

        _, r = self._entra(c, cab, nombre="  maria ")

        yo = c.get("/casa", headers={"Authorization": f"Bearer {r.json()['token']}"}).json()
        assert yo["yo"]["user_id"] == suyo and len(yo["miembros"]) == 2

    def test_la_invitacion_se_gasta_igual(self, c, cab, db):
        codigo, _ = self._entra(c, cab, nombre="María")
        r = c.post("/casa/unirse", json={"codigo": codigo, "nombre": "María"})
        assert r.status_code == 422

    def test_nadie_se_hace_pasar_por_el_titular(self, c, cab, db):
        yo = c.get("/casa", headers=cab).json()["yo"]
        codigo = c.post("/casa/invitacion", headers=cab).json()["codigo"]
        r = c.post("/casa/unirse", json={"codigo": codigo, "miembro_id": yo["id"]})
        assert r.status_code == 422

    def test_quien_usa_telegram_no_vuelve_asi(self, c, cab, db):
        codigo = casa.crear_invitacion(db, USUARIO)
        tg = casa.unirse(db, codigo, 777888999, "Marta")
        codigo = c.post("/casa/invitacion", headers=cab).json()["codigo"]
        assert c.get(f"/casa/invitacion/{codigo}").json()["volver"] == []
        r = c.post("/casa/unirse", json={"codigo": codigo, "miembro_id": tg.id})
        assert r.status_code == 422
