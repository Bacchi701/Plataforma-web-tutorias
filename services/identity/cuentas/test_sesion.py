from pathlib import Path

import jwt
import pytest
from django.core.management import call_command

from .models import RefreshToken, Usuario
from .tokens import leer_clave

BASE = "/api/identity/v1"
CLAVE = "clave-segura-1"


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
def usuario(db):
    return Usuario.objects.create_user(
        "ana.demo@duocuc.cl",
        CLAVE,
        nombre="Ana",
        apellido="Demo",
        email_verificado=True,
    )


def entrar(client, email="ana.demo@duocuc.cl", clave=CLAVE):
    return client.post(
        f"{BASE}/login",
        {"email": email, "password": clave},
        content_type="application/json",
    )


@pytest.mark.django_db
def test_el_login_entrega_un_token_rs256_y_la_cookie_de_renovacion(
    client, usuario, settings
):
    respuesta = entrar(client, email="ANA.DEMO@duocuc.cl")

    assert respuesta.status_code == 200
    token = respuesta.json()["token_acceso"]
    reclamaciones = jwt.decode(
        token,
        Path(settings.JWT_CLAVE_PUBLICA).read_text(),
        algorithms=["RS256"],
        issuer="identity",
    )
    assert reclamaciones["sub"] == str(usuario.id)
    assert reclamaciones["exp"] - reclamaciones["iat"] == 30 * 60
    assert set(reclamaciones) == {"sub", "es_admin", "iat", "exp", "iss"}
    cookie = respuesta.cookies["refresh_token"]
    assert cookie["httponly"]
    assert cookie["samesite"] == "Strict"
    assert RefreshToken.objects.get().token_hash != cookie.value


@pytest.mark.django_db
def test_credenciales_incorrectas_responden_401(client, usuario):
    assert entrar(client, clave="otra-clave-99").status_code == 401
    assert entrar(client, email="nadie@duocuc.cl").status_code == 401


@pytest.mark.django_db
def test_sin_verificar_el_correo_no_se_entra(client, usuario):
    Usuario.objects.update(email_verificado=False)

    respuesta = entrar(client)

    assert respuesta.status_code == 403
    assert respuesta.json()["codigo"] == "correo_no_verificado"


@pytest.mark.django_db
def test_una_cuenta_desactivada_no_entra(client, usuario):
    Usuario.objects.update(activo=False)

    respuesta = entrar(client)

    assert respuesta.status_code == 403
    assert respuesta.json()["codigo"] == "cuenta_desactivada"


@pytest.mark.django_db
def test_yo_exige_el_token_de_acceso(client, usuario):
    token = entrar(client).json()["token_acceso"]

    con_token = client.get(f"{BASE}/yo", HTTP_AUTHORIZATION=f"Bearer {token}")
    sin_token = client.get(f"{BASE}/yo")
    falso = client.get(f"{BASE}/yo", HTTP_AUTHORIZATION="Bearer abc.def.ghi")

    assert con_token.status_code == 200
    assert con_token.json()["email"] == "ana.demo@duocuc.cl"
    assert sin_token.status_code == 401
    assert falso.status_code == 401


@pytest.mark.django_db
def test_refresh_renueva_y_rota_la_cookie(client, usuario):
    entrar(client)
    cookie_vieja = client.cookies["refresh_token"].value

    renovado = client.post(f"{BASE}/refresh")
    assert renovado.status_code == 200
    assert renovado.json()["token_acceso"]

    # La renovacion usada queda revocada: reutilizarla no sirve.
    client.cookies["refresh_token"] = cookie_vieja
    assert client.post(f"{BASE}/refresh").status_code == 401


@pytest.mark.django_db
def test_logout_revoca_la_renovacion(client, usuario):
    entrar(client)
    cookie = client.cookies["refresh_token"].value

    assert client.post(f"{BASE}/logout").status_code == 204

    client.cookies["refresh_token"] = cookie
    assert client.post(f"{BASE}/refresh").status_code == 401
    assert RefreshToken.objects.filter(revocado_en__isnull=True).count() == 0
