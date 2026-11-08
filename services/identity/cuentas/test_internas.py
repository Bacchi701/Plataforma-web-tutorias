"""Pruebas de las rutas internas de Identidad (internas.py, Pilar 2 §5.4)."""

import uuid

import pytest

from .models import Usuario

BASE = "/api/identity/v1/internal"
CLAVE_PRUEBA = "clave-de-prueba"
CARRERA_ID = uuid.uuid4()
SEDE_ID = uuid.uuid4()


@pytest.fixture(autouse=True)
def clave_servicio(settings):
    settings.CLAVE_SERVICIO = CLAVE_PRUEBA


@pytest.fixture
def usuario(db):
    return Usuario.objects.create_user(
        "ana.demo@duocuc.cl",
        "clave-segura-1",
        nombre="Ana",
        apellido="Demo",
        carrera_id=CARRERA_ID,
        nivel=4,
        sede_id=SEDE_ID,
        email_verificado=True,
        activo=True,
    )


def test_con_clave_correcta_responde_200_y_los_siete_campos(client, usuario):
    respuesta = client.get(
        f"{BASE}/usuarios/{usuario.id}",
        HTTP_X_CLAVE_SERVICIO=CLAVE_PRUEBA,
    )

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos == {
        "id": str(usuario.id),
        "nombre": "Ana",
        "apellido": "Demo",
        "carrera_id": str(CARRERA_ID),
        "nivel": 4,
        "sede_id": str(SEDE_ID),
        "activo": True,
    }
    assert "email" not in datos
    assert "password" not in datos
    assert "es_admin" not in datos


def test_cuenta_desactivada_responde_200_con_activo_false(client, usuario):
    usuario.activo = False
    usuario.save()

    respuesta = client.get(
        f"{BASE}/usuarios/{usuario.id}",
        HTTP_X_CLAVE_SERVICIO=CLAVE_PRUEBA,
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["activo"] is False


@pytest.mark.parametrize(
    "cabeceras",
    [
        {},
        {"HTTP_X_CLAVE_SERVICIO": "clave-equivocada"},
        {"HTTP_X_CLAVE_SERVICIO": "clave-con-é"},
        {"HTTP_X_CLAVE_SERVICIO": ""},
    ],
    ids=["sin_cabecera", "clave_equivocada", "con_tilde", "cabecera_vacia"],
)
def test_sin_clave_valida_responde_404_ruta_no_encontrada(client, usuario, cabeceras):
    respuesta = client.get(f"{BASE}/usuarios/{usuario.id}", **cabeceras)

    assert respuesta.status_code == 404
    assert respuesta.json()["codigo"] == "ruta_no_encontrada"


def test_con_clave_servicio_vacia_en_settings_responde_404(client, usuario, settings):
    settings.CLAVE_SERVICIO = ""

    respuesta = client.get(
        f"{BASE}/usuarios/{usuario.id}",
        HTTP_X_CLAVE_SERVICIO=CLAVE_PRUEBA,
    )
    assert respuesta.status_code == 404
    assert respuesta.json()["codigo"] == "ruta_no_encontrada"

    respuesta_vacia = client.get(
        f"{BASE}/usuarios/{usuario.id}",
        HTTP_X_CLAVE_SERVICIO="",
    )
    assert respuesta_vacia.status_code == 404
    assert respuesta_vacia.json()["codigo"] == "ruta_no_encontrada"


def test_usuario_que_no_existe_responde_404_usuario_no_encontrado(client, db):
    inexistente = uuid.uuid4()
    respuesta = client.get(
        f"{BASE}/usuarios/{inexistente}",
        HTTP_X_CLAVE_SERVICIO=CLAVE_PRUEBA,
    )

    assert respuesta.status_code == 404
    assert respuesta.json()["codigo"] == "usuario_no_encontrado"


def test_authorization_sin_clave_de_servicio_responde_404(client, usuario):
    respuesta = client.get(
        f"{BASE}/usuarios/{usuario.id}",
        HTTP_AUTHORIZATION="Bearer token-cualquiera",
    )

    assert respuesta.status_code == 404
    assert respuesta.json()["codigo"] == "ruta_no_encontrada"
