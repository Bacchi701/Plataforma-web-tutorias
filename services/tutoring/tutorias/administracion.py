"""Rutas del panel de administracion en Tutorias (HU-33, parte 1; AD-09).

GET /admin/reservas y DELETE /admin/evaluaciones/<id>. Responden solo a un
token con es_admin: sin token, 401, como las demas rutas con sesion; con un
token sin la marca, 403 no_es_administrador. La marca sale del token
(UsuarioDelToken.es_admin, HU-17), sin consultar a Identidad. La pantalla del
panel llega en la parte 2.

- Todo sale de tutoring_db, sin llamar a otros servicios (AD-07). Ninguna
  respuesta trae correos (no estan en esta base), la nota del estudiante ni el
  lugar o enlace de la tutoria: no hacen falta para administrar (RNF-07).
- Retirar una evaluacion no borra la fila: escribe retirada_en y
  retirada_por_usuario_id (la base exige los dos juntos, ck_evaluacion_retiro)
  y recalcula la reputacion del tutor con recalcular_reputacion (HU-25), en la
  misma transaccion. La reserva sigue EVALUADA (anexo A, seccion 9).

No se llama admin.py: en Django ese nombre es del panel de Django, que este
proyecto no usa (AD-09).
"""

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from .bloques import Rechazo, instante_json
from .models import EstadoReserva, Evaluacion, Reserva
from .reputacion import recalcular_reputacion

# Lo que cabe en el panel: las mas nuevas.
MAXIMO_RESERVAS = 100

ESTADO_INVALIDO = (
    "El estado tiene que ser uno de estos: SOLICITADA, CONFIRMADA, RECHAZADA, "
    "EXPIRADA, CANCELADA, REALIZADA o EVALUADA."
)
EVALUACION_NO_ENCONTRADA = "No existe una evaluación con ese identificador."
EVALUACION_YA_RETIRADA = "Esa evaluación ya estaba retirada."


class EsAdministrador(BasePermission):
    """Solo un token con es_admin (AD-09). Va despues de IsAuthenticated.

    DRF responde 403 con este mensaje y este codigo, en el formato uniforme.
    """

    message = "Esta sección es solo para administradores."
    code = "no_es_administrador"

    def has_permission(self, request, view):
        # La marca es la del token: Tutorias no le pregunta a Identidad.
        return getattr(request.user, "es_admin", False) is True


def estado_pedido(request):
    """El estado de ?estado=, o None si no viene (criterio 3).

    Si viene, tiene que ser uno de los siete de EstadoReserva, tal cual y en
    mayusculas. Vacio (?estado=) tambien es un estado invalido.
    """
    if "estado" not in request.query_params:
        return None
    estado = request.query_params["estado"]
    if estado not in EstadoReserva.values:
        raise Rechazo(ESTADO_INVALIDO, "estado_invalido")
    return estado


def instante_o_nulo(valor):
    """Las fechas que pueden faltar: en UTC con Z, o None."""
    return None if valor is None else instante_json(valor)


def texto_o_nulo(identificador):
    """Un identificador que puede faltar, como texto."""
    return None if identificador is None else str(identificador)


def persona_json(usuario):
    """Nombre y apellido de usuario_ref. El correo no esta en esta base."""
    return {
        "usuario_id": str(usuario.usuario_id),
        "nombre": usuario.nombre,
        "apellido": usuario.apellido,
    }


def evaluacion_administrada_json(evaluacion):
    """Lo que necesita el panel para retirar una evaluacion (criterio 4)."""
    return {
        "id": str(evaluacion.id),
        "calificacion": evaluacion.calificacion,
        "comentario": evaluacion.comentario,
        "creada_en": instante_json(evaluacion.creada_en),
        "retirada_en": instante_o_nulo(evaluacion.retirada_en),
    }


