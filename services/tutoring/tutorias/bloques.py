"""Bloques de disponibilidad del tutor (HU-15, RF-05).

GET y POST /disponibilidad, PATCH y DELETE /disponibilidad/<id>, todo con
sesion: el usuario del token (HU-17) solo ve y cambia sus propios bloques.

- Publicar o editar exige ser tutor: estar activo en usuario_ref y tener al
  menos un perfil activo. Ver y borrar los propios bloques no lo exige, para
  que quien deja de ser tutor pueda retirar lo que publico.
- RN-02: el solape lo rechaza la base (EXCLUDE ex_bloque_sin_solape), no el
  codigo. Aqui solo se traduce ese rechazo a un 409.
- Las fechas llegan en ISO 8601 con zona, se guardan en UTC y salen en UTC
  con Z. La pagina las muestra en hora de Chile (criterio 6, RNF-08).
"""

from datetime import UTC

from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import APIException, NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import (
    ESTADOS_QUE_OCUPAN,
    BloqueDisponibilidad,
    EstadoBloque,
    EstadoReserva,
    PerfilTutor,
    UsuarioRef,
)

RESTRICCION_SOLAPE = "ex_bloque_sin_solape"
EJEMPLO_FECHA = "2026-12-01T20:00:00-03:00"

NO_ES_TUTOR = (
    "Para publicar bloques de disponibilidad, primero declara al menos una "
    "asignatura que puedas enseñar."
)
SOLAPADO = "El bloque se cruza con otro de tus bloques. Elige otro horario."
CON_SOLICITUDES = (
    "El bloque tiene solicitudes pendientes y no se puede editar. Si lo "
    "eliminas, esas solicitudes quedan rechazadas."
)
CON_RESERVA = "El bloque tiene una tutoría confirmada: no se puede editar ni eliminar."


class Rechazo(APIException):
    """Error con codigo propio, en el formato uniforme de la API."""

    def __init__(self, mensaje, codigo, estado=status.HTTP_400_BAD_REQUEST):
        self.status_code = estado
        super().__init__(detail=mensaje, code=codigo)


def instante_json(valor):
    """ISO 8601 en UTC y con Z, por ejemplo 2026-12-01T23:00:00Z."""
    return valor.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def bloque_json(bloque, solicitudes_pendientes):
    return {
        "id": str(bloque.id),
        "inicio_en": instante_json(bloque.inicio_en),
        "fin_en": instante_json(bloque.fin_en),
        "estado": bloque.estado,
        "solicitudes_pendientes": solicitudes_pendientes,
    }


def tutor_con_sesion(request):
    """El usuario del token, si es tutor: activo y con un perfil activo."""
    perfil_activo = PerfilTutor.objects.filter(usuario=OuterRef("pk"), activo=True)
    tutor = (
        UsuarioRef.objects.filter(usuario_id=request.user.usuario_id, activo=True)
        .filter(Exists(perfil_activo))
        .first()
    )
    if tutor is None:
        raise Rechazo(NO_ES_TUTOR, "no_es_tutor", status.HTTP_403_FORBIDDEN)
    return tutor


def fecha_invalida(nombre):
    return Rechazo(
        f"La fecha de {nombre} tiene que ir en ISO 8601, por ejemplo {EJEMPLO_FECHA}.",
        "fecha_invalida",
    )


def leer_instante(datos, campo, nombre, actual):
    """Un instante del cuerpo, con zona, pasado a UTC.

    Si el campo no viene y hay un valor actual (PATCH), se conserva ese.
    """
    if campo not in datos and actual is not None:
        return actual
    texto = datos.get(campo)
    try:
        instante = parse_datetime(texto) if isinstance(texto, str) else None
    except ValueError:
        instante = None
    if instante is None:
        raise fecha_invalida(nombre)
    if timezone.is_naive(instante):
        raise Rechazo(
            f"La fecha de {nombre} tiene que indicar la zona horaria, por ejemplo "
            f"{EJEMPLO_FECHA}.",
            "zona_horaria_requerida",
        )
    try:
        return instante.astimezone(UTC)
    except OverflowError as error:
        # Una fecha en el limite (0001 o 9999) con desfase se sale del rango.
        raise fecha_invalida(nombre) from error


def fechas_validas(datos, bloque=None):
    """inicio_en y fin_en del cuerpo, ya validados (criterios 1 y 2)."""
    if not isinstance(datos, dict):
        datos = {}
    inicio = leer_instante(
        datos, "inicio_en", "inicio", bloque.inicio_en if bloque else None
    )
    fin = leer_instante(datos, "fin_en", "término", bloque.fin_en if bloque else None)
    if fin <= inicio:
        raise Rechazo(
            "La hora de término tiene que ser posterior a la de inicio.",
            "fin_antes_de_inicio",
        )
    if inicio <= timezone.now():
        raise Rechazo(
            "El bloque empieza en el pasado: elige una fecha y una hora futuras.",
            "bloque_en_el_pasado",
        )
    return inicio, fin


