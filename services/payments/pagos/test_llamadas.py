"""Pruebas de las llamadas de Pagos a Tutorias (llamadas.py, HU-23).

Reemplazan llamadas.abrir, la unica salida a la red del modulo: no necesitan
Tutorias, que en la integracion continua no esta. Respuesta, error_http y Red
son los de tutorias/test_llamadas.py. Cada falla se arma con una funcion,
para que cada caso lea su propia respuesta.
"""

import http.client
import io
import json
import urllib.error
import uuid
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from . import llamadas
from .llamadas import (
    AVISADO,
    RESERVA_CANCELADA,
    SIN_AVISO,
    ServicioNoDisponible,
    informar_estado,
    reserva,
)

RESERVA_ID = uuid.uuid4()
SOLICITANTE_ID = uuid.uuid4()
TUTOR_ID = uuid.uuid4()
CLAVE = "clave-de-prueba"
INSTANTE = datetime(2026, 11, 8, 15, 30, 0, 123456, tzinfo=UTC)


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
    # En la integracion continua CLAVE_SERVICIO no existe: se fija aqui.
    settings.URL_TUTORIAS = "http://tutoring:8000"
    settings.CLAVE_SERVICIO = CLAVE
    falsa = Red()
    monkeypatch.setattr(llamadas, "abrir", falsa.abrir)
    return falsa


def reserva_interna(**cambios):
    """GET /internal/reservas/<id> de Tutorias (tutorias/internas.py)."""
    return {
        "id": str(RESERVA_ID),
        "estado": "CONFIRMADA",
        "monto": 5000,
        "estado_pago": None,
        "pago_actualizado_en": None,
        "solicitante_usuario_id": str(SOLICITANTE_ID),
        "tutor_usuario_id": str(TUTOR_ID),
        **cambios,
    }


def error_de_tutorias(estado, codigo):
    return error_http(estado, {"codigo": codigo, "mensaje": "x", "detalles": None})


# ---------------------------------------------------------------- reserva()


@pytest.mark.parametrize("estado_pago", [None, "PAGADO"])
def test_reserva_con_200_devuelve_el_diccionario_con_sus_tipos(red, estado_pago):
    red.respuesta = Respuesta(reserva_interna(estado_pago=estado_pago))

    datos = reserva(RESERVA_ID)

    assert datos == {
        "id": RESERVA_ID,
        "solicitante_usuario_id": SOLICITANTE_ID,
        "tutor_usuario_id": TUTOR_ID,
        "estado": "CONFIRMADA",
        "monto": 5000,
        "estado_pago": estado_pago,
    }
    [peticion] = red.peticiones
    assert peticion.full_url == (
        f"http://tutoring:8000/api/tutoring/v1/internal/reservas/{RESERVA_ID}"
    )
    assert peticion.get_method() == "GET"
    assert peticion.get_header("X-clave-servicio") == CLAVE
    assert peticion.get_header("Accept") == "application/json"
    # Pagos no manda el token del usuario a Tutorias.
    assert peticion.get_header("Authorization") is None


def test_reserva_que_no_existe_devuelve_none(red):
    red.respuesta = error_de_tutorias(404, "reserva_no_encontrada")

    assert reserva(RESERVA_ID) is None


@pytest.mark.parametrize(
    "fabrica",
    [
        lambda: error_de_tutorias(404, "ruta_no_encontrada"),
        lambda: error_http(404, b"<!DOCTYPE html><title>Not Found</title>"),
    ],
    ids=["ruta_no_encontrada", "html_404"],
)
def test_reserva_404_sin_codigo_conocido_lanza_503_y_pide_revisar_la_clave(
    red, fabrica, caplog
):
    red.respuesta = fabrica()

    with pytest.raises(ServicioNoDisponible) as error:
        reserva(RESERVA_ID)

    assert error.value.status_code == 503
    assert "404 sin código conocido desde Tutorías: revisa CLAVE_SERVICIO" in (
        caplog.text
    )


FALLAS_DE_RESERVA = {
    "error_500": lambda: error_http(500, b"<h1>Server Error (500)</h1>"),
    "error_503": lambda: error_de_tutorias(503, "x"),
    "otro_error": lambda: error_de_tutorias(400, "x"),
    "no_conecta": lambda: urllib.error.URLError(ConnectionRefusedError(111, "x")),
    "no_conecta_a_tiempo": lambda: urllib.error.URLError(TimeoutError("timed out")),
    "no_contesta_a_tiempo": lambda: TimeoutError("timed out"),
    "corta_la_conexion": lambda: ConnectionResetError(104, "reset"),
    "corta_la_respuesta": lambda: http.client.RemoteDisconnected("closed"),
    "no_es_json": lambda: Respuesta(b"<html>gateway</html>"),
    "otra_forma": lambda: Respuesta(["CONFIRMADA"]),
    "monto_true": lambda: Respuesta(reserva_interna(monto=True)),
    "monto_texto": lambda: Respuesta(reserva_interna(monto="5000")),
    "id_no_uuid": lambda: Respuesta(reserva_interna(id="no-es-uuid")),
    "sin_tutor": lambda: Respuesta(reserva_interna(tutor_usuario_id=None)),
    "estado_no_texto": lambda: Respuesta(reserva_interna(estado=1)),
}


