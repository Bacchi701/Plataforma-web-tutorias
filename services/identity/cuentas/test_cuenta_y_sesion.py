"""Lo que faltaba de la cuenta y la sesion (HU-11, criterio 2).

El registro, la verificacion, el inicio, la renovacion y el cierre de sesion
ya tienen sus pruebas en test_registro.py y test_sesion.py, y la cuenta
desactivada, en test_sesion.py y test_administracion.py. Aqui van los casos
que no tenian prueba y los errores 500 de esas rutas que corrige esta
historia:
- POST /verificar-correo con un cuerpo que no es un objeto JSON, o con un
  token que no se puede pasar a UTF-8;
- POST /login y POST /refresh sin una clave privada que se pueda leer;
- POST /refresh sin la cookie, o de una cuenta desactivada que conserva su
  renovacion, y POST /logout sin la cookie.
"""

import pytest
from django.core.management import call_command
from django.test import Client

from .models import RefreshToken, Usuario
from .tokens import leer_clave

BASE = "/api/identity/v1"
VERIFICAR = f"{BASE}/verificar-correo"
CLAVE = "clave-segura-1"
SESION_INVALIDA = {
    "codigo": "sesion_invalida",
    "mensaje": "La sesión no es válida o venció.",
    "detalles": None,
}


# Como en test_sesion.py: claves RS256 de prueba en tmp_path y un hash rapido.
@pytest.fixture(autouse=True)
def entorno(settings, tmp_path):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    settings.JWT_CLAVE_PRIVADA = str(tmp_path / "jwt_private.pem")
    settings.JWT_CLAVE_PUBLICA = str(tmp_path / "jwt_public.pem")
    call_command("generar_claves_jwt")
    leer_clave.cache_clear()
    yield
    leer_clave.cache_clear()


@pytest.fixture
def cuenta(db):
    return Usuario.objects.create_user(
        "ana.demo@duocuc.cl",
        CLAVE,
        nombre="Ana",
        apellido="Demo",
        email_verificado=True,
    )


def entrar(cliente):
    return cliente.post(
        f"{BASE}/login",
        {"email": "ana.demo@duocuc.cl", "password": CLAVE},
        content_type="application/json",
    )


def sesiones_abiertas():
    return RefreshToken.objects.filter(revocado_en__isnull=True).count()


# ------------------------------------------- POST /verificar-correo


@pytest.mark.django_db
@pytest.mark.parametrize(
    "cuerpo",
    ['["x"]', '"un texto"', "5", "null"],
    ids=["lista", "texto", "numero", "null"],
)
def test_verificar_correo_con_un_cuerpo_que_no_es_un_objeto_responde_400(
    client, cuerpo
):
    # El JSON va tal cual. Antes, request.data.get no existia: 500.
    respuesta = client.post(VERIFICAR, cuerpo, content_type="application/json")

    assert respuesta.status_code == 400
    assert respuesta.json() == {
        "codigo": "invalid",
        "mensaje": "La petición tiene datos inválidos.",
        "detalles": {"token": ["Falta el token del enlace."]},
    }


@pytest.mark.django_db
def test_verificar_correo_con_un_token_que_no_pasa_a_utf8_responde_400(client):
    # "\ud800" en el JSON es un sustituto de UTF-16 suelto: hash_de no lo puede
    # pasar a UTF-8. Antes, 500.
    respuesta = client.post(
        VERIFICAR, '{"token": "\\ud800"}', content_type="application/json"
    )

    assert respuesta.status_code == 400
    assert respuesta.json() == {
        "codigo": "token_invalido",
        "mensaje": "El enlace no es válido.",
        "detalles": None,
    }


# ------------------------------------------- la clave privada


@pytest.mark.django_db
@pytest.mark.parametrize(
    "contenido, dice",
    [
        (None, "No existe"),
        ("esto no es una clave\n", "generar_claves_jwt --forzar"),
    ],
    ids=["sin_el_archivo", "no_es_una_clave"],
)
def test_login_sin_una_clave_privada_que_se_pueda_leer_responde_503(
    client, cuenta, settings, tmp_path, contenido, dice
):
    ruta = tmp_path / "otra" / "jwt_private.pem"
    if contenido is not None:
        ruta.parent.mkdir()
        ruta.write_text(contenido)
    settings.JWT_CLAVE_PRIVADA = str(ruta)
    leer_clave.cache_clear()

    respuesta = entrar(client)

    # Sin el archivo ya respondia 503; con un archivo que no es una clave, 500.
    assert respuesta.status_code == 503
    cuerpo = respuesta.json()
    assert cuerpo["codigo"] == "claves_no_configuradas"
    assert str(ruta) in cuerpo["mensaje"]
    assert dice in cuerpo["mensaje"]
    # No se abre ninguna sesion: ni fila en refresh_token ni cookie.
    assert not RefreshToken.objects.exists()
    assert "refresh_token" not in respuesta.cookies


@pytest.mark.django_db
def test_refresh_con_una_clave_que_no_es_pem_responde_503_y_la_sesion_sigue(
    client, cuenta, settings, tmp_path
):
    assert entrar(client).status_code == 200
    buena = settings.JWT_CLAVE_PRIVADA
    mala = tmp_path / "no_es_una_clave.pem"
    mala.write_text("esto no es una clave\n")
    settings.JWT_CLAVE_PRIVADA = str(mala)
    leer_clave.cache_clear()

    respuesta = client.post(f"{BASE}/refresh")

    assert respuesta.status_code == 503
    assert respuesta.json()["codigo"] == "claves_no_configuradas"
    assert str(mala) in respuesta.json()["mensaje"]
    # La transaccion se deshizo: la renovacion no quedo revocada y, con la
    # clave de vuelta, la misma cookie renueva la sesion.
    assert sesiones_abiertas() == 1
    settings.JWT_CLAVE_PRIVADA = buena
    leer_clave.cache_clear()
    assert client.post(f"{BASE}/refresh").status_code == 200


# ------------------------------------------- refresh y logout


@pytest.mark.django_db
def test_refresh_de_una_cuenta_desactivada_despues_de_entrar_responde_401(
    client, cuenta
):
    assert entrar(client).status_code == 200
    # Desactivada directo en la base, sin revocar su renovacion: refresh
    # revisa tambien que la cuenta siga activa. Desde el panel (HU-31) la
    # renovacion se revoca en el mismo paso.
    Usuario.objects.filter(id=cuenta.id).update(activo=False)

    respuesta = client.post(f"{BASE}/refresh")

    assert respuesta.status_code == 401
    assert respuesta.json() == SESION_INVALIDA
    # No se entrega una renovacion nueva.
    assert RefreshToken.objects.count() == 1


@pytest.mark.django_db
def test_refresh_sin_la_cookie_responde_401(client):
    respuesta = client.post(f"{BASE}/refresh")

    assert respuesta.status_code == 401
    assert respuesta.json() == SESION_INVALIDA


@pytest.mark.django_db
def test_logout_sin_la_cookie_responde_204_y_no_cierra_otras_sesiones(client, cuenta):
    assert entrar(Client()).status_code == 200

    respuesta = client.post(f"{BASE}/logout")

    assert respuesta.status_code == 204
    assert respuesta.cookies["refresh_token"].value == ""
    assert sesiones_abiertas() == 1