def guardar_sin_solape(bloque, campos=None):
    """Guarda el bloque. Si la base lo rechaza por RN-02, responde 409."""
    try:
        with transaction.atomic():
            bloque.save(update_fields=campos)
    except IntegrityError as error:
        diagnostico = getattr(error.__cause__, "diag", None)
        if getattr(diagnostico, "constraint_name", None) != RESTRICCION_SOLAPE:
            raise
        raise Rechazo(SOLAPADO, "bloque_solapado", status.HTTP_409_CONFLICT) from error


def bloque_propio(request, bloque_id):
    """El bloque del usuario del token, bloqueado hasta el fin de la transaccion.

    Uno de otro usuario, uno eliminado o uno que no existe dan el mismo 404,
    para no revelar que existe.
    """
    bloque = (
        BloqueDisponibilidad.objects.select_for_update()
        .filter(id=bloque_id, usuario_id=request.user.usuario_id)
        .exclude(estado=EstadoBloque.ELIMINADO)
        .first()
    )
    if bloque is None:
        raise NotFound("No tienes un bloque con ese identificador.")
    return bloque


def tiene_reserva_que_ocupa(bloque):
    """Confirmada, realizada o evaluada (ajuste A-03)."""
    return (
        bloque.estado == EstadoBloque.OCUPADO
        or bloque.reservas.filter(estado__in=ESTADOS_QUE_OCUPAN).exists()
    )


def listar(request):
    """Bloques no eliminados que todavia no terminan, del mas proximo al mas lejano.

    La cantidad de solicitudes pendientes sale en la misma consulta (sin N+1).
    """
    bloques = (
        BloqueDisponibilidad.objects.filter(
            usuario_id=request.user.usuario_id, fin_en__gt=timezone.now()
        )
        .exclude(estado=EstadoBloque.ELIMINADO)
        .annotate(
            solicitudes_pendientes=Count(
                "reservas", filter=Q(reservas__estado=EstadoReserva.SOLICITADA)
            )
        )
        .order_by("inicio_en")
    )
    return Response([bloque_json(b, b.solicitudes_pendientes) for b in bloques])


def publicar(request):
    """Criterios 1 y 2: el bloque nace LIBRE si es futuro y no se solapa."""
    tutor = tutor_con_sesion(request)
    inicio, fin = fechas_validas(request.data)
    bloque = BloqueDisponibilidad(usuario=tutor, inicio_en=inicio, fin_en=fin)
    guardar_sin_solape(bloque)
    return Response(bloque_json(bloque, 0), status=status.HTTP_201_CREATED)


def editar(request, bloque_id):
    """Criterio 3: solo un bloque libre y sin solicitudes pendientes."""
    tutor_con_sesion(request)
    with transaction.atomic():
        bloque = bloque_propio(request, bloque_id)
        if tiene_reserva_que_ocupa(bloque):
            raise Rechazo(
                CON_RESERVA, "bloque_con_reserva_confirmada", status.HTTP_409_CONFLICT
            )
        if bloque.reservas.filter(estado=EstadoReserva.SOLICITADA).exists():
            raise Rechazo(
                CON_SOLICITUDES, "bloque_con_solicitudes", status.HTTP_409_CONFLICT
            )
        bloque.inicio_en, bloque.fin_en = fechas_validas(request.data, bloque)
        guardar_sin_solape(bloque, ["inicio_en", "fin_en", "actualizado_en"])
    return Response(bloque_json(bloque, 0))


def eliminar(request, bloque_id):
    """Criterios 3, 4 y 5.

    Con una reserva que ocupa el bloque, no se borra. Las solicitudes
    pendientes pasan a RECHAZADA. Si el bloque tuvo reservas, el borrado es
    logico (ELIMINADO, T-169); si nunca tuvo, se borra la fila.
    """
    with transaction.atomic():
        bloque = bloque_propio(request, bloque_id)
        if tiene_reserva_que_ocupa(bloque):
            raise Rechazo(
                CON_RESERVA, "bloque_con_reserva_confirmada", status.HTTP_409_CONFLICT
            )
        # El aviso por correo a cada estudiante llega con HU-16.
        bloque.reservas.filter(estado=EstadoReserva.SOLICITADA).update(
            estado=EstadoReserva.RECHAZADA, cerrada_en=timezone.now()
        )
        if bloque.reservas.exists():
            bloque.estado = EstadoBloque.ELIMINADO
            bloque.save(update_fields=["estado", "actualizado_en"])
        else:
            bloque.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def mis_bloques(request):
    """GET /disponibilidad (los del usuario del token) y POST /disponibilidad."""
    if request.method == "POST":
        return publicar(request)
    return listar(request)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def un_bloque(request, bloque_id):
    """PATCH /disponibilidad/<id> y DELETE /disponibilidad/<id>."""
    if request.method == "DELETE":
        return eliminar(request, bloque_id)
    return editar(request, bloque_id)
