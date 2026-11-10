"""El token de acceso en las rutas de Identidad (HU-11, criterio 3).

Lo que rechaza TokenDeAcceso y los errores 500 que corrige esta historia: una
cabecera que no es texto, un sub que no es un uuid, y una clave publica que
falta, es una carpeta o no es una clave. Casi todo va sobre GET /yo; la
ultima prueba muestra que vale igual en PATCH /yo y en las rutas /admin.

Como en test_perfil.py, las claves RS256 se generan en tmp_path. firmar()
firma con la clave privada de prueba las reclamaciones de emitir_acceso, con
los cambios que se le pidan; otra_clave es un par RSA que Identidad no conoce.
"""

import base64
import hashlib
import hmac
import json
import uuid
from datetime import timedelta
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.core.management import call_command
from django.utils import timezone

from .models import Usuario
from .tokens import ALGORITMO, emitir_acceso, leer_clave

BASE = "/api/identity/v1"
YO = f"{BASE}/yo"
CLAVE = "clave-segura-1"
DESAFIO = 'Bearer realm="identity"'
MENSAJES = {
    "token_vencido": "El token de acceso venció.",
    "token_invalido": "El token de acceso no es válido.",
    "cuenta_inactiva": "La cuenta no existe o está desactivada.",
}


@pytest.fixture(autouse=True)
def entorno(settings, tmp_path):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    settings.JWT_CLAVE_PRIVADA = str(tmp_path / "jwt_private.pem")
    settings.JWT_CLAVE_PUBLICA = str(tmp_path / "jwt_public.pem")
    call_command("generar_claves_jwt")
    leer_clave.cache_clear()
    yield
    leer_clave.cache_clear()


