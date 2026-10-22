"""Autenticacion con el token de acceso de Identidad (HU-17, criterio 1).

Tutorias no emite tokens: verifica con la clave publica la firma RS256 del
token que emite Identidad (Pilar 2, seccion 5.1, paso 4), como lo hacen
cuentas/tokens.py y cuentas/autenticacion.py en Identidad, y con los mismos
codigos de error. No consulta la base: quien hace la peticion sale de las
reclamaciones del token.
"""

import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import jwt
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from rest_framework import status
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import APIException, AuthenticationFailed

ALGORITMO = "RS256"
VENCIDO = "El token de acceso venció."
INVALIDO = "El token de acceso no es válido."


@lru_cache
def leer_clave(ruta):
    archivo = Path(ruta)
    # is_file y no exists: si el archivo no estaba al levantar el contenedor,
    # Docker monta en su lugar una carpeta con ese nombre.
    if not archivo.is_file():
        raise ImproperlyConfigured(
            f"No existe el archivo {ruta}. Tutorías verifica los tokens con la "
            "clave pública de Identidad, keys/jwt_public.pem, que "
            "docker-compose.yml monta en /app/keys. Si faltan las claves, se "
            "generan en Identidad con: python manage.py generar_claves_jwt "
            "(ver el RUNBOOK, nivel 3)."
        )
    return archivo.read_text()


def verificar_acceso(token):
    """Devuelve las reclamaciones o lanza jwt.InvalidTokenError.

    Si falta la clave publica, leer_clave lanza ImproperlyConfigured.
    """
    return jwt.decode(
        token,
        leer_clave(settings.JWT_CLAVE_PUBLICA),
        algorithms=[ALGORITMO],
        issuer=settings.JWT_EMISOR,
        options={"require": ["sub", "iat", "exp", "iss"]},
    )


@dataclass(frozen=True)
class UsuarioDelToken:
    """Quien hace la peticion, segun el token; es lo que queda en request.user.

    usuario_id es el id de la cuenta en Identidad, el mismo de usuario_ref.
    """

    usuario_id: uuid.UUID
    es_admin: bool

    # IsAuthenticated de DRF pregunta por is_authenticated.
    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False


class ClavesNoConfiguradas(APIException):
    """Falta la clave publica: 503 con el motivo, como el login de Identidad."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = "claves_no_configuradas"


class TokenDeAcceso(BaseAuthentication):
    """Lee "Authorization: Bearer <token>" y verifica la firma RS256."""

    def authenticate(self, request):
        partes = get_authorization_header(request).split()
        if not partes or partes[0].lower() != b"bearer":
            return None
        if len(partes) != 2:
            raise AuthenticationFailed("La cabecera Authorization está mal formada.")
        try:
            reclamaciones = verificar_acceso(partes[1].decode())
            # PyJWT ya exige que sub sea texto; ademas tiene que ser un uuid.
            usuario_id = uuid.UUID(reclamaciones["sub"])
        except ImproperlyConfigured as error:
            raise ClavesNoConfiguradas(str(error)) from error
        except jwt.ExpiredSignatureError as error:
            raise AuthenticationFailed(VENCIDO, code="token_vencido") from error
        except (jwt.InvalidTokenError, ValueError) as error:
            # ValueError: sub no es un uuid, o la cabecera trae bytes que no son
            # texto (UnicodeDecodeError).
            raise AuthenticationFailed(INVALIDO, code="token_invalido") from error

        # Solo un true de JSON da permisos de administrador.
        usuario = UsuarioDelToken(
            usuario_id=usuario_id, es_admin=reclamaciones.get("es_admin") is True
        )
        return usuario, reclamaciones

    def authenticate_header(self, request):
        # Con esto DRF responde 401 (y no 403) cuando falta el token.
        return 'Bearer realm="tutoring"'
