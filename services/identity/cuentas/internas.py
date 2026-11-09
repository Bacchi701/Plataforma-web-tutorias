"""Vistas internas de Identidad (Pilar 2, seccion 5.4).

Se comunican exclusivamente dentro de la red de Docker autenticadas con
la cabecera X-Clave-Servicio.
"""

import hmac
import uuid

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
from .vistas import Rechazo


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


def usuario_json(usuario):
    """Los siete campos de un usuario en las rutas internas.

    Nunca el correo, el hash de la clave ni es_admin (RNF-07).
    """
    return {
        "id": str(usuario.id),
        "nombre": usuario.nombre,
        "apellido": usuario.apellido,
        "carrera_id": str(usuario.carrera_id) if usuario.carrera_id else None,
        "nivel": usuario.nivel,
        "sede_id": str(usuario.sede_id) if usuario.sede_id else None,
        "activo": usuario.activo,
    }


@api_view(["GET"])
@authentication_classes([])
@permission_classes([ClaveDeServicio])
def un_usuario(request, usuario_id):
    """Consulta interna de los datos de un usuario por su UUID."""
    try:
        usuario = Usuario.objects.get(id=usuario_id)
    except Usuario.DoesNotExist:
        raise NotFound("El usuario no existe.", code="usuario_no_encontrado") from None

    return Response(usuario_json(usuario))


@api_view(["GET"])
@authentication_classes([])
@permission_classes([ClaveDeServicio])
def varios_usuarios(request):
    """GET /internal/usuarios?ids=<uuid>,<uuid>,... (HU-19, ajuste A-01).

    Los datos de hasta 100 usuarios en una sola consulta, para la
    sincronizacion de las copias de Tutorias. Los ids van separados por comas
    en un solo parametro: se ignoran los espacios y las partes vacias, y un id
    repetido cuenta una vez. Los que no existen no salen, asi que la lista
    puede venir mas corta, o vacia. Una cuenta desactivada sale con activo
    false. Ordenada por id.
    """
    invalidos = "Indica los usuarios en ?ids=, separados por comas."
    ids = set()
    for parte in request.query_params.get("ids", "").split(","):
        texto = parte.strip()
        if not texto:
            continue
        try:
            ids.add(uuid.UUID(texto))
        except ValueError:
            raise Rechazo(invalidos, "ids_invalidos") from None
    if not ids:
        raise Rechazo(invalidos, "ids_invalidos")
    # Tutorias pide de a 50.
    if len(ids) > 100:
        raise Rechazo("Pide hasta 100 usuarios por llamada.", "demasiados_ids")

    usuarios = Usuario.objects.filter(id__in=ids).order_by("id")
    return Response([usuario_json(usuario) for usuario in usuarios])
