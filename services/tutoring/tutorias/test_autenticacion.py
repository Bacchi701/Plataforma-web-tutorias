"""Pruebas del token de acceso en Tutorias (HU-17, criterio 1).

No usan las claves de keys/: generan su propio par RSA, firman los tokens con
la privada, como Identidad (cuentas/tokens.py), y Tutorias los verifica con la
publica. Este cambio no agrega endpoints, asi que se llama directo al
autenticador y a una vista de prueba que no tiene ruta.
"""

import base64
import hashlib
import hmac
import json
import uuid
from datetime import timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from .autenticacion import (
    ClavesNoConfiguradas,
    TokenDeAcceso,
    UsuarioDelToken,
    leer_clave,
)

USUARIO_ID = uuid.uuid4()


def clave_nueva():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def clave_de_identidad():
    """Hace de la clave privada de Identidad: firma los tokens de las pruebas."""
    return clave_nueva()


@pytest.fixture(autouse=True)
def clave_publica(clave_de_identidad, settings, tmp_path):
    """Deja la clave publica en tmp_path y Tutorias la lee de ahi."""
    ruta = tmp_path / "jwt_public.pem"
    ruta.write_bytes(
        clave_de_identidad.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    settings.JWT_CLAVE_PUBLICA = str(ruta)
    leer_clave.cache_clear()
    yield ruta
    leer_clave.cache_clear()


def firmar(clave, quitar=(), **cambios):
    """Token con las reclamaciones que pone Identidad.

    cambios reemplaza o agrega reclamaciones; quitar dice cuales sacar.
    """
    ahora = timezone.now()
    reclamaciones = {
        "sub": str(USUARIO_ID),
        "es_admin": False,
        "iat": int(ahora.timestamp()),
        "exp": int((ahora + timedelta(minutes=30)).timestamp()),
        "iss": "identity",
    }
    reclamaciones.update(cambios)
    for nombre in quitar:
        del reclamaciones[nombre]
    return jwt.encode(reclamaciones, clave, algorithm="RS256")


def b64url(datos):
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


def token_a_mano(alg, secreto=None):
    """Token de administrador con otro alg, armado a mano.

    PyJWT no deja firmar estos casos. Con secreto, la firma es HMAC-SHA256
    con ese secreto; sin secreto, va vacia (alg none).
    """
    ahora = int(timezone.now().timestamp())
    cabecera = {"alg": alg, "typ": "JWT"}
    reclamaciones = {
        "sub": str(USUARIO_ID),
        "es_admin": True,
        "iat": ahora,
        "exp": ahora + 30 * 60,
        "iss": "identity",
    }
    partes = [b64url(json.dumps(parte).encode()) for parte in (cabecera, reclamaciones)]
    firma = b""
    if secreto is not None:
        firma = hmac.new(secreto, ".".join(partes).encode(), hashlib.sha256).digest()
    return ".".join([*partes, b64url(firma)])


def peticion(cabecera=None):
    """GET con esa cabecera Authorization, o sin ella."""
    if cabecera is None:
        return APIRequestFactory().get("/")
    return APIRequestFactory().get("/", HTTP_AUTHORIZATION=cabecera)


def autenticar(cabecera=None):
    return TokenDeAcceso().authenticate(peticion(cabecera))


def rechazo(cabecera):
    """Codigo con que el autenticador rechaza la peticion."""
    with pytest.raises(AuthenticationFailed) as error:
        autenticar(cabecera)
    return error.value.detail.code


def test_sin_cabecera_no_autentica_y_la_peticion_sigue_sin_usuario():
    assert autenticar() is None


def test_sin_token_bearer_no_se_lee_la_clave(settings, tmp_path):
    # /estado y las rutas publicas no dependen de que la clave este montada.
    settings.JWT_CLAVE_PUBLICA = str(tmp_path / "no-existe.pem")

    assert autenticar() is None
    assert autenticar("Basic dXN1YXJpbzpjbGF2ZQ==") is None
    assert leer_clave.cache_info().misses == 0


def test_un_token_valido_entrega_el_usuario_del_token(clave_de_identidad):
    token = firmar(clave_de_identidad, es_admin=True)

    usuario, reclamaciones = autenticar(f"Bearer {token}")

    # La igualdad compara con un uuid.UUID: un texto no seria igual.
    assert usuario == UsuarioDelToken(usuario_id=USUARIO_ID, es_admin=True)
    assert usuario.is_authenticated
    assert not usuario.is_anonymous
    assert reclamaciones["iss"] == "identity"


def test_un_token_vencido_se_rechaza_con_token_vencido(clave_de_identidad):
    hace_una_hora = timezone.now() - timedelta(hours=1)
    token = firmar(
        clave_de_identidad,
        iat=int(hace_una_hora.timestamp()),
        exp=int((hace_una_hora + timedelta(minutes=30)).timestamp()),
    )

    assert rechazo(f"Bearer {token}") == "token_vencido"


def test_un_token_firmado_con_otra_clave_se_rechaza_con_token_invalido():
    token = firmar(clave_nueva())

    assert rechazo(f"Bearer {token}") == "token_invalido"


def test_un_token_de_otro_emisor_se_rechaza_con_token_invalido(clave_de_identidad):
    token = firmar(clave_de_identidad, iss="otro-servicio")

    assert rechazo(f"Bearer {token}") == "token_invalido"


@pytest.mark.parametrize("reclamacion", ["sub", "iat", "exp", "iss"])
def test_un_token_sin_una_reclamacion_obligatoria_se_rechaza_con_token_invalido(
    clave_de_identidad, reclamacion
):
    token = firmar(clave_de_identidad, quitar=[reclamacion])

    assert rechazo(f"Bearer {token}") == "token_invalido"


def test_un_token_sin_firma_alg_none_se_rechaza_con_token_invalido():
    token = token_a_mano("none")

    assert rechazo(f"Bearer {token}") == "token_invalido"


def test_un_token_hs256_firmado_con_la_clave_publica_se_rechaza_con_token_invalido(
    clave_publica,
):
    # Confusion de algoritmos: la clave publica esta en el repositorio; si se
    # aceptara HS256, con ella como secreto cualquiera firmaria un token.
    token = token_a_mano("HS256", secreto=clave_publica.read_bytes())

    assert rechazo(f"Bearer {token}") == "token_invalido"


def test_una_cabecera_con_tres_partes_se_rechaza(clave_de_identidad):
    token = firmar(clave_de_identidad)

    assert rechazo(f"Bearer {token} sobrante") == "authentication_failed"


def test_un_sub_que_no_es_uuid_se_rechaza_con_token_invalido(clave_de_identidad):
    token = firmar(clave_de_identidad, sub="valentina")

    assert rechazo(f"Bearer {token}") == "token_invalido"


@pytest.mark.parametrize(
    "cambios",
    [
        pytest.param({"es_admin": "true"}, id="texto-true"),
        pytest.param({"es_admin": 1}, id="numero-1"),
        pytest.param({"quitar": ["es_admin"]}, id="sin-es_admin"),
    ],
)
def test_un_es_admin_que_no_es_true_de_json_no_da_permisos_de_administrador(
    clave_de_identidad, cambios
):
    usuario, _ = autenticar(f"Bearer {firmar(clave_de_identidad, **cambios)}")

    assert usuario.es_admin is False


def test_una_cabecera_que_no_es_texto_se_rechaza_con_token_invalido():
    # La "é" llega como el byte 0xE9 (latin-1), que no es UTF-8 valido.
    assert rechazo("Bearer é") == "token_invalido"


def test_sin_el_archivo_de_la_clave_responde_503_con_el_motivo(
    clave_de_identidad, settings, tmp_path
):
    settings.JWT_CLAVE_PUBLICA = str(tmp_path / "no-existe.pem")
    token = firmar(clave_de_identidad)

    with pytest.raises(ClavesNoConfiguradas) as error:
        autenticar(f"Bearer {token}")

    assert error.value.status_code == 503
    assert error.value.detail.code == "claves_no_configuradas"
    assert "no-existe.pem" in str(error.value.detail)


# Vista sin ruta, con la configuracion por defecto de DRF (settings.py): asi
# se comprueba lo que veran las vistas con sesion que agrega HU-15.
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def vista_con_sesion(request):
    return Response({"usuario_id": str(request.user.usuario_id)})


def test_una_vista_que_pide_sesion_responde_401_sin_token():
    respuesta = vista_con_sesion(peticion())

    assert respuesta.status_code == 401
    assert respuesta["WWW-Authenticate"] == 'Bearer realm="tutoring"'
    assert respuesta.data["codigo"] == "not_authenticated"
    assert respuesta.data["detalles"] is None


def test_una_vista_que_pide_sesion_responde_401_con_token_vencido(clave_de_identidad):
    hace_una_hora = timezone.now() - timedelta(hours=1)
    token = firmar(
        clave_de_identidad,
        iat=int(hace_una_hora.timestamp()),
        exp=int((hace_una_hora + timedelta(minutes=30)).timestamp()),
    )

    respuesta = vista_con_sesion(peticion(f"Bearer {token}"))

    assert respuesta.status_code == 401
    assert respuesta["WWW-Authenticate"] == 'Bearer realm="tutoring"'
    assert respuesta.data == {
        "codigo": "token_vencido",
        "mensaje": "El token de acceso venció.",
        "detalles": None,
    }


def test_una_vista_que_pide_sesion_recibe_al_usuario_del_token(clave_de_identidad):
    token = firmar(clave_de_identidad)

    respuesta = vista_con_sesion(peticion(f"Bearer {token}"))

    assert respuesta.status_code == 200
    assert respuesta.data == {"usuario_id": str(USUARIO_ID)}