@pytest.mark.parametrize(
    "fabrica", list(FALLAS_DE_RESERVA.values()), ids=list(FALLAS_DE_RESERVA)
)
def test_si_tutorias_falla_reserva_lanza_503(red, fabrica):
    red.respuesta = fabrica()

    with pytest.raises(ServicioNoDisponible) as error:
        reserva(RESERVA_ID)

    assert error.value.status_code == 503
    assert error.value.detail.code == "servicio_no_disponible"
    assert "servicio de Tutorías" in str(error.value.detail)


# ---------------------------------------------------------- informar_estado()


def pago(estado="PAGADO", actualizado_en=INSTANTE):
    """Lo que informar_estado lee de un Pago."""
    return SimpleNamespace(
        reserva_id=RESERVA_ID, estado=estado, actualizado_en=actualizado_en
    )


def test_informar_estado_hace_un_patch_con_el_cuerpo_json_y_la_clave(red, caplog):
    red.respuesta = Respuesta({"aplicado": True, "estado_pago": "PAGADO"})

    assert informar_estado(pago()) == AVISADO

    [peticion] = red.peticiones
    assert peticion.full_url == (
        "http://tutoring:8000/api/tutoring/v1/internal/reservas/"
        f"{RESERVA_ID}/estado-pago"
    )
    assert peticion.get_method() == "PATCH"
    assert json.loads(peticion.data) == {
        "estado_pago": "PAGADO",
        "actualizado_en": "2026-11-08T15:30:00.123456Z",
    }
    assert peticion.get_header("Content-type") == "application/json"
    assert peticion.get_header("X-clave-servicio") == CLAVE
    assert peticion.get_header("Authorization") is None
    assert [r for r in caplog.records if r.name == llamadas.__name__] == []


def test_informar_estado_manda_el_instante_en_utc_con_microsegundos(red):
    red.respuesta = Respuesta({"aplicado": True, "estado_pago": "PENDIENTE"})
    chile = timezone(timedelta(hours=-3))

    informar_estado(pago("PENDIENTE", datetime(2026, 11, 8, 12, 30, tzinfo=chile)))

    [peticion] = red.peticiones
    assert json.loads(peticion.data)["actualizado_en"] == "2026-11-08T15:30:00.000000Z"


def test_un_aviso_que_tutorias_ya_tenia_tambien_es_avisado(red):
    # aplicado false: Tutorias ya tiene un aviso mas nuevo (A-06).
    red.respuesta = Respuesta({"aplicado": False, "estado_pago": "PAGADO"})

    assert informar_estado(pago("PENDIENTE")) == AVISADO


def test_un_409_reserva_cancelada_devuelve_reserva_cancelada(red):
    red.respuesta = error_de_tutorias(409, "reserva_cancelada")

    assert informar_estado(pago()) == RESERVA_CANCELADA


FALLAS_DEL_AVISO = {
    "ruta_no_encontrada": lambda: error_de_tutorias(404, "ruta_no_encontrada"),
    "html_404": lambda: error_http(404, b"<!DOCTYPE html><title>Not Found</title>"),
    "sin_pago": lambda: error_de_tutorias(409, "sin_pago"),
    "otro_400": lambda: error_de_tutorias(400, "estado_pago_invalido"),
    "error_500": lambda: error_http(500, b"<h1>Server Error (500)</h1>"),
    "no_conecta": lambda: urllib.error.URLError(ConnectionRefusedError(111, "x")),
    "no_conecta_a_tiempo": lambda: urllib.error.URLError(TimeoutError("timed out")),
    "no_contesta_a_tiempo": lambda: TimeoutError("timed out"),
    "corta_la_conexion": lambda: ConnectionResetError(104, "reset"),
    "inesperado": lambda: RuntimeError("algo que nadie espera"),
}


@pytest.mark.parametrize(
    "fabrica", list(FALLAS_DEL_AVISO.values()), ids=list(FALLAS_DEL_AVISO)
)
def test_si_el_aviso_no_sale_devuelve_sin_aviso_sin_lanzar_y_lo_deja_en_el_log(
    red, fabrica, caplog
):
    red.respuesta = fabrica()

    assert informar_estado(pago()) == SIN_AVISO

    avisos = [r.getMessage() for r in caplog.records if r.name == llamadas.__name__]
    assert any(
        "No salió el aviso PAGADO" in linea and str(RESERVA_ID) in linea
        for linea in avisos
    )
