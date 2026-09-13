"""Los hábitos contra la base de datos y por HTTP.

Las rachas en sí se prueban en `test_habitos_reglas.py`. Aquí, lo que puede
romperse al guardar: que marcar dos veces cuente doble, que se pueda marcar
el futuro, que un recordatorio se mande tarde o dos veces, o que llegue a
quien apagó los avisos.

El día de hoy se fija con `hoy`: los hábitos dependen del día de la semana,
y un test que pasa el martes y falla el sábado no sirve de nada.
"""
from datetime import date, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient

from app.dominio.habitos import HECHO, DiasNoValidos
from app.dominio.models import HabitoHecho
from app.main import crear_api
from app.servicios import habitos as servicio
from app.servicios.auth import generar_token
from app.servicios.avisos import activar_avisos
from app.servicios.habitos import DiaNoMarcable, HabitoNoEncontrado
from tests.conftest import USUARIO

OTRO = 111222333
MIERCOLES = date(2026, 9, 9)
SABADO = date(2026, 9, 12)
TODOS = list(range(7))
LABORABLES = [0, 1, 2, 3, 4]


@pytest.fixture
def hoy(monkeypatch):
    reloj = {"hoy": MIERCOLES}
    monkeypatch.setattr(servicio, "hoy_local", lambda: reloj["hoy"])
    return reloj


class TestCrearYMarcar:
    def test_marcar_hoy(self, db, hoy):
        habito = servicio.crear(db, USUARIO, "Beber agua", TODOS)

        resumen = servicio.marcar(db, USUARIO, habito.id)

        assert (resumen.hecho_hoy, resumen.racha) == (True, 1)
        assert resumen.semana[2].estado == HECHO, "el miércoles es el tercer círculo"

    def test_marcar_dos_veces_no_cuenta_doble(self, db, hoy):
        habito = servicio.crear(db, USUARIO, "Beber agua", TODOS)

        servicio.marcar(db, USUARIO, habito.id)
        resumen = servicio.marcar(db, USUARIO, habito.id)

        assert resumen.racha == 1
        assert db.query(HabitoHecho).count() == 1

    def test_desmarcar(self, db, hoy):
        habito = servicio.crear(db, USUARIO, "Beber agua", TODOS)
        servicio.marcar(db, USUARIO, habito.id)

        resumen = servicio.marcar(db, USUARIO, habito.id, hecho=False)

        assert (resumen.hecho_hoy, resumen.racha) == (False, 0)

    def test_el_futuro_no_se_marca(self, db, hoy):
        habito = servicio.crear(db, USUARIO, "Beber agua", TODOS)
        with pytest.raises(DiaNoMarcable):
            servicio.marcar(db, USUARIO, habito.id, MIERCOLES + timedelta(days=1))

    def test_un_dia_que_no_toca_no_se_marca(self, db, hoy):
        habito = servicio.crear(db, USUARIO, "Entrenar", LABORABLES)
        with pytest.raises(DiaNoMarcable):
            servicio.marcar(db, USUARIO, habito.id, date(2026, 9, 5))  # sábado

    def test_los_dias_de_antes_de_crearlo_tambien_cuentan(self, db, hoy):
        """'Llevo toda la semana bebiendo agua': se marca y la racha lo refleja."""
        habito = servicio.crear(db, USUARIO, "Beber agua", TODOS)

        servicio.marcar(db, USUARIO, habito.id, MIERCOLES - timedelta(days=2))
        resumen = servicio.marcar(db, USUARIO, habito.id, MIERCOLES - timedelta(days=1))

        assert resumen.racha == 2, "lunes y martes; hoy aún está a tiempo"

    def test_al_dia_siguiente_la_racha_sigue_viva(self, db, hoy):
        habito = servicio.crear(db, USUARIO, "Beber agua", TODOS)
        servicio.marcar(db, USUARIO, habito.id)

        hoy["hoy"] = MIERCOLES + timedelta(days=1)
        [resumen] = servicio.listar(db, USUARIO)

        assert (resumen.racha, resumen.toca_hoy, resumen.hecho_hoy) == (1, True, False)

    def test_sin_nombre_o_sin_dias_no_hay_habito(self, db, hoy):
        with pytest.raises(ValueError):
            servicio.crear(db, USUARIO, "   ", TODOS)
        with pytest.raises(DiasNoValidos):
            servicio.crear(db, USUARIO, "Beber agua", [])

    def test_no_se_toca_el_habito_de_otro(self, db, hoy):
        habito = servicio.crear(db, USUARIO, "Beber agua", TODOS)
        with pytest.raises(HabitoNoEncontrado):
            servicio.marcar(db, OTRO, habito.id)
        assert servicio.listar(db, OTRO) == []


