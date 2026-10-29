"""Pruebas de las consultas de Tutorias a Identidad y a Catalogo (llamadas.py).

Reemplazan llamadas.abrir, la unica salida a la red del modulo: no necesitan
los otros servicios, que en la integracion continua no estan.
"""

import http.client
import io
import json
import urllib.error
import uuid

import pytest
from rest_framework.exceptions import AuthenticationFailed

from . import llamadas
from .llamadas import (
    CuentaInactiva,
    ServicioNoDisponible,
    datos_del_usuario,
    malla_cursada,
)

USUARIO_ID = uuid.uuid4()
CARRERA_ID = uuid.uuid4()
SEDE_ID = uuid.uuid4()
AUTORIZACION = "Bearer token-de-prueba"

PRIMERO = {"id": str(uuid.uuid4()), "sigla": "PGY1101", "nombre": "Programación"}
SEGUNDO = {"id": str(uuid.uuid4()), "sigla": "BDY1101", "nombre": "Base de Datos"}
TERCERO = {
    "id": str(uuid.uuid4()),
    "sigla": "POO1101",
    "nombre": "Orientación a Objetos",
}


def como_bytes(cuerpo):
    return cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo).encode()


class Respuesta(io.BytesIO):
    """Lo que entrega abrir() con un 2xx: se usa con with y trae status."""

    def __init__(self, cuerpo, status=200):
        super().__init__(como_bytes(cuerpo))
        self.status = status


def error_http(codigo, cuerpo):
    """Lo que lanza abrir() con un 4xx o un 5xx."""
    return urllib.error.HTTPError(
        "http://servicio", codigo, "error", {}, io.BytesIO(como_bytes(cuerpo))
    )


class Red:
    """Hace de la red: cada prueba fija la respuesta y ve que se pidio."""

    def __init__(self):
        self.respuesta = None
        self.peticiones = []

    def abrir(self, peticion):
        self.peticiones.append(peticion)
        if isinstance(self.respuesta, BaseException):
            raise self.respuesta
        return self.respuesta


@pytest.fixture
def red(monkeypatch, settings):
    settings.URL_IDENTIDAD = "http://identity:8000"
    settings.URL_CATALOGO = "http://catalog:8000"
    falsa = Red()
    monkeypatch.setattr(llamadas, "abrir", falsa.abrir)
    return falsa


def yo(**cambios):
    """GET /yo de Identidad (cuentas/vistas.py, cuenta_json)."""
    return {
        "id": str(USUARIO_ID),
        "email": "camila.demo@duocuc.cl",
        "nombre": "Camila",
        "apellido": "Soto",
        "carrera_id": str(CARRERA_ID),
        "nivel": 3,
        "sede_id": str(SEDE_ID),
        "es_admin": False,
        **cambios,
    }


def malla(*semestres):
    """GET /carreras/<id>/asignaturas de Catalogo: (semestre, [asignaturas])."""
    return {
        "carrera": {"id": str(CARRERA_ID), "nombre": "Ingeniería en Informática"},
        "malla": {"version": "2024", "vigente_desde": "2024-03-01"},
        "semestres": [
            {"semestre": numero, "asignaturas": asignaturas}
            for numero, asignaturas in semestres
        ],
    }


# ---------------------------------------------------------------- Identidad


def test_pide_yo_a_identidad_con_el_token_de_la_peticion(red):
    red.respuesta = Respuesta(yo())

    datos = datos_del_usuario(AUTORIZACION)

    # El correo no se toma (RNF-07): Tutorias no lo guarda.
    assert datos == {
        "id": USUARIO_ID,
        "nombre": "Camila",
        "apellido": "Soto",
        "carrera_id": CARRERA_ID,
        "sede_id": SEDE_ID,
        "nivel": 3,
    }
    [peticion] = red.peticiones
    assert peticion.full_url == "http://identity:8000/api/identity/v1/yo"
    assert peticion.get_method() == "GET"
    assert peticion.get_header("Authorization") == AUTORIZACION
    assert peticion.get_header("Accept") == "application/json"


def test_un_perfil_incompleto_llega_sin_carrera_sin_sede_y_sin_nivel(red):
    red.respuesta = Respuesta(yo(carrera_id=None, sede_id=None, nivel=None))

    datos = datos_del_usuario(AUTORIZACION)

    assert (datos["carrera_id"], datos["sede_id"], datos["nivel"]) == (None, None, None)


def test_una_cuenta_que_identidad_no_reconoce_responde_403(red):
    red.respuesta = error_http(
        401,
        {
            "codigo": "cuenta_inactiva",
            "mensaje": "La cuenta no existe o está desactivada.",
            "detalles": None,
        },
    )

    with pytest.raises(CuentaInactiva) as error:
        datos_del_usuario(AUTORIZACION)

    assert error.value.status_code == 403
    assert error.value.detail.code == "cuenta_inactiva"


