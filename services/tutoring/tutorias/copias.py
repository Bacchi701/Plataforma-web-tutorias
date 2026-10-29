"""Copias de lectura de Tutorias (AD-07): usuario_ref y asignatura_ref.

- T-166: usuario_ref nace en el primer contacto del usuario con Tutorias (hoy,
  declarar una asignatura, HU-14) y se pone al dia en cada contacto, con lo
  que responde Identidad a GET /yo (llamadas.py). No toca la reputacion.
- El nivel no se copia (A-11): RN-01 lo usa en el momento.
- HU-41: cuando el usuario abre o guarda «Mi perfil», la pagina pide POST
  /yo/refrescar y la copia se pone al dia, si existe. Si no existe, no se
  crea: nace con el primer contacto (M-09 del anexo A).
- asignatura_ref se crea o se pone al dia con lo que trae Catalogo cuando se
  declara o se reactiva una asignatura (perfiles.py).
"""

import logging

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .llamadas import IDENTIDAD, CuentaInactiva, datos_del_usuario, no_disponible
from .models import AsignaturaRef, UsuarioRef

logger = logging.getLogger(__name__)


def datos_de_identidad(request):
    """Lo que dice Identidad del usuario del token (una llamada a GET /yo)."""
    usuario_id = request.user.usuario_id
    try:
        datos = datos_del_usuario(request.META.get("HTTP_AUTHORIZATION", ""))
    except CuentaInactiva:
        # RN-08: sale de la busqueda y de su perfil publico de inmediato.
        UsuarioRef.objects.filter(usuario_id=usuario_id).update(activo=False)
        raise
    if datos["id"] != usuario_id:
        # No deberia pasar: Identidad y Tutorias leen el mismo token.
        logger.error(
            "GET /yo respondió %s para el token de %s", datos["id"], usuario_id
        )
        raise no_disponible(IDENTIDAD)
    return datos


def campos_de_la_copia(datos):
    return {
        "nombre": datos["nombre"],
        "apellido": datos["apellido"],
        "carrera_id": datos["carrera_id"],
        "sede_id": datos["sede_id"],
        # Identidad solo responde /yo a una cuenta activa.
        "activo": True,
        "actualizado_en": timezone.now(),
    }


def asegurar_usuario_ref(request):
    """Crea o pone al dia la copia del usuario del token (T-166).

    Una sola llamada a Identidad. Devuelve (usuario_ref, nivel).
    """
    datos = datos_de_identidad(request)
    usuario, _ = UsuarioRef.objects.update_or_create(
        usuario_id=request.user.usuario_id, defaults=campos_de_la_copia(datos)
    )
    return usuario, datos["nivel"]


def refrescar_usuario_ref(request):
    """Pone al dia la copia, si existe (HU-41). Devuelve si la actualizo.

    Si no existe, no llama a Identidad y no la crea (criterio 2).
    """
    copia = UsuarioRef.objects.filter(usuario_id=request.user.usuario_id)
    if not copia.exists():
        return False
    datos = datos_de_identidad(request)
    return copia.update(**campos_de_la_copia(datos)) > 0


def copiar_asignatura(asignatura_id, datos):
    """Crea o pone al dia asignatura_ref con la sigla y el nombre de Catalogo."""
    asignatura, _ = AsignaturaRef.objects.update_or_create(
        asignatura_id=asignatura_id,
        defaults={
            "sigla": datos["sigla"],
            "nombre": datos["nombre"],
            "actualizado_en": timezone.now(),
        },
    )
    return asignatura


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def refrescar(request):
    """POST /yo/refrescar: la copia toma el nombre y la carrera de Identidad (HU-41)."""
    return Response({"actualizada": refrescar_usuario_ref(request)})