class TestDetalle:
    def test_rachas_cumplimiento_y_calendario(self, db, hoy):
        habito = servicio.crear(db, USUARIO, "Beber agua", TODOS)
        for atras in (2, 1, 0):
            servicio.marcar(db, USUARIO, habito.id, MIERCOLES - timedelta(days=atras))

        detalle = servicio.detalle(db, USUARIO, habito.id)

        assert (detalle.racha, detalle.mejor_racha) == (3, 3)
        assert (detalle.cumplidos, detalle.programados, detalle.porcentaje) == (3, 3, 100)
        assert len(detalle.dias_del_mes) == 30
        assert detalle.dias_del_mes[8].estado == HECHO, "el día 9"


class TestEditarYBorrar:
    def test_cambiar_la_hora_vuelve_a_permitir_el_recordatorio_de_hoy(self, db, hoy):
        """Avisado a las 9 y cambiado a las 18: a las 18 tiene que llegar."""
        habito = servicio.crear(db, USUARIO, "Beber agua", TODOS, time(9, 0))
        servicio.marcar_recordado(db, habito, MIERCOLES)

        servicio.editar(db, USUARIO, habito.id, recordar_a=time(18, 0))

        db.refresh(habito)
        assert habito.recordado_el is None

    def test_tocar_otra_cosa_no_reinicia_el_recordatorio(self, db, hoy):
        habito = servicio.crear(db, USUARIO, "Beber agua", TODOS, time(9, 0))
        servicio.marcar_recordado(db, habito, MIERCOLES)

        servicio.editar(db, USUARIO, habito.id, nombre="Beber más agua")

        db.refresh(habito)
        assert habito.recordado_el == MIERCOLES

    def test_borrar_se_lleva_su_historial(self, db, hoy):
        habito = servicio.crear(db, USUARIO, "Beber agua", TODOS)
        servicio.marcar(db, USUARIO, habito.id)

        servicio.borrar(db, USUARIO, habito.id)

        assert servicio.listar(db, USUARIO) == []
        assert db.query(HabitoHecho).count() == 0


def _a_las(dia: date, horas: int, minutos: int) -> datetime:
    return datetime.combine(dia, time(horas, minutos))


