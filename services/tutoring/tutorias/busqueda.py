"""Busqueda publica de tutores (HU-20 y HU-40, RF-06).

GET /tutores?asignatura=<id> lista los tutores de una asignatura; sin
asignatura lista los tutores mejor evaluados, o los que coinciden con
?buscar= (HU-40). GET /tutores/<id> muestra el perfil publico de uno. No
piden sesion: son datos publicos de busqueda.

Todo sale de tutoring_db, sin llamar a Identidad ni a Catalogo (AD-07):
usuario_ref y asignatura_ref son las copias de lectura, y la reputacion es el
dato que guarda usuario_ref (RN-06). El correo no esta en esta base y ninguna
respuesta lo incluye (RNF-07). La carrera y la sede van como identificador:
sus nombres los pide el frontend a Catalogo.
"""

import unicodedata
import uuid
from decimal import Decimal, InvalidOperation

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import APIException, NotFound
from rest_framework.response import Response

from .models import BloqueDisponibilidad, EstadoBloque, Evaluacion, PerfilTutor

# Topes del perfil publico: lo que cabe en una pantalla.
MAXIMO_BLOQUES = 20
MAXIMO_EVALUACIONES = 10

# Sin asignatura (HU-40): los mejor evaluados que caben en una pantalla, o
# hasta el doble si se busca por nombre.
MAXIMO_DESTACADOS = 24
MAXIMO_POR_NOMBRE = 48
LARGO_MAXIMO_BUSQUEDA = 80


# Errores 400 con codigo propio. Heredan de APIException y no de
# ValidationError porque esta envuelve el mensaje en una lista, y con el
# formato unico (configuracion.errores) el mensaje quedaria generico. Asi sale
# {"codigo": "asignatura_invalida", "mensaje": ..., "detalles": null}.
class AsignaturaInvalida(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "El identificador de la asignatura no es válido."
    default_code = "asignatura_invalida"


class ReputacionInvalida(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "La evaluación mínima tiene que ser un número de 1 a 5."
    default_code = "reputacion_invalida"


class BusquedaInvalida(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = (
        f"Escribe hasta {LARGO_MAXIMO_BUSQUEDA} caracteres para buscar a un tutor."
    )
    default_code = "busqueda_invalida"


def asignatura_pedida(request):
    """La asignatura de ?asignatura=, o None si no viene (HU-40)."""
    texto = request.query_params.get("asignatura", "").strip()
    if not texto:
        return None
    try:
        return uuid.UUID(texto)
    except ValueError as error:
        raise AsignaturaInvalida() from error


def reputacion_pedida(request):
    """La evaluacion minima de ?min_reputacion=, de 1 a 5, o None (HU-40).

    Acepta punto o coma decimal: 4, 4.5 o 4,5.
    """
    texto = request.query_params.get("min_reputacion", "").strip().replace(",", ".")
    if not texto:
        return None
    try:
        valor = Decimal(texto)
    except InvalidOperation as error:
        raise ReputacionInvalida() from error
    if not valor.is_finite() or not Decimal(1) <= valor <= Decimal(5):
        raise ReputacionInvalida()
    return valor


def sin_tildes(texto):
    """Minusculas y sin tildes, para que «matias» encuentre a «Matías»."""
    descompuesto = unicodedata.normalize("NFD", texto.casefold())
    return "".join(letra for letra in descompuesto if not unicodedata.combining(letra))


def palabras_pedidas(request):
    """Las palabras de ?buscar=, sin tildes ni mayusculas (HU-40, criterio 3)."""
    texto = " ".join(request.query_params.get("buscar", "").split())
    if len(texto) > LARGO_MAXIMO_BUSQUEDA:
        raise BusquedaInvalida()
    return sin_tildes(texto).split()


def coincide(usuario, palabras):
    """Cada palabra buscada aparece en el nombre o el apellido."""
    nombre = sin_tildes(f"{usuario.nombre} {usuario.apellido}")
    return all(palabra in nombre for palabra in palabras)


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


def asignatura_resumida(perfil):
    """Una asignatura del tutor en la busqueda sin asignatura (HU-40)."""
    asignatura = perfil.asignatura
    return {
        "asignatura_id": str(asignatura.asignatura_id),
        "sigla": asignatura.sigla,
        "nombre": asignatura.nombre,
        "tarifa": int(perfil.tarifa),
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
    """Tutores con perfil activo (HU-20, criterios 1 y 2; HU-40).

    - Con ?asignatura=, los tutores de esa asignatura, cada uno con su tarifa
      en ella (HU-20).
    - Sin asignatura, un resultado por tutor, con todas sus asignaturas
      activas: los mejor evaluados, o los que coinciden con ?buscar= (HU-40).
    - ?buscar= compara cada palabra con el nombre y el apellido, sin tildes ni
      mayusculas. ?min_reputacion= deja solo a los que tienen esa evaluacion o
      mas; los que todavia no tienen evaluaciones quedan fuera.

    No salen la cuenta desactivada (RN-08, usuario_ref.activo) ni el perfil
    desactivado (RN-01). Una sola consulta: select_related trae el usuario y
    la asignatura de cada perfil, sin una consulta por tutor. El nombre se
    compara en Python porque tutoring_db no tiene la extension unaccent, y los
    tutores activos son pocos (RNF-02 mide con 500 usuarios).
    """
    asignatura_id = asignatura_pedida(request)
    minimo = reputacion_pedida(request)
    palabras = palabras_pedidas(request)

    perfiles = PerfilTutor.objects.filter(
        activo=True, usuario__activo=True
    ).select_related("usuario", "asignatura")
    if asignatura_id is not None:
        perfiles = perfiles.filter(asignatura_id=asignatura_id)
    if minimo is not None:
        perfiles = perfiles.filter(
            usuario__reputacion_total__gt=0, usuario__reputacion_promedio__gte=minimo
        )

    reputacion = ("-usuario__reputacion_promedio", "-usuario__reputacion_total")
    # Desempate estable entre tutores con la misma reputacion.
    desempate = ("usuario__nombre", "usuario__apellido", "usuario_id")
    if asignatura_id is not None:
        perfiles = perfiles.order_by(*reputacion, "tarifa", *desempate)
    else:
        perfiles = perfiles.order_by(
            *reputacion, *desempate, "asignatura__sigla", "asignatura_id"
        )

    if palabras:
        perfiles = [perfil for perfil in perfiles if coincide(perfil.usuario, palabras)]

    if asignatura_id is not None:
        return Response([resultado_json(perfil) for perfil in perfiles])

    tutores = {}
    for perfil in perfiles:
        tutor = tutores.get(perfil.usuario_id)
        if tutor is None:
            tutor = tutores[perfil.usuario_id] = {
                **datos_del_tutor(perfil.usuario),
                "reputacion": reputacion_json(perfil.usuario),
                "asignaturas": [],
            }
        tutor["asignaturas"].append(asignatura_resumida(perfil))
    tope = MAXIMO_POR_NOMBRE if palabras else MAXIMO_DESTACADOS
    return Response(list(tutores.values())[:tope])


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
