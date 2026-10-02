"""Autenticacion con el token de acceso (Pilar 2, seccion 5.1, paso 4)."""

import jwt
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from .models import Usuario
from .tokens import verificar_acceso


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
        except jwt.ExpiredSignatureError as error:
            raise AuthenticationFailed(
                "El token de acceso venció.", code="token_vencido"
            ) from error
        except jwt.InvalidTokenError as error:
            raise AuthenticationFailed(
                "El token de acceso no es válido.", code="token_invalido"
            ) from error

        usuario = Usuario.objects.filter(id=reclamaciones["sub"], activo=True).first()
        if usuario is None:
            raise AuthenticationFailed(
                "La cuenta no existe o está desactivada.", code="cuenta_inactiva"
            )
        return usuario, reclamaciones

    def authenticate_header(self, request):
        # Con esto DRF responde 401 (y no 403) cuando falta el token.
        return 'Bearer realm="identity"'
