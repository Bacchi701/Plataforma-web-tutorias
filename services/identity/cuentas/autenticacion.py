"""Autenticacion con el token de acceso (Pilar 2, seccion 5.1, paso 4)."""

import uuid

import jwt
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from rest_framework import status
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import APIException, AuthenticationFailed

from .models import Usuario
from .tokens import clave_ilegible, verificar_acceso


class ClavesNoConfiguradas(APIException):
    """Falta la clave publica o no se puede leer: 503 con el motivo.

    Es el mismo codigo que responde /login cuando falta la clave privada, y el
    mismo de Tutorias y Pagos.
    """

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
        except jwt.InvalidKeyError as error:
            raise ClavesNoConfiguradas(
                clave_ilegible(settings.JWT_CLAVE_PUBLICA)
            ) from error
        except jwt.ExpiredSignatureError as error:
            raise AuthenticationFailed(
                "El token de acceso venció.", code="token_vencido"
            ) from error
        except (jwt.InvalidTokenError, ValueError) as error:
            # ValueError: sub no es un uuid, o la cabecera trae bytes que no son
            # texto (UnicodeDecodeError).
            raise AuthenticationFailed(
                "El token de acceso no es válido.", code="token_invalido"
            ) from error

        usuario = Usuario.objects.filter(id=usuario_id, activo=True).first()
        if usuario is None:
            raise AuthenticationFailed(
                "La cuenta no existe o está desactivada.", code="cuenta_inactiva"
            )
        return usuario, reclamaciones

    def authenticate_header(self, request):
        # Con esto DRF responde 401 (y no 403) cuando falta el token.
        return 'Bearer realm="identity"'