def test_un_token_que_vence_entre_medio_responde_401_para_renovar(red):
    red.respuesta = error_http(
        401,
        {"codigo": "token_vencido", "mensaje": "El token de acceso venció."},
    )

    with pytest.raises(AuthenticationFailed) as error:
        datos_del_usuario(AUTORIZACION)

    assert error.value.detail.code == "token_vencido"


FALLAS = {
    "error_500": error_http(500, b"<h1>Server Error (500)</h1>"),
    "error_503": error_http(503, {"codigo": "x", "mensaje": "x", "detalles": None}),
    "ruta_que_no_existe": error_http(404, b"<!DOCTYPE html><title>Not Found</title>"),
    "otro_401": error_http(401, {"codigo": "token_invalido", "mensaje": "x"}),
    "no_conecta": urllib.error.URLError(ConnectionRefusedError(111, "refused")),
    "no_conecta_a_tiempo": urllib.error.URLError(TimeoutError("timed out")),
    "no_contesta_a_tiempo": TimeoutError("timed out"),
    "corta_la_conexion": ConnectionResetError(104, "reset"),
    "corta_la_respuesta": http.client.RemoteDisconnected("closed"),
    "no_es_json": Respuesta(b"<html>gateway</html>"),
    "otra_forma": Respuesta(["Camila"]),
}


@pytest.mark.parametrize("falla", list(FALLAS.values()), ids=list(FALLAS))
def test_si_identidad_falla_responde_503(red, falla):
    red.respuesta = falla

    with pytest.raises(ServicioNoDisponible) as error:
        datos_del_usuario(AUTORIZACION)

    assert error.value.status_code == 503
    assert error.value.detail.code == "servicio_no_disponible"
    assert "servicio de Identidad" in str(error.value.detail)


@pytest.mark.parametrize(
    "cambios",
    [{"id": "no-es-un-uuid"}, {"nombre": None}, {"carrera_id": "x"}],
    ids=["id", "nombre", "carrera"],
)
def test_una_respuesta_de_identidad_con_otra_forma_responde_503(red, cambios):
    red.respuesta = Respuesta(yo(**cambios))

    with pytest.raises(ServicioNoDisponible):
        datos_del_usuario(AUTORIZACION)


# ---------------------------------------------------------------- Catalogo


def test_la_malla_cursada_trae_las_asignaturas_hasta_ese_semestre(red):
    red.respuesta = Respuesta(malla((1, [PRIMERO]), (2, [SEGUNDO]), (3, [TERCERO])))

    habilitadas = malla_cursada(CARRERA_ID, 2)

    assert habilitadas == {
        uuid.UUID(PRIMERO["id"]): {
            "sigla": "PGY1101",
            "nombre": "Programación",
            "semestre": 1,
        },
        uuid.UUID(SEGUNDO["id"]): {
            "sigla": "BDY1101",
            "nombre": "Base de Datos",
            "semestre": 2,
        },
    }
    [peticion] = red.peticiones
    assert peticion.full_url == (
        f"http://catalog:8000/api/catalog/v1/carreras/{CARRERA_ID}/asignaturas"
    )
    # La malla es publica: a Catalogo no se le manda el token.
    assert peticion.get_header("Authorization") is None


def test_en_primer_semestre_no_hay_malla_cursada_ni_llamada(red):
    assert malla_cursada(CARRERA_ID, 0) == {}
    assert red.peticiones == []


def test_una_carrera_sin_malla_vigente_no_habilita_ninguna(red):
    red.respuesta = Respuesta({**malla(), "malla": None})

    assert malla_cursada(CARRERA_ID, 4) == {}


def test_una_carrera_que_catalogo_no_tiene_devuelve_none(red):
    red.respuesta = error_http(
        404,
        {
            "codigo": "not_found",
            "mensaje": "No existe una carrera activa con ese identificador.",
            "detalles": None,
        },
    )

    assert malla_cursada(CARRERA_ID, 2) is None


@pytest.mark.parametrize(
    "falla",
    [
        error_http(500, b"<h1>Server Error (500)</h1>"),
        error_http(404, b"<!DOCTYPE html><title>Not Found</title>"),
        urllib.error.URLError(TimeoutError("timed out")),
        TimeoutError("timed out"),
        Respuesta(b"no es json"),
        Respuesta({"semestres": [{"semestre": "1", "asignaturas": [PRIMERO]}]}),
        Respuesta({"semestres": [{"semestre": 1, "asignaturas": [{"id": "x"}]}]}),
    ],
    ids=[
        "error_500",
        "ruta_que_no_existe",
        "no_conecta_a_tiempo",
        "no_contesta_a_tiempo",
        "no_es_json",
        "semestre_como_texto",
        "asignatura_sin_datos",
    ],
)
def test_si_catalogo_falla_responde_503(red, falla):
    red.respuesta = falla

    with pytest.raises(ServicioNoDisponible) as error:
        malla_cursada(CARRERA_ID, 2)

    assert "servicio de Catálogo" in str(error.value.detail)