def evaluacion_de(reserva):
    """La evaluacion de la reserva en el formato del panel, o None si no tiene.

    La trajo select_related. Sin evaluacion, el acceso inverso lanza
    DoesNotExist sin consultar la base: select_related ya dejo anotado que no
    hay.
    """
    try:
        evaluacion = reserva.evaluacion
    except Evaluacion.DoesNotExist:
        return None
    return evaluacion_administrada_json(evaluacion)


def reserva_administrada_json(reserva):
    """Una reserva del panel, sin nota ni lugar o enlace (RNF-07)."""
    bloque = reserva.bloque
    asignatura = reserva.asignatura
    return {
        "id": str(reserva.id),
        "estado": reserva.estado,
        "asignatura": {
            "asignatura_id": str(asignatura.asignatura_id),
            "sigla": asignatura.sigla,
            "nombre": asignatura.nombre,
        },
        # El tutor es el dueno del bloque (3FN).
        "tutor": persona_json(bloque.usuario),
        "solicitante": persona_json(reserva.solicitante_usuario),
        "bloque": {
            "id": str(bloque.id),
            "inicio_en": instante_json(bloque.inicio_en),
            "fin_en": instante_json(bloque.fin_en),
        },
        "monto": int(reserva.monto),
        "estado_pago": reserva.estado_pago,
        "creada_en": instante_json(reserva.creada_en),
        "confirmada_en": instante_o_nulo(reserva.confirmada_en),
        "cerrada_en": instante_o_nulo(reserva.cerrada_en),
        "cancelada_por_usuario_id": texto_o_nulo(reserva.cancelada_por_usuario_id),
        "evaluacion": evaluacion_de(reserva),
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated, EsAdministrador])
def reservas(request):
    """GET /admin/reservas[?estado=]: las reservas, de la mas nueva a la mas antigua.

    Hasta 100, por creada_en y despues por id. Una sola consulta: select_related
    trae el bloque con su tutor, el solicitante, la asignatura y la evaluacion
    (un OneToOne inverso), sin una consulta por reserva. No llama a otros
    servicios.
    """
    estado = estado_pedido(request)
    pedidas = Reserva.objects.select_related(
        "bloque__usuario", "solicitante_usuario", "asignatura", "evaluacion"
    ).order_by("-creada_en", "id")
    if estado is not None:
        pedidas = pedidas.filter(estado=estado)
    return Response([reserva_administrada_json(r) for r in pedidas[:MAXIMO_RESERVAS]])


@api_view(["DELETE"])
@permission_classes([IsAuthenticated, EsAdministrador])
def retirar_evaluacion(request, evaluacion_id):
    """DELETE /admin/evaluaciones/<id>: la evaluacion deja de contar (criterio 4).

    Bloquea la evaluacion y despues, dentro de recalcular_reputacion, la fila
    del tutor en usuario_ref. Evaluar (HU-25) bloquea la reserva y despues esa
    misma fila del tutor: los dos caminos no se cruzan.
    """
    with transaction.atomic():
        evaluacion = (
            Evaluacion.objects.select_for_update(of=("self",))
            .select_related("reserva__bloque")
            .filter(pk=evaluacion_id)
            .first()
        )
        if evaluacion is None:
            raise Rechazo(
                EVALUACION_NO_ENCONTRADA,
                "evaluacion_no_encontrada",
                status.HTTP_404_NOT_FOUND,
            )
        if evaluacion.retirada_en is not None:
            # Sin cambiar cuando ni quien la retiro.
            raise Rechazo(
                EVALUACION_YA_RETIRADA,
                "evaluacion_ya_retirada",
                status.HTTP_409_CONFLICT,
            )
        evaluacion.retirada_en = timezone.now()
        # Referencia logica, sin clave foranea: el administrador no necesita
        # fila en usuario_ref.
        evaluacion.retirada_por_usuario_id = request.user.usuario_id
        evaluacion.save(update_fields=["retirada_en", "retirada_por_usuario_id"])
        # La reserva no cambia: sigue EVALUADA (anexo A, seccion 9).
        recalcular_reputacion(evaluacion.reserva.bloque.usuario_id)
    return Response(status=status.HTTP_204_NO_CONTENT)
