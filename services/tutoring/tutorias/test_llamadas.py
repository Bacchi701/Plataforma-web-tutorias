"""Pruebas de las consultas de Tutorias a otros servicios (llamadas.py).

Identidad, Catalogo y, desde HU-28, el reembolso a Pagos. Reemplazan
llamadas.abrir, la unica salida a la red del modulo: no necesitan los otros
servicios, que en la integracion continua no estan.
"""

import http.client
import io
import json
import logging
import urllib.error
import uuid

import pytest
from rest_framework.exceptions import AuthenticationFailed

from . import llamadas
from .llamadas import (
    CuentaInactiva,
    ServicioNoDisponible,
    _pedir,
    datos_del_usuario,
    malla_cursada,
    usuario_por_id,
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
    """Hace de la red: cada prueba fija la respuesta y ve que se pidio.

    Para las pruebas de varias peticiones, respuestas es una cola: abrir
    entrega (o lanza) la primera. Vacia, usa respuesta, como antes.
    """

    def __init__(self):
        self.respuesta = None
        self.respuestas = []
        self.peticiones = []

    def abrir(self, peticion):
        self.peticiones.append(peticion)
        respuesta = self.respuestas.pop(0) if self.respuestas else self.respuesta
        if isinstance(respuesta, BaseException):
            raise respuesta
        return respuesta


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


# ---------------------------------------------------- Llamadas internas (F1)


def usuario_interno(**cambios):
    return {
        "id": str(USUARIO_ID),
        "nombre": "Camila",
        "apellido": "Soto",
        "carrera_id": str(CARRERA_ID),
        "nivel": 3,
        "sede_id": str(SEDE_ID),
        "activo": True,
        **cambios,
    }


def test_pedir_con_post_hacia_ruta_interna_agrega_clave_y_cuerpo_json(red, settings):
    settings.CLAVE_SERVICIO = "clave-secreta-interna"
    red.respuesta = Respuesta({"ok": True}, status=200)

    url = "http://identity:8000/api/identity/v1/internal/avisos"
    cuerpo = {"destinatario": "test@duocuc.cl"}
    estado, respuesta = _pedir("Identidad", url, metodo="POST", cuerpo=cuerpo)

    assert estado == 200
    assert respuesta == {"ok": True}
    [peticion] = red.peticiones
    assert peticion.full_url == url
    assert peticion.get_method() == "POST"
    assert peticion.data == json.dumps(cuerpo).encode("utf-8")
    assert peticion.get_header("Content-type") == "application/json"
    assert peticion.get_header("Accept") == "application/json"
    assert peticion.get_header("X-clave-servicio") == "clave-secreta-interna"


def test_pedir_2xx_sin_cuerpo_devuelve_none(red, settings):
    settings.CLAVE_SERVICIO = "clave-secreta-interna"
    red.respuesta = Respuesta(b"", status=204)

    url = "http://identity:8000/api/identity/v1/internal/accion"
    estado, respuesta = _pedir("Identidad", url, metodo="POST")

    assert estado == 204
    assert respuesta is None


def test_rutas_publicas_no_llevan_clave_de_servicio(red, settings):
    settings.CLAVE_SERVICIO = "clave-secreta-interna"
    red.respuesta = Respuesta(yo())

    datos_del_usuario(AUTORIZACION)

    [peticion_yo] = red.peticiones
    assert peticion_yo.get_header("X-clave-servicio") is None

    red.peticiones.clear()
    red.respuesta = Respuesta(malla((1, [PRIMERO])))

    malla_cursada(CARRERA_ID, 1)

    [peticion_malla] = red.peticiones
    assert peticion_malla.get_header("X-clave-servicio") is None


def test_clave_de_servicio_se_lee_en_cada_llamada(red, settings):
    settings.CLAVE_SERVICIO = "primera-clave"
    red.respuesta = Respuesta({"ok": 1})
    _pedir("Identidad", "http://identity:8000/api/identity/v1/internal/test")
    assert red.peticiones[0].get_header("X-clave-servicio") == "primera-clave"

    settings.CLAVE_SERVICIO = "segunda-clave"
    red.respuesta = Respuesta({"ok": 2})
    _pedir("Identidad", "http://identity:8000/api/identity/v1/internal/test")
    assert red.peticiones[1].get_header("X-clave-servicio") == "segunda-clave"


def test_usuario_por_id_con_200_devuelve_diccionario_completo(red, settings):
    settings.CLAVE_SERVICIO = "clave-de-prueba"
    red.respuesta = Respuesta(usuario_interno())

    datos = usuario_por_id(USUARIO_ID)

    assert datos == {
        "id": USUARIO_ID,
        "nombre": "Camila",
        "apellido": "Soto",
        "carrera_id": CARRERA_ID,
        "nivel": 3,
        "sede_id": SEDE_ID,
        "activo": True,
    }
    [peticion] = red.peticiones
    assert peticion.full_url == (
        f"http://identity:8000/api/identity/v1/internal/usuarios/{USUARIO_ID}"
    )
    assert peticion.get_header("X-clave-servicio") == "clave-de-prueba"
    assert peticion.get_header("Authorization") is None


def test_usuario_por_id_cuenta_desactivada_llega_con_activo_false(red, settings):
    settings.CLAVE_SERVICIO = "clave-de-prueba"
    red.respuesta = Respuesta(usuario_interno(activo=False))

    datos = usuario_por_id(USUARIO_ID)

    assert datos["activo"] is False


def test_usuario_por_id_inexistente_devuelve_none(red, settings):
    settings.CLAVE_SERVICIO = "clave-de-prueba"
    red.respuesta = error_http(
        404,
        {
            "codigo": "usuario_no_encontrado",
            "mensaje": "El usuario no existe.",
            "detalles": None,
        },
    )

    resultado = usuario_por_id(USUARIO_ID)

    assert resultado is None


@pytest.mark.parametrize(
    "falla_404",
    [
        error_http(404, {"codigo": "ruta_no_encontrada", "mensaje": "x"}),
        error_http(404, b"<!DOCTYPE html><title>Not Found</title>"),
    ],
    ids=["ruta_no_encontrada", "html_404"],
)
def test_usuario_por_id_404_sin_codigo_conocido_lanza_503_y_loguea_revisa_clave(
    red, settings, falla_404, caplog
):
    settings.CLAVE_SERVICIO = "clave-de-prueba"
    red.respuesta = falla_404

    with pytest.raises(ServicioNoDisponible) as error:
        usuario_por_id(USUARIO_ID)

    assert error.value.status_code == 503
    assert "revisa CLAVE_SERVICIO" in caplog.text


FALLAS_USUARIO_POR_ID = {
    "error_500": error_http(500, b"<h1>Server Error (500)</h1>"),
    "error_503": error_http(503, {"codigo": "x", "mensaje": "x"}),
    "no_conecta_a_tiempo": urllib.error.URLError(TimeoutError("timed out")),
    "no_contesta_a_tiempo": TimeoutError("timed out"),
    "corta_la_conexion": ConnectionResetError(104, "reset"),
    "no_es_json": Respuesta(b"<html>gateway</html>"),
    "otra_forma_id": Respuesta(usuario_interno(id="no-es-uuid")),
    "otra_forma_activo": Respuesta(usuario_interno(activo="si")),
}


@pytest.mark.parametrize(
    "falla",
    list(FALLAS_USUARIO_POR_ID.values()),
    ids=list(FALLAS_USUARIO_POR_ID),
)
def test_usuario_por_id_fallas_lanzan_503_con_mensaje_identidad(red, settings, falla):
    settings.CLAVE_SERVICIO = "clave-de-prueba"
    red.respuesta = falla

    with pytest.raises(ServicioNoDisponible) as error:
        usuario_por_id(USUARIO_ID)

    assert error.value.status_code == 503
    assert "servicio de Identidad" in str(error.value.detail)


# ----------------------------------------- Varios usuarios y asignaturas (HU-19)

OTRO_ID = uuid.uuid4()
ASIGNATURAS = "http://catalog:8000/api/catalog/v1/asignaturas?paginado=1&limite=200"


def test_usuarios_por_ids_pide_la_ruta_interna_con_los_ids_y_la_clave(red, settings):
    settings.CLAVE_SERVICIO = "clave-de-prueba"
    diego = usuario_interno(
        id=str(OTRO_ID),
        nombre="Diego",
        carrera_id=None,
        nivel=None,
        sede_id=None,
        activo=False,
    )
    red.respuesta = Respuesta([usuario_interno(), diego])

    datos = llamadas.usuarios_por_ids([USUARIO_ID, OTRO_ID])

    assert datos == {
        USUARIO_ID: {
            "id": USUARIO_ID,
            "nombre": "Camila",
            "apellido": "Soto",
            "carrera_id": CARRERA_ID,
            "nivel": 3,
            "sede_id": SEDE_ID,
            "activo": True,
        },
        OTRO_ID: {
            "id": OTRO_ID,
            "nombre": "Diego",
            "apellido": "Soto",
            "carrera_id": None,
            "nivel": None,
            "sede_id": None,
            "activo": False,
        },
    }
    [peticion] = red.peticiones
    assert peticion.full_url == (
        "http://identity:8000/api/identity/v1/internal/usuarios"
        f"?ids={USUARIO_ID},{OTRO_ID}"
    )
    assert peticion.get_method() == "GET"
    assert peticion.get_header("X-clave-servicio") == "clave-de-prueba"
    assert peticion.get_header("Authorization") is None


def test_usuarios_por_ids_con_una_lista_vacia_devuelve_vacio(red, settings):
    settings.CLAVE_SERVICIO = "clave-de-prueba"
    red.respuesta = Respuesta([])

    assert llamadas.usuarios_por_ids([USUARIO_ID]) == {}
    assert len(red.peticiones) == 1


def test_usuarios_por_ids_sin_ids_no_llama_a_identidad(red):
    assert llamadas.usuarios_por_ids([]) == {}
    assert red.peticiones == []


@pytest.mark.parametrize(
    "falla_404",
    [
        error_http(404, {"codigo": "ruta_no_encontrada", "mensaje": "x"}),
        error_http(404, {"codigo": "usuario_no_encontrado", "mensaje": "x"}),
        error_http(404, b"<!DOCTYPE html><title>Not Found</title>"),
    ],
    ids=["ruta_no_encontrada", "usuario_no_encontrado", "html_404"],
)
def test_usuarios_por_ids_con_404_lanza_503_y_loguea_revisa_clave(
    red, settings, falla_404, caplog
):
    settings.CLAVE_SERVICIO = "clave-de-prueba"
    red.respuesta = falla_404

    with pytest.raises(ServicioNoDisponible) as error:
        llamadas.usuarios_por_ids([USUARIO_ID])

    assert error.value.status_code == 503
    assert "servicio de Identidad" in str(error.value.detail)
    assert "revisa CLAVE_SERVICIO" in caplog.text


FALLAS_USUARIOS_POR_IDS = {
    "error_500": error_http(500, b"<h1>Server Error (500)</h1>"),
    "error_400": error_http(400, {"codigo": "ids_invalidos", "mensaje": "x"}),
    "no_conecta": urllib.error.URLError(ConnectionRefusedError(111, "refused")),
    "no_contesta_a_tiempo": TimeoutError("timed out"),
    "no_es_una_lista": Respuesta(usuario_interno()),
    "otra_forma_activo": Respuesta([usuario_interno(activo="si")]),
    "otra_forma_id": Respuesta([usuario_interno(), usuario_interno(id="x")]),
}


@pytest.mark.parametrize(
    "falla",
    list(FALLAS_USUARIOS_POR_IDS.values()),
    ids=list(FALLAS_USUARIOS_POR_IDS),
)
def test_usuarios_por_ids_si_identidad_falla_responde_503(red, settings, falla):
    settings.CLAVE_SERVICIO = "clave-de-prueba"
    red.respuesta = falla

    with pytest.raises(ServicioNoDisponible) as error:
        llamadas.usuarios_por_ids([USUARIO_ID])

    assert error.value.status_code == 503
    assert "servicio de Identidad" in str(error.value.detail)


def pagina(numero, total_paginas, *asignaturas, total=None):
    """GET /asignaturas?paginado=1 de Catalogo (catalogo/vistas.py)."""
    return {
        "total": len(asignaturas) if total is None else total,
        "pagina": numero,
        "total_paginas": total_paginas,
        "limite": 200,
        "resultados": [
            {**asignatura, "area": "", "creditos": 6} for asignatura in asignaturas
        ],
    }


def test_asignaturas_del_catalogo_pide_las_paginas_y_las_junta(red, settings):
    settings.CLAVE_SERVICIO = "clave-de-prueba"
    red.respuestas = [
        Respuesta(pagina(1, 2, PRIMERO, SEGUNDO, total=3)),
        Respuesta(pagina(2, 2, TERCERO, total=3)),
    ]

    asignaturas = llamadas.asignaturas_del_catalogo()

    assert asignaturas == {
        uuid.UUID(PRIMERO["id"]): {"sigla": "PGY1101", "nombre": "Programación"},
        uuid.UUID(SEGUNDO["id"]): {"sigla": "BDY1101", "nombre": "Base de Datos"},
        uuid.UUID(TERCERO["id"]): {
            "sigla": "POO1101",
            "nombre": "Orientación a Objetos",
        },
    }
    assert [peticion.full_url for peticion in red.peticiones] == [
        f"{ASIGNATURAS}&pagina=1",
        f"{ASIGNATURAS}&pagina=2",
    ]
    # Es la ruta publica de Catalogo: no lleva la clave de servicio.
    for peticion in red.peticiones:
        assert peticion.get_header("X-clave-servicio") is None
        assert peticion.get_method() == "GET"


def test_asignaturas_del_catalogo_lee_hasta_50_paginas(red):
    red.respuestas = [Respuesta(pagina(numero, 60)) for numero in range(1, 61)]
    red.respuestas[0] = Respuesta(pagina(1, 60, PRIMERO))

    asignaturas = llamadas.asignaturas_del_catalogo()

    assert len(red.peticiones) == 50
    assert red.peticiones[-1].full_url == f"{ASIGNATURAS}&pagina=50"
    assert list(asignaturas) == [uuid.UUID(PRIMERO["id"])]


@pytest.mark.parametrize(
    "falla",
    [
        error_http(500, b"<h1>Server Error (500)</h1>"),
        error_http(404, b"<!DOCTYPE html><title>Not Found</title>"),
        urllib.error.URLError(TimeoutError("timed out")),
        TimeoutError("timed out"),
        Respuesta([PRIMERO, SEGUNDO]),
        Respuesta({**pagina(1, 1, PRIMERO), "total_paginas": "1"}),
        Respuesta({**pagina(1, 1, PRIMERO), "resultados": None}),
        Respuesta(pagina(1, 1, {"id": "x", "sigla": "PGY1101", "nombre": "P"})),
        Respuesta(pagina(1, 1, {**PRIMERO, "nombre": None})),
    ],
    ids=[
        "error_500",
        "ruta_que_no_existe",
        "no_conecta_a_tiempo",
        "no_contesta_a_tiempo",
        "sin_paginar",
        "total_paginas_como_texto",
        "sin_resultados",
        "asignatura_sin_uuid",
        "asignatura_sin_nombre",
    ],
)
def test_si_catalogo_falla_al_listar_las_asignaturas_responde_503(red, falla):
    red.respuesta = falla

    with pytest.raises(ServicioNoDisponible) as error:
        llamadas.asignaturas_del_catalogo()

    assert "servicio de Catálogo" in str(error.value.detail)


def test_si_falla_la_segunda_pagina_no_devuelve_una_lista_a_medias(red):
    red.respuestas = [
        Respuesta(pagina(1, 2, PRIMERO)),
        error_http(500, b"<h1>Server Error (500)</h1>"),
    ]

    with pytest.raises(ServicioNoDisponible):
        llamadas.asignaturas_del_catalogo()

    assert len(red.peticiones) == 2


# ------------------------------------------------- El reembolso a Pagos (HU-28)

RESERVA_ID = uuid.uuid4()
REEMBOLSO = "http://payments:8000/api/payments/v1/internal/pagos/reembolso"


@pytest.fixture
def pagos(red, settings):
    """La red, con la direccion de Pagos y la clave de servicio fijadas.

    En la integracion continua URL_PAGOS y CLAVE_SERVICIO no existen.
    """
    settings.URL_PAGOS = "http://payments:8000"
    settings.CLAVE_SERVICIO = "clave-de-prueba"
    return red


def pago_reembolsado():
    """El 200 de POST /internal/pagos/reembolso de Pagos (vistas.pago_json)."""
    return {
        "id": str(uuid.uuid4()),
        "reserva_id": str(RESERVA_ID),
        "monto": 5000,
        "estado": "REEMBOLSADO",
        "proveedor": "SIMULADO",
        "creado_en": "2026-11-12T14:00:00Z",
        "actualizado_en": "2026-11-12T14:20:00Z",
        "intentos": [
            {
                "tipo": "REEMBOLSO",
                "resultado": "EXITOSO",
                "mensaje": None,
                "creado_en": "2026-11-12T14:20:00Z",
            },
            {
                "tipo": "COBRO",
                "resultado": "EXITOSO",
                "mensaje": None,
                "creado_en": "2026-11-12T14:01:00Z",
            },
        ],
    }


def registros_de_llamadas(caplog):
    """(nivel, mensaje) de cada linea que dejo llamadas.py en el log."""
    return [
        (registro.levelno, registro.getMessage())
        for registro in caplog.records
        if registro.name == llamadas.logger.name
    ]


def test_pedir_reembolso_con_200_pide_a_la_ruta_interna_y_devuelve_true(pagos):
    pagos.respuesta = Respuesta(pago_reembolsado())

    assert llamadas.pedir_reembolso(RESERVA_ID) is True

    [peticion] = pagos.peticiones
    assert peticion.full_url == REEMBOLSO
    assert peticion.get_method() == "POST"
    # El id va como texto: json.dumps no sabe escribir un uuid.UUID.
    assert json.loads(peticion.data) == {"reserva_id": str(RESERVA_ID)}
    # urllib guarda las cabeceras con str.capitalize().
    assert peticion.get_header("Content-type") == "application/json"
    assert peticion.get_header("X-clave-servicio") == "clave-de-prueba"
    # Una ruta interna no usa el token de nadie.
    assert peticion.get_header("Authorization") is None


NADA_QUE_REEMBOLSAR = {
    "sin_pago": (
        error_http(
            404,
            {
                "codigo": "pago_no_encontrado",
                "mensaje": "Esa reserva no tiene pago.",
                "detalles": None,
            },
        ),
        "404 (codigo pago_no_encontrado)",
    ),
    "pago_no_pagado": (
        error_http(
            409,
            {
                "codigo": "pago_no_reembolsable",
                "mensaje": "Solo se reembolsa un pago PAGADO.",
                "detalles": None,
            },
        ),
        "409 (codigo pago_no_reembolsable)",
    ),
}


@pytest.mark.parametrize(
    "respuesta, respondio",
    list(NADA_QUE_REEMBOLSAR.values()),
    ids=list(NADA_QUE_REEMBOLSAR),
)
def test_pedir_reembolso_sin_nada_que_reembolsar_devuelve_true(
    pagos, caplog, respuesta, respondio
):
    """La reserva no tiene pago, o el pago no esta PAGADO: Pagos decide."""
    caplog.set_level(logging.INFO, logger="tutorias.llamadas")
    pagos.respuesta = respuesta

    assert llamadas.pedir_reembolso(RESERVA_ID) is True

    # Una sola linea, informativa, con la reserva y el codigo. Ningun error.
    assert registros_de_llamadas(caplog) == [
        (
            logging.INFO,
            f"Nada que reembolsar en la reserva {RESERVA_ID}: Pagos respondió "
            f"{respondio}",
        )
    ]


REEMBOLSOS_PENDIENTES = {
    "ruta_no_encontrada": (
        error_http(404, {"codigo": "ruta_no_encontrada", "mensaje": "x"}),
        "404 sin código conocido desde Pagos: revisa CLAVE_SERVICIO",
    ),
    "html_404": (
        error_http(404, b"<!DOCTYPE html><title>Not Found</title>"),
        "404 sin código conocido desde Pagos: revisa CLAVE_SERVICIO",
    ),
    "error_500": (
        error_http(500, b"<h1>Server Error (500)</h1>"),
        "falló la llamada a Pagos (<HTTPError 500: 'error'>)",
    ),
    "no_conecta_a_tiempo": (
        urllib.error.URLError(TimeoutError("timed out")),
        "falló la llamada a Pagos (URLError(TimeoutError('timed out')))",
    ),
    "no_contesta_a_tiempo": (
        TimeoutError("timed out"),
        "falló la llamada a Pagos (TimeoutError('timed out'))",
    ),
    "no_conecta": (
        urllib.error.URLError(ConnectionRefusedError(111, "refused")),
        "falló la llamada a Pagos (URLError(ConnectionRefusedError(111, 'refused')))",
    ),
    "otro_error": (
        RuntimeError("inesperado"),
        "falló la llamada a Pagos (RuntimeError('inesperado'))",
    ),
}


@pytest.mark.parametrize(
    "falla, que_paso",
    list(REEMBOLSOS_PENDIENTES.values()),
    ids=list(REEMBOLSOS_PENDIENTES),
)
def test_si_pagos_falla_el_reembolso_queda_pendiente_sin_lanzar_nada(
    pagos, caplog, falla, que_paso
):
    """Devuelve False y no lanza: la cancelacion ya quedo guardada."""
    pagos.respuesta = falla

    assert llamadas.pedir_reembolso(RESERVA_ID) is False

    errores = [
        mensaje
        for nivel, mensaje in registros_de_llamadas(caplog)
        if nivel >= logging.ERROR
    ]
    assert errores == [
        f"El reembolso de la reserva {RESERVA_ID} quedó pendiente: {que_paso}"
    ]
