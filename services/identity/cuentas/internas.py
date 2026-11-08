"""Vistas internas de Identidad (Pilar 2, seccion 5.4).

Se comunican exclusivamente dentro de la red de Docker autenticadas con
la cabecera X-Clave-Servicio.
"""

import hmac

from django.conf import settings
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from .models import Usuario


class ClaveDeServicio(BasePermission):
    """Permiso para rutas internas entre servicios."""

    def has_permission(self, request, view):
        esperada = getattr(settings, "CLAVE_SERVICIO", "") or ""
        recibida = request.headers.get("X-Clave-Servicio", "") or ""

        if not esperada or not recibida:
            raise NotFound("Ruta no encontrada.", code="ruta_no_encontrada")

        try:
            valida = hmac.compare_digest(recibida.encode(), esperada.encode())
        except Exception:
            valida = False

        if not valida:
            raise NotFound("Ruta no encontrada.", code="ruta_no_encontrada")

        return True


@api_view(["GET"])
@authentication_classes([])
@permission_classes([ClaveDeServicio])
def un_usuario(request, usuario_id):
    """Consulta interna de los datos de un usuario por su UUID."""
    try:
        usuario = Usuario.objects.get(id=usuario_id)
    except Usuario.DoesNotExist:
        raise NotFound("El usuario no existe.", code="usuario_no_encontrado") from None

    return Response(
        {
            "id": str(usuario.id),
            "nombre": usuario.nombre,
            "apellido": usuario.apellido,
            "carrera_id": str(usuario.carrera_id) if usuario.carrera_id else None,
            "nivel": usuario.nivel,
            "sede_id": str(usuario.sede_id) if usuario.sede_id else None,
            "activo": usuario.activo,
        }
    )