class TestRecordatorios:
    def test_llega_a_su_hora(self, db, hoy):
        habito = servicio.crear(db, USUARIO, "Beber agua", TODOS, time(12, 0))
        assert servicio.recordatorios_debidos(db, _a_las(MIERCOLES, 12, 5)) == [habito]

    def test_ni_antes_ni_media_hora_tarde(self, db, hoy):
        """Un recordatorio tarde es ruido: tras una caída, mejor no mandarlo."""
        servicio.crear(db, USUARIO, "Beber agua", TODOS, time(12, 0))

        assert servicio.recordatorios_debidos(db, _a_las(MIERCOLES, 11, 59)) == []
        assert len(servicio.recordatorios_debidos(db, _a_las(MIERCOLES, 12, 29))) == 1
        assert servicio.recordatorios_debidos(db, _a_las(MIERCOLES, 12, 30)) == []

    def test_si_ya_esta_hecho_no_molesta(self, db, hoy):
        habito = servicio.crear(db, USUARIO, "Beber agua", TODOS, time(12, 0))
        servicio.marcar(db, USUARIO, habito.id)

        assert servicio.recordatorios_debidos(db, _a_las(MIERCOLES, 12, 5)) == []

    def test_una_vez_al_dia(self, db, hoy):
        habito = servicio.crear(db, USUARIO, "Beber agua", TODOS, time(12, 0))
        servicio.marcar_recordado(db, habito, MIERCOLES)

        assert servicio.recordatorios_debidos(db, _a_las(MIERCOLES, 12, 6)) == []

    def test_el_dia_que_no_toca_no_llega(self, db, hoy):
        servicio.crear(db, USUARIO, "Entrenar", LABORABLES, time(12, 0))
        assert servicio.recordatorios_debidos(db, _a_las(SABADO, 12, 5)) == []

    def test_con_los_avisos_apagados_no_llega(self, db, hoy):
        """/avisos off es para todo, recordatorios incluidos."""
        servicio.crear(db, USUARIO, "Beber agua", TODOS, time(12, 0))
        activar_avisos(db, USUARIO, False)

        assert servicio.recordatorios_debidos(db, _a_las(MIERCOLES, 12, 5)) == []

    def test_sin_hora_no_hay_recordatorio(self, db, hoy):
        servicio.crear(db, USUARIO, "Beber agua", TODOS)
        assert servicio.recordatorios_debidos(db, _a_las(MIERCOLES, 12, 5)) == []


@pytest.fixture
def cliente():
    with TestClient(crear_api()) as c:
        yield c


@pytest.fixture
def cabeceras(db):
    return {"Authorization": f"Bearer {generar_token(db, USUARIO)}"}


class TestPorHttp:
    def test_pide_token(self, cliente):
        assert cliente.get("/habitos").status_code == 401

    def test_el_ciclo_entero(self, cliente, cabeceras, hoy):
        creado = cliente.post(
            "/habitos",
            json={"nombre": "Beber agua", "dias": TODOS, "recordar_a": "08:30"},
            headers=cabeceras,
        )
        assert creado.status_code == 201
        cuerpo = creado.json()
        assert cuerpo["habito"]["dias"] == TODOS
        assert cuerpo["habito"]["recordar_a"] == "08:30:00"
        assert len(cuerpo["semana"]) == 7
        habito_id = cuerpo["habito"]["id"]

        marcado = cliente.post(f"/habitos/{habito_id}/dias", json={}, headers=cabeceras)
        assert marcado.json()["hecho_hoy"] is True

        detalle = cliente.get(f"/habitos/{habito_id}", headers=cabeceras).json()
        assert detalle["porcentaje"] == 100
        assert len(detalle["dias_del_mes"]) == 30

        sin_hora = cliente.patch(
            f"/habitos/{habito_id}", json={"recordar_a": None}, headers=cabeceras
        )
        assert sin_hora.json()["habito"]["recordar_a"] is None

        assert cliente.delete(f"/habitos/{habito_id}", headers=cabeceras).status_code == 204
        assert cliente.get("/habitos", headers=cabeceras).json() == []

    def test_errores_con_su_codigo(self, cliente, cabeceras, hoy):
        sin_dias = cliente.post(
            "/habitos", json={"nombre": "Beber agua", "dias": []}, headers=cabeceras
        )
        assert sin_dias.status_code == 422

        assert cliente.post("/habitos/999999/dias", json={}, headers=cabeceras).status_code == 404

        habito_id = cliente.post(
            "/habitos", json={"nombre": "Beber agua", "dias": TODOS}, headers=cabeceras
        ).json()["habito"]["id"]
        futuro = cliente.post(
            f"/habitos/{habito_id}/dias", json={"fecha": "2026-09-10"}, headers=cabeceras
        )
        assert futuro.status_code == 422
