"""La capa HTTP: que pida token, que devuelva los códigos correctos y que el
navegador pueda leer las respuestas.

Lo de CORS en los errores parece un detalle y no lo es: sin esa cabecera el
navegador bloquea la respuesta y la web no puede enseñar por qué falló un
apunte, aunque el servidor la haya explicado perfectamente.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import crear_api
from app.nucleo.db import sesion
from app.servicios.auth import generar_token
from tests.conftest import USUARIO

ORIGEN_WEB = "http://localhost:5173"


@pytest.fixture
def cliente():
    with TestClient(crear_api()) as c:
        yield c


@pytest.fixture
def cabeceras(db):
    return {"Authorization": f"Bearer {generar_token(db, USUARIO)}"}


def test_salud_no_pide_token(cliente):
    respuesta = cliente.get("/salud")
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "ok"


def test_salud_avisa_de_si_los_datos_persisten(cliente):
    """Existe para detectar el caso en que la base vive dentro del contenedor."""
    datos = cliente.get("/salud").json()["datos"]
    assert "persistente" in datos
    assert "ruta" in datos


@pytest.mark.parametrize(
    "metodo,ruta",
    [
        ("get", "/apuntes"),
        ("post", "/apuntes"),
        ("get", "/clientes"),
        ("get", "/citas"),
        ("get", "/resumen/dia"),
        ("get", "/apuntes/pendientes"),
    ],
)
def test_todo_lo_demas_pide_token(cliente, metodo, ruta):
    assert getattr(cliente, metodo)(ruta).status_code == 401


def test_un_token_inventado_no_vale(cliente):
    respuesta = cliente.get("/apuntes", headers={"Authorization": "Bearer inventado"})
    assert respuesta.status_code == 401


def test_crear_listar_corregir_y_borrar(cliente, cabeceras):
    creado = cliente.post(
        "/apuntes", json={"texto": "Cambio de grifo 1200", "origen": "web"}, headers=cabeceras
    )
    assert creado.status_code == 201
    apunte = creado.json()["apunte"]
    assert apunte["importe"] == "1200.00"

    corregido = cliente.patch(
        f"/apuntes/{apunte['id']}", json={"importe": "120"}, headers=cabeceras
    )
    assert corregido.status_code == 200
    assert corregido.json()["importe"] == "120.00"

    assert cliente.delete(f"/apuntes/{apunte['id']}", headers=cabeceras).status_code == 204
    assert cliente.get("/apuntes", headers=cabeceras).json() == []


def test_borrar_algo_que_no_existe_da_404(cliente, cabeceras):
    assert cliente.delete("/apuntes/999999", headers=cabeceras).status_code == 404


def test_texto_sin_importe_se_guarda_como_nota(cliente, cabeceras):
    """Escribir no cuesta nada, así que tampoco se pierde nada por escribirlo."""
    respuesta = cliente.post(
        "/apuntes",
        json={"texto": "Llamar al fontanero el martes", "origen": "web"},
        headers=cabeceras,
    )
    assert respuesta.status_code == 201
    apunte = respuesta.json()["apunte"]
    assert apunte["tipo"] == "nota"
    assert apunte["importe"] == "0.00"
    assert apunte["concepto"] == "Llamar al fontanero el martes"


def test_un_texto_en_blanco_si_da_422(cliente, cabeceras):
    """Una nota vacía no es nada: eso sí es un error de quien llama."""
    respuesta = cliente.post(
        "/apuntes", json={"texto": "   ", "origen": "web"}, headers=cabeceras
    )
    assert respuesta.status_code == 422


def test_dos_clientes_iguales_se_devuelven_para_preguntar(cliente, cabeceras):
    for nombre in ("Ana Ruiz", "Ana Pérez"):
        cliente.post("/clientes", json={"nombre": nombre}, headers=cabeceras)

    creado = cliente.post(
        "/apuntes", json={"texto": "Cambio de grifo ana 120", "origen": "web"}, headers=cabeceras
    ).json()

    assert creado["apunte"]["cliente_id"] is None
    assert len(creado["candidatos"]) == 2


def test_las_respuestas_llevan_cabecera_cors(cliente, cabeceras):
    respuesta = cliente.get("/apuntes", headers={**cabeceras, "Origin": ORIGEN_WEB})
    assert respuesta.headers.get("access-control-allow-origin") == ORIGEN_WEB


def test_los_errores_tambien_llevan_cabecera_cors(cliente, cabeceras):
    """Sin esto el navegador bloquea la respuesta y la web no puede explicar el fallo."""
    respuesta = cliente.post(
        "/apuntes",
        json={"texto": "   ", "origen": "web"},
        headers={**cabeceras, "Origin": ORIGEN_WEB},
    )
    assert respuesta.status_code == 422
    assert respuesta.headers.get("access-control-allow-origin") == ORIGEN_WEB


def test_un_origen_desconocido_no_recibe_permiso(cliente, cabeceras):
    respuesta = cliente.get(
        "/apuntes", headers={**cabeceras, "Origin": "https://sitio-cualquiera.example"}
    )
    assert "access-control-allow-origin" not in respuesta.headers


def test_el_csv_sale_con_sus_columnas(cliente, cabeceras):
    cliente.post(
        "/apuntes", json={"texto": "Cambio de grifo 120", "origen": "web"}, headers=cabeceras
    )
    hoy = cliente.get("/apuntes", headers=cabeceras).json()[0]["fecha"]

    respuesta = cliente.get(f"/export/csv?desde={hoy}&hasta={hoy}", headers=cabeceras)
    assert respuesta.status_code == 200
    lineas = respuesta.text.strip().splitlines()
    assert lineas[0].startswith("fecha,tipo,concepto,importe")
    assert "Cambio de grifo" in lineas[1]


def test_el_buzon_pide_token(cliente):
    assert cliente.get("/notas").status_code == 401


def test_el_ciclo_entero_de_una_nota(cliente, cabeceras):
    """Crear, editar, agendar: lo que hacen los botones del buzón."""
    creada = cliente.post("/notas", json={"texto": "Revisar el coche"}, headers=cabeceras)
    assert creada.status_code == 201
    nota = creada.json()
    assert nota["concepto"] == "Revisar el coche"

    editada = cliente.patch(
        f"/notas/{nota['id']}", json={"texto": "Revisar el coche y las ruedas"}, headers=cabeceras
    )
    assert editada.json()["concepto"] == "Revisar el coche y las ruedas"

    assert len(cliente.get("/notas", headers=cabeceras).json()) == 1


def test_agendar_una_nota_la_saca_del_buzon(cliente, cabeceras):
    nota = cliente.post("/notas", json={"texto": "Reforma"}, headers=cabeceras).json()

    respuesta = cliente.post(
        f"/notas/{nota['id']}/agendar",
        json={"fecha": "2026-09-09", "fecha_fin": "2026-09-11", "titulo": "Reforma del baño"},
        headers=cabeceras,
    )

    assert respuesta.status_code == 201
    cita = respuesta.json()
    assert (cita["fecha"], cita["fecha_fin"], cita["titulo"]) == (
        "2026-09-09",
        "2026-09-11",
        "Reforma del baño",
    )
    assert cliente.get("/notas", headers=cabeceras).json() == []
    # Y sale el día de en medio, que es lo que se mira en el calendario.
    del_dia = cliente.get("/citas?fecha=2026-09-10", headers=cabeceras).json()
    assert [c["id"] for c in del_dia] == [cita["id"]]


def test_un_rango_al_reves_da_422(cliente, cabeceras):
    nota = cliente.post("/notas", json={"texto": "Reforma"}, headers=cabeceras).json()

    respuesta = cliente.post(
        f"/notas/{nota['id']}/agendar",
        json={"fecha": "2026-09-11", "fecha_fin": "2026-09-09"},
        headers=cabeceras,
    )

    assert respuesta.status_code == 422
    assert len(cliente.get("/notas", headers=cabeceras).json()) == 1


def test_borrar_una_nota_que_no_existe_da_404(cliente, cabeceras):
    assert cliente.delete("/notas/999999", headers=cabeceras).status_code == 404


def test_corregir_una_cita(cliente, cabeceras):
    cita = cliente.post(
        "/citas", json={"fecha": "2026-09-09", "titulo": "Reforma", "hora": "09:00"},
        headers=cabeceras,
    ).json()

    cambiada = cliente.patch(
        f"/citas/{cita['id']}", json={"titulo": "Reforma del baño", "hora": None}, headers=cabeceras
    )

    assert cambiada.status_code == 200
    assert cambiada.json()["titulo"] == "Reforma del baño"
    assert cambiada.json()["hora"] is None


def test_marcar_una_nota_hecha_y_deshacerlo(cliente, cabeceras):
    nota = cliente.post("/notas", json={"texto": "Revisar el coche"}, headers=cabeceras).json()

    hecha = cliente.post(f"/notas/{nota['id']}/hecha", headers=cabeceras)
    assert hecha.status_code == 200
    assert hecha.json()["hecha"] is True

    assert cliente.get("/notas", headers=cabeceras).json() == []
    cumplidas = cliente.get("/notas?hechas=true", headers=cabeceras).json()
    assert [n["id"] for n in cumplidas] == [nota["id"]]

    cliente.post(f"/notas/{nota['id']}/hecha?hecha=false", headers=cabeceras)
    assert len(cliente.get("/notas", headers=cabeceras).json()) == 1
