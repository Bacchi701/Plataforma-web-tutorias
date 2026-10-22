"""Busqueda publica de tutores (HU-20, RF-06).

GET /tutores?asignatura=<id> lista los tutores de una asignatura y
GET /tutores/<id> muestra el perfil publico de uno. No piden sesion: son
datos publicos de busqueda.

Todo sale de tutoring_db, sin llamar a Identidad ni a Catalogo (AD-07):
usuario_ref y asignatura_ref son las copias de lectura, y la reputacion es el
dato que guarda usuario_ref (RN-06). El correo no esta en esta base y ninguna
respuesta lo incluye (RNF-07). La carrera y la sede van como identificador:
sus nombres los pide el frontend a Catalogo.
"""

import uuid

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import APIException, NotFound
from rest_framework.response import Response

from .models import BloqueDisponibilidad, EstadoBloque, Evaluacion, PerfilTutor

# Topes del perfil publico: lo que cabe en una pantalla.
MAXIMO_BLOQUES = 20
MAXIMO_EVALUACIONES = 10


# Errores 400 con codigo propio. Heredan de APIException y no de
# ValidationError porque esta envuelve el mensaje en una lista, y con el
# formato unico (configuracion.errores, llega con HU-17) el mensaje quedaria
# generico. Asi sale {"codigo": "asignatura_requerida", "mensaje": ...}; hasta
# entonces DRF responde {"detail": ...} con el mismo estado 400.
class AsignaturaRequerida(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Indica la asignatura con ?asignatura=<identificador>."
    default_code = "asignatura_requerida"


class AsignaturaInvalida(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "El identificador de la asignatura no es válido."
    default_code = "asignatura_invalida"


def asignatura_pedida(request):
    texto = request.query_params.get("asignatura", "").strip()
    if not texto:
        raise AsignaturaRequerida()
    try:
        return uuid.UUID(texto)
    except ValueError as error:
        raise AsignaturaInvalida() from error


def identificador(valor):
    """Los identificadores van como texto; carrera y sede pueden faltar."""
    return None if valor is None else str(valor)


def datos_del_tutor(usuario):
    """Lo publico de usuario_ref. No hay correo que excluir: no esta aqui."""
    return {
        "usuario_id": str(usuario.usuario_id),
        "nombre": usuario.nombre,
        "apellido": usuario.apellido,
        "carrera_id": identificador(usuario.carrera_id),
        "sede_id": identificador(usuario.sede_id),
    }


def reputacion_json(usuario):
    return {
        "promedio": float(usuario.reputacion_promedio),
        "total": usuario.reputacion_total,
    }


def resultado_json(perfil):
    """Un tutor de la busqueda, con su tarifa en esa asignatura."""
    asignatura = perfil.asignatura
    return {
        **datos_del_tutor(perfil.usuario),
        "asignatura": {
            "asignatura_id": str(asignatura.asignatura_id),
            "sigla": asignatura.sigla,
            "nombre": asignatura.nombre,
        },
        "tarifa": int(perfil.tarifa),
        "descripcion": perfil.descripcion,
        "reputacion": reputacion_json(perfil.usuario),
    }


def asignatura_del_perfil(perfil):
    asignatura = perfil.asignatura
    return {
        "asignatura_id": str(asignatura.asignatura_id),
        "sigla": asignatura.sigla,
        "nombre": asignatura.nombre,
        "tarifa": int(perfil.tarifa),
        "descripcion": perfil.descripcion,
    }


def bloque_json(bloque):
    # DRF escribe las fechas en ISO 8601 con zona: se guardan en UTC y el
    # navegador las muestra en hora de Chile.
    return {
        "id": str(bloque.id),
        "inicio_en": bloque.inicio_en,
        "fin_en": bloque.fin_en,
    }


def evaluacion_json(evaluacion):
    # Sin datos de quien evaluo: el perfil publico muestra solo la opinion.
    asignatura = evaluacion.reserva.asignatura
    return {
        "calificacion": evaluacion.calificacion,
        "comentario": evaluacion.comentario,
        "creada_en": evaluacion.creada_en,
        "asignatura": {"sigla": asignatura.sigla, "nombre": asignatura.nombre},
    }


@api_view(["GET"])
def buscar_tutores(request):
    """Tutores con perfil activo en la asignatura (HU-20, criterios 1 y 2).

    No salen la cuenta desactivada (RN-08, usuario_ref.activo) ni el perfil
    desactivado (RN-01). Una sola consulta: select_related trae el usuario y
    la asignatura de cada perfil, sin una consulta por tutor.
    """
    asignatura_id = asignatura_pedida(request)
    perfiles = (
        PerfilTutor.objects.filter(
            asignatura_id=asignatura_id, activo=True, usuario__activo=True
        )
        .select_related("usuario", "asignatura")
        .order_by(
            "-usuario__reputacion_promedio",
            "-usuario__reputacion_total",
            "tarifa",
            # Desempate estable entre tutores con la misma reputacion y tarifa.
            "usuario__nombre",
            "usuario__apellido",
            "usuario_id",
        )
    )
    return Response([resultado_json(perfil) for perfil in perfiles])


@api_view(["GET"])
def perfil_publico(request, usuario_id):
    """Perfil publico del tutor con su reputacion (HU-20, criterio 3)."""
    # El mismo filtro cubre los tres casos del 404: el usuario no existe, su
    # cuenta esta desactivada (RN-08) o no tiene perfiles activos.
    perfiles = list(
        PerfilTutor.objects.filter(
            usuario_id=usuario_id, activo=True, usuario__activo=True
        )
        .select_related("usuario", "asignatura")
        .order_by("asignatura__sigla")
    )
    if not perfiles:
        raise NotFound("No existe un tutor activo con ese identificador.")
    usuario = perfiles[0].usuario

    bloques = BloqueDisponibilidad.objects.filter(
        usuario=usuario, estado=EstadoBloque.LIBRE, inicio_en__gt=timezone.now()
    ).order_by("inicio_en")[:MAXIMO_BLOQUES]

    # El tutor evaluado es el dueno del bloque de la reserva (3FN). Las
    # evaluaciones retiradas por el administrador no se muestran (CA7).
    evaluaciones = (
        Evaluacion.objects.filter(
            reserva__bloque__usuario=usuario, retirada_en__isnull=True
        )
        .select_related("reserva__asignatura")
        .order_by("-creada_en", "id")[:MAXIMO_EVALUACIONES]
    )

    cuerpo = {
        **datos_del_tutor(usuario),
        "reputacion": reputacion_json(usuario),
        "asignaturas": [asignatura_del_perfil(perfil) for perfil in perfiles],
        "bloques": [bloque_json(bloque) for bloque in bloques],
        "evaluaciones": [evaluacion_json(e) for e in evaluaciones],
    }
    return Response(cuerpo)
