from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .bloques import instante_json
from .busqueda import evaluacion_json
from .models import EstadoReserva, Evaluacion, PerfilTutor, Reserva
from .reputacion import recalcular_reputacion

MAXIMO_COMENTARIO = 500
RESTRICCION_EVALUACION_UNICA = "evaluacion_reserva_id_key"
# GET /tutores/<id>/evaluaciones: las mas nuevas, hasta este tope.
MAXIMO_EVALUACIONES_DEL_TUTOR = 100


def respuesta_error(estado, codigo, mensaje):
    return Response(
        {"codigo": codigo, "mensaje": mensaje, "detalles": None},
        status=estado,
    )


def cuerpo_json(peticion):
    datos = peticion.data
    if isinstance(datos, dict):
        return datos
    return {}


def leer_calificacion(datos):
    valor = datos.get("calificacion")
    if isinstance(valor, bool) or not isinstance(valor, int) or not (1 <= valor <= 5):
        return None, respuesta_error(
            400,
            "calificacion_invalida",
            "La nota tiene que ser un número entero de 1 a 5.",
        )
    return valor, None


def leer_comentario(datos):
    if "comentario" not in datos or datos.get("comentario") is None:
        return None, None
    valor = datos.get("comentario")
    if not isinstance(valor, str):
        return None, respuesta_error(
            400,
            "comentario_invalido",
            "El comentario tiene que ser un texto.",
        )
    if "\x00" in valor or any("\ud800" <= c <= "\udfff" for c in valor):
        return None, respuesta_error(
            400,
            "comentario_invalido",
            "El comentario tiene caracteres que no se pueden guardar.",
        )
    limpio = valor.strip()
    if len(limpio) > MAXIMO_COMENTARIO:
        return None, respuesta_error(
            400,
            "comentario_invalido",
            f"El comentario puede tener hasta {MAXIMO_COMENTARIO} caracteres.",
        )
    return (limpio or None), None


def es_evaluacion_duplicada(error):
    causa = error.__cause__
    diagnostico = getattr(causa, "diag", None)
    nombre = getattr(diagnostico, "constraint_name", None)
    if nombre is not None:
        return nombre == RESTRICCION_EVALUACION_UNICA
    return RESTRICCION_EVALUACION_UNICA in str(error)


def evaluacion_registrada_json(evaluacion):
    return {
        "id": str(evaluacion.id),
        "reserva_id": str(evaluacion.reserva_id),
        "calificacion": evaluacion.calificacion,
        "comentario": evaluacion.comentario,
        "creada_en": instante_json(evaluacion.creada_en),
    }


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def evaluar(peticion, reserva_id):
    datos = cuerpo_json(peticion)

    calificacion, error = leer_calificacion(datos)
    if error is not None:
        return error

    comentario, error = leer_comentario(datos)
    if error is not None:
        return error

    usuario_id = peticion.user.usuario_id
    ahora = timezone.now()

    with transaction.atomic():
        reserva = (
            Reserva.objects.select_for_update(of=("self",))
            .select_related("bloque")
            .filter(pk=reserva_id)
            .first()
        )
        if reserva is None or usuario_id not in (
            reserva.solicitante_usuario_id,
            reserva.bloque.usuario_id,
        ):
            return respuesta_error(
                404,
                "reserva_no_encontrada",
                "No encontramos esa tutoría.",
            )

        if usuario_id == reserva.bloque.usuario_id:
            return respuesta_error(
                403,
                "solo_el_solicitante",
                "Solo quien pidió la tutoría puede evaluarla.",
            )

        if (
            reserva.estado == EstadoReserva.EVALUADA
            or Evaluacion.objects.filter(reserva_id=reserva.id).exists()
        ):
            return respuesta_error(
                409,
                "reserva_ya_evaluada",
                "Ya evaluaste esta tutoría.",
            )

        if reserva.estado != EstadoReserva.REALIZADA:
            return respuesta_error(
                409,
                "reserva_no_realizada",
                "Solo se puede evaluar una tutoría realizada.",
            )

        if reserva.bloque.fin_en > ahora:
            return respuesta_error(
                409,
                "tutoria_no_terminada",
                "Podrás evaluarla cuando termine la tutoría.",
            )

        try:
            with transaction.atomic():
                evaluacion = Evaluacion.objects.create(
                    reserva=reserva,
                    calificacion=calificacion,
                    comentario=comentario,
                )
        except IntegrityError as exc:
            if es_evaluacion_duplicada(exc):
                return respuesta_error(
                    409,
                    "reserva_ya_evaluada",
                    "Ya evaluaste esta tutoría.",
                )
            raise

        reserva.estado = EstadoReserva.EVALUADA
        reserva.cerrada_en = ahora
        reserva.save(update_fields=["estado", "cerrada_en"])

        recalcular_reputacion(reserva.bloque.usuario_id)

    return Response(evaluacion_registrada_json(evaluacion), status=201)


@api_view(["GET"])
def del_tutor(peticion, usuario_id):
    """Evaluaciones visibles de un tutor (HU-25, criterio 4). No pide sesion.

    Cada una con evaluacion_json de busqueda.py, el formato del perfil publico:
    sin datos de quien evaluo. No recalcula la reputacion: esta en
    GET /tutores/<id>.
    """
    # El mismo 404 que perfil_publico: el usuario no esta en Tutorias, su
    # cuenta esta desactivada (RN-08) o no tiene perfiles activos.
    tutor_activo = PerfilTutor.objects.filter(
        usuario_id=usuario_id, activo=True, usuario__activo=True
    ).exists()
    if not tutor_activo:
        raise NotFound("No existe un tutor activo con ese identificador.")

    # El tutor evaluado es el dueno del bloque de la reserva (3FN). Las
    # retiradas por el administrador no salen (CA7). Una sola consulta:
    # select_related trae la reserva y su asignatura.
    evaluaciones = (
        Evaluacion.objects.filter(
            reserva__bloque__usuario_id=usuario_id, retirada_en__isnull=True
        )
        .select_related("reserva__asignatura")
        .order_by("-creada_en", "id")[:MAXIMO_EVALUACIONES_DEL_TUTOR]
    )
    return Response([evaluacion_json(evaluacion) for evaluacion in evaluaciones])
