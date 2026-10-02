import re
from datetime import timedelta

import pytest
from django.utils import timezone

from .models import AvisoCorreo, EstadoAviso, TokenVerificacion, Usuario

BASE = "/api/identity/v1"
DATOS = {
    "nombre": "Ana",
    "apellido": "Demo",
    "email": "Ana.Demo@DuocUC.cl",
    "password": "clave-segura-1",
}


@pytest.fixture(autouse=True)
def hash_rapido(settings):
    # Las pruebas no necesitan el millon de iteraciones de PBKDF2.
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


def registrar(client, **cambios):
    return client.post(
        f"{BASE}/registro", {**DATOS, **cambios}, content_type="application/json"
    )


def token_del_correo(correo):
    return re.search(r"token=([\w-]+)", correo.body).group(1)


@pytest.mark.django_db
def test_el_registro_crea_la_cuenta_sin_verificar_y_envia_el_enlace(client, mailoutbox):
    respuesta = registrar(client)

    assert respuesta.status_code == 201
    usuario = Usuario.objects.get()
    assert usuario.email == "ana.demo@duocuc.cl"
    assert usuario.email_verificado is False
    assert len(mailoutbox) == 1
    token = token_del_correo(mailoutbox[0])
    # En la base queda el sha256, nunca el token (A-12).
    assert TokenVerificacion.objects.get().token_hash != token
    assert AvisoCorreo.objects.get().estado == EstadoAviso.ENVIADO


@pytest.mark.django_db
@pytest.mark.parametrize(
    "cambio, campo",
    [
        ({"email": "ana.demo@gmail.com"}, "email"),
        ({"password": "corta"}, "password"),
        ({"nombre": ""}, "nombre"),
    ],
)
def test_el_registro_rechaza_datos_invalidos(client, cambio, campo):
    respuesta = registrar(client, **cambio)

    assert respuesta.status_code == 400
    assert campo in respuesta.json()["detalles"]
    assert not Usuario.objects.exists()


@pytest.mark.django_db
def test_no_se_registra_dos_veces_el_mismo_correo(client):
    registrar(client)

    respuesta = registrar(client, email="ANA.DEMO@duocuc.cl")

    assert respuesta.status_code == 400
    assert "email" in respuesta.json()["detalles"]


@pytest.mark.django_db
def test_el_enlace_verifica_la_cuenta_una_sola_vez(client, mailoutbox):
    registrar(client)
    token = token_del_correo(mailoutbox[0])

    primera = client.post(
        f"{BASE}/verificar-correo", {"token": token}, content_type="application/json"
    )
    segunda = client.post(
        f"{BASE}/verificar-correo", {"token": token}, content_type="application/json"
    )

    assert primera.status_code == 200
    assert Usuario.objects.get().email_verificado is True
    assert segunda.status_code == 400
    assert segunda.json()["codigo"] == "token_usado"


@pytest.mark.django_db
def test_un_enlace_vencido_no_verifica(client, mailoutbox):
    registrar(client)
    token = token_del_correo(mailoutbox[0])
    TokenVerificacion.objects.update(
        creado_en=timezone.now() - timedelta(days=2),
        expira_en=timezone.now() - timedelta(days=1),
    )

    respuesta = client.post(
        f"{BASE}/verificar-correo", {"token": token}, content_type="application/json"
    )

    assert respuesta.status_code == 400
    assert respuesta.json()["codigo"] == "token_vencido"
    assert Usuario.objects.get().email_verificado is False


@pytest.mark.django_db
def test_un_token_inventado_no_verifica(client):
    respuesta = client.post(
        f"{BASE}/verificar-correo",
        {"token": "inventado"},
        content_type="application/json",
    )

    assert respuesta.status_code == 400
    assert respuesta.json()["codigo"] == "token_invalido"
