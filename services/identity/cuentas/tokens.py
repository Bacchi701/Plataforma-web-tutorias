"""Token de acceso (HU-05, AD-06 y Pilar 2 seccion 5).

JWT firmado con RS256 que dura 30 minutos. La clave privada vive solo en
Identidad; los demas servicios verifican con la publica. El token de
renovacion no es un JWT: es un texto aleatorio (ver secretos.py).
"""

from datetime import timedelta
from functools import lru_cache
from pathlib import Path

import jwt
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

ALGORITMO = "RS256"


@lru_cache
def leer_clave(ruta):
    archivo = Path(ruta)
    # is_file y no exists: si la ruta es una carpeta, read_text terminaba en
    # un error 500. Pasa si keys/jwt_public.pem no estaba al levantar Tutorias
    # o Pagos: Docker monta en su lugar una carpeta con ese nombre.
    if not archivo.is_file():
        raise ImproperlyConfigured(
            f"No existe {ruta}. Genera las claves con: "
            "python manage.py generar_claves_jwt (ver el RUNBOOK, nivel 3)."
        )
    return archivo.read_text()


def clave_ilegible(ruta):
    """El motivo del 503 cuando el archivo de una clave no es una clave PEM.

    Pasa con un archivo vacio o con otro texto: PyJWT lanza InvalidKeyError,
    que no hereda de InvalidTokenError.
    """
    return (
        f"El archivo {ruta} no es una clave PEM válida. Revísalo o genera las "
        "claves de nuevo con: python manage.py generar_claves_jwt --forzar "
        "(ver el README)."
    )


def emitir_acceso(usuario):
    """Reclamaciones sub, es_admin, iat, exp e iss; sin correo (RNF-07)."""
    ahora = timezone.now()
    reclamaciones = {
        "sub": str(usuario.id),
        "es_admin": usuario.es_admin,
        "iat": int(ahora.timestamp()),
        "exp": int(
            (ahora + timedelta(minutes=settings.JWT_MINUTOS_ACCESO)).timestamp()
        ),
        "iss": settings.JWT_EMISOR,
    }
    return jwt.encode(
        reclamaciones, leer_clave(settings.JWT_CLAVE_PRIVADA), algorithm=ALGORITMO
    )


def verificar_acceso(token):
    """Devuelve las reclamaciones o lanza jwt.InvalidTokenError.

    Si falta la clave publica, leer_clave lanza ImproperlyConfigured; si el
    archivo no es una clave, PyJWT lanza jwt.InvalidKeyError.
    """
    return jwt.decode(
        token,
        leer_clave(settings.JWT_CLAVE_PUBLICA),
        algorithms=[ALGORITMO],
        issuer=settings.JWT_EMISOR,
        options={"require": ["sub", "iat", "exp", "iss"]},
    )