@pytest.fixture(scope="module")
def otra_clave():
    """Un par RSA que Identidad no conoce."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def crear_cuenta(email, nombre, **campos):
    return Usuario.objects.create_user(
        email, CLAVE, nombre=nombre, apellido="Demo", email_verificado=True, **campos
    )


@pytest.fixture
def cuenta(db):
    return crear_cuenta("ana.demo@duocuc.cl", "Ana")


@pytest.fixture
def admin(db):
    return crear_cuenta("admin.demo@duocuc.cl", "Admin", es_admin=True)


def reclamaciones_de(usuario):
    """Las que pone emitir_acceso: sub, es_admin, iat, exp e iss."""
    return jwt.decode(emitir_acceso(usuario), options={"verify_signature": False})


def firmar(usuario, clave=None, **cambios):
    """Un token con las reclamaciones de emitir_acceso y esos cambios.

    Lo firma con la clave privada de prueba o, si se pasa, con clave.
    """
    if clave is None:
        clave = leer_clave(settings.JWT_CLAVE_PRIVADA)
    return jwt.encode(
        {**reclamaciones_de(usuario), **cambios}, clave, algorithm=ALGORITMO
    )


def b64url(datos):
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


def token_a_mano(usuario, alg, secreto=None):
    """Las reclamaciones de emitir_acceso con otro alg, armado a mano.

    PyJWT no deja firmar estos casos (como en tutorias/test_autenticacion.py).
    Con secreto, la firma es HMAC-SHA256 con ese secreto; sin secreto, va
    vacia (alg none).
    """
    cabecera = {"alg": alg, "typ": "JWT"}
    partes = [
        b64url(json.dumps(parte).encode())
        for parte in (cabecera, reclamaciones_de(usuario))
    ]
    firma = b""
    if secreto is not None:
        firma = hmac.new(secreto, ".".join(partes).encode(), hashlib.sha256).digest()
    return ".".join([*partes, b64url(firma)])


def con_token(token):
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def rechazo(codigo):
    return {"codigo": codigo, "mensaje": MENSAJES[codigo], "detalles": None}


# ------------------------------------------- los tokens que no sirven


@pytest.mark.django_db
def test_un_token_firmado_por_identidad_entra(client, cuenta):
    # Asi se sabe que firmar() arma un token bueno: en las pruebas que siguen,
    # lo unico distinto es lo que se tiene que rechazar.
    respuesta = client.get(YO, **con_token(firmar(cuenta)))

    assert respuesta.status_code == 200
    assert respuesta.json()["id"] == str(cuenta.id)


def token_que_no_sirve(caso, usuario, otra_clave):
    """Un token de esa cuenta, que Identidad tiene que rechazar."""
    if caso == "vencido":
        hace_una_hora = timezone.now() - timedelta(hours=1)
        return firmar(
            usuario,
            iat=int(hace_una_hora.timestamp()),
            exp=int((hace_una_hora + timedelta(minutes=30)).timestamp()),
        )
    if caso == "firmado_con_otra_clave":
        return firmar(usuario, clave=otra_clave)
    if caso == "de_otro_emisor":
        return firmar(usuario, iss="otro-servicio")
    if caso == "sin_firma_alg_none":
        return token_a_mano(usuario, "none")
    assert caso == "hs256_con_la_clave_publica", caso
    # Confusion de algoritmos: la clave publica esta en el repositorio; si se
    # aceptara HS256, con ella como secreto cualquiera firmaria un token.
    publica = Path(settings.JWT_CLAVE_PUBLICA).read_bytes()
    return token_a_mano(usuario, "HS256", secreto=publica)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "caso, codigo",
    [
        ("vencido", "token_vencido"),
        ("firmado_con_otra_clave", "token_invalido"),
        ("de_otro_emisor", "token_invalido"),
        ("sin_firma_alg_none", "token_invalido"),
        ("hs256_con_la_clave_publica", "token_invalido"),
    ],
    ids=[
        "vencido",
        "firmado_con_otra_clave",
        "de_otro_emisor",
        "sin_firma_alg_none",
        "hs256_con_la_clave_publica",
    ],
)
def test_un_token_que_no_sirve_responde_401(client, cuenta, otra_clave, caso, codigo):
    token = token_que_no_sirve(caso, cuenta, otra_clave)

    respuesta = client.get(YO, **con_token(token))

    assert respuesta.status_code == 401
    assert respuesta.json() == rechazo(codigo)
    assert respuesta["WWW-Authenticate"] == DESAFIO


@pytest.mark.django_db
def test_una_cabecera_que_no_es_texto_responde_401_token_invalido(client, cuenta):
    # La «é» llega como el byte 0xE9 (latin-1), que no es UTF-8. Antes, 500.
    respuesta = client.get(YO, HTTP_AUTHORIZATION="Bearer é")

    assert respuesta.status_code == 401
    assert respuesta.json() == rechazo("token_invalido")
    assert respuesta["WWW-Authenticate"] == DESAFIO


@pytest.mark.django_db
def test_un_sub_que_no_es_un_uuid_responde_401_token_invalido(client, cuenta):
    # Bien firmado, pero buscar la cuenta con id "valentina" lanzaba el
    # ValidationError de Django. Antes, 500.
    respuesta = client.get(YO, **con_token(firmar(cuenta, sub="valentina")))

    assert respuesta.status_code == 401
    assert respuesta.json() == rechazo("token_invalido")
    assert respuesta["WWW-Authenticate"] == DESAFIO


@pytest.mark.django_db
def test_el_sub_de_una_cuenta_que_no_existe_responde_401_cuenta_inactiva(
    client, cuenta
):
    respuesta = client.get(YO, **con_token(firmar(cuenta, sub=str(uuid.uuid4()))))

    assert respuesta.status_code == 401
    assert respuesta.json() == rechazo("cuenta_inactiva")
    assert respuesta["WWW-Authenticate"] == DESAFIO


# ------------------------------------------- la clave publica


def clave_publica_que_no_sirve(caso, tmp_path):
    """Una ruta para JWT_CLAVE_PUBLICA que Identidad no puede usar."""
    ruta = tmp_path / "montada" / "jwt_public.pem"
    if caso == "carpeta":
        # Lo que deja Docker si el archivo no estaba al montarlo.
        ruta.mkdir(parents=True)
    elif caso != "no_existe":
        ruta.parent.mkdir()
        ruta.write_text("" if caso == "archivo_vacio" else "esto no es una clave\n")
    return ruta


@pytest.mark.django_db
@pytest.mark.parametrize(
    "caso, dice",
    [
        ("no_existe", "No existe"),
        ("carpeta", "No existe"),
        ("archivo_vacio", "generar_claves_jwt --forzar"),
        ("texto", "generar_claves_jwt --forzar"),
    ],
    ids=["no_existe", "es_una_carpeta", "archivo_vacio", "texto_que_no_es_clave"],
)
def test_sin_una_clave_publica_que_se_pueda_leer_responde_503(
    client, cuenta, settings, tmp_path, caso, dice
):
    token = firmar(cuenta)
    ruta = clave_publica_que_no_sirve(caso, tmp_path)
    settings.JWT_CLAVE_PUBLICA = str(ruta)
    leer_clave.cache_clear()

    respuesta = client.get(YO, **con_token(token))

    # Antes, 500: ImproperlyConfigured, IsADirectoryError o InvalidKeyError.
    assert respuesta.status_code == 503
    cuerpo = respuesta.json()
    assert cuerpo["codigo"] == "claves_no_configuradas"
    assert str(ruta) in cuerpo["mensaje"]
    assert dice in cuerpo["mensaje"]
    assert cuerpo["detalles"] is None


@pytest.mark.django_db
def test_sin_la_clave_publica_y_sin_token_responde_401_sin_leerla(
    client, settings, tmp_path
):
    settings.JWT_CLAVE_PUBLICA = str(tmp_path / "no-existe.pem")
    leer_clave.cache_clear()

    respuesta = client.get(YO)

    assert respuesta.status_code == 401
    assert respuesta.json()["codigo"] == "not_authenticated"
    assert respuesta["WWW-Authenticate"] == DESAFIO
    # Sin token no se lee la clave.
    assert leer_clave.cache_info().misses == 0


def test_pyjwt_lanza_invalid_key_error_que_no_es_invalid_token_error():
    """Por esto TokenDeAcceso y respuesta_con_sesion lo capturan aparte."""
    reclamaciones = {"sub": str(uuid.uuid4())}
    token = jwt.encode(
        reclamaciones, leer_clave(settings.JWT_CLAVE_PRIVADA), algorithm=ALGORITMO
    )

    with pytest.raises(jwt.InvalidKeyError):
        jwt.decode(token, "esto no es una clave", algorithms=[ALGORITMO])
    with pytest.raises(jwt.InvalidKeyError):
        jwt.encode(reclamaciones, "", algorithm=ALGORITMO)
    assert not issubclass(jwt.InvalidKeyError, jwt.InvalidTokenError)


# ------------------------------------------- las demas rutas con token

# PATCH /yo (HU-10) y las dos rutas de administracion (HU-31).
OTRAS_RUTAS = {
    "patch_yo": ("patch", "/yo"),
    "get_admin_usuarios": ("get", "/admin/usuarios"),
    "patch_admin_usuario": ("patch", "/admin/usuarios/{id}"),
}


def pedir(client, metodo, url, token):
    if metodo == "get":
        return client.get(url, **con_token(token))
    return client.patch(url, {}, content_type="application/json", **con_token(token))


@pytest.mark.django_db
@pytest.mark.parametrize(
    "metodo, ruta", list(OTRAS_RUTAS.values()), ids=list(OTRAS_RUTAS)
)
def test_las_demas_rutas_con_token_rechazan_igual(
    client, admin, otra_clave, settings, tmp_path, metodo, ruta
):
    url = BASE + ruta.format(id=admin.id)
    token = firmar(admin)

    con_otra_clave = pedir(client, metodo, url, firmar(admin, clave=otra_clave))
    settings.JWT_CLAVE_PUBLICA = str(tmp_path / "no-existe.pem")
    leer_clave.cache_clear()
    sin_la_clave_publica = pedir(client, metodo, url, token)

    assert con_otra_clave.status_code == 401
    assert con_otra_clave.json() == rechazo("token_invalido")
    assert con_otra_clave["WWW-Authenticate"] == DESAFIO
    assert sin_la_clave_publica.status_code == 503
    assert sin_la_clave_publica.json()["codigo"] == "claves_no_configuradas"
