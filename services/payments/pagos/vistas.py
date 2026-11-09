"""Pagos simulados de una tutoria confirmada (HU-23; Pilar 2, seccion 4.4).

POST y GET /pagos y POST /pagos/<id>/simular, todo con sesion: quien pide
sale del token (HU-17, pagos/autenticacion.py).

- Pagos no conoce usuarios ni asignaturas: de quien es la reserva, en que
  estado esta y cuanto vale se lo pregunta a Tutorias (llamadas.reserva),
  antes de abrir cualquier transaccion, para no dejarla abierta mientras
  espera la respuesta.
- Un pago por reserva (ux_pago_reserva, A-10), con el monto de la reserva,
  que es la copia congelada de la tarifa (A-04). Cada cobro o reembolso es una
  fila de intento_pago, y un reintento no borra el anterior. Sin tarifa no hay
  pago (RN-05).
- El pago es simulado: no se cobra dinero real ni se piden datos de tarjeta.
  El proveedor es SIMULADO, el punto donde entraria una pasarela real (RF-18).
- Cada cambio del estado del pago se guarda en una transaccion, deja
  notificado_en en null y se avisa a Tutorias despues del commit
  (avisar_a_tutorias). Tutorias guarda una copia en la reserva (M-10, A-06).
  Un aviso que no sale se reenvia cuando alguien vuelve a abrir el pago
  (anexo A, seccion 7.2).
- Ninguna transicion de Tutorias mira el pago para dejar pasar la sesion
  (criterio 7): una reserva REALIZADA o EVALUADA tambien se paga.
"""

import logging
import uuid
from datetime import UTC
from functools import partial

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import APIException
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import llamadas
from .models import EstadoPago, IntentoPago, Pago, ResultadoIntento, TipoIntento

logger = logging.getLogger(__name__)

RESTRICCION_UNICA = "ux_pago_reserva"
# Punto exacto donde entraria una pasarela real (RF-18).
PROVEEDOR = "SIMULADO"
# Se paga una vez confirmada, y el pago no bloquea la sesion (RN-05, criterio
# 7): HU-29 pasa a REALIZADA las tutorias que ya terminaron.
ESTADOS_PAGABLES = ("CONFIRMADA", "REALIZADA", "EVALUADA")
# Una tutoria en estos estados ya no esta vigente: su pago no se simula.
ESTADOS_NO_VIGENTES = ("CANCELADA", "RECHAZADA", "EXPIRADA")

RESERVA_INVALIDA = "Indica la reserva que quieres pagar."
CONSULTA_INVALIDA = "Indica la reserva con ?reserva=<identificador>."
RESERVA_NO_ENCONTRADA = "No tienes una reserva con ese identificador."
GRATUITA = "Esta tutoría es gratuita: no tiene pago."
NO_CONFIRMADA = "Solo se paga una tutoría confirmada."
TODAVIA_SIN_PAGO = "Esta reserva todavía no tiene pago."
PAGO_NO_ENCONTRADO = "No tienes un pago con ese identificador."
RESULTADO_INVALIDO = "Indica el resultado de la simulación: EXITOSO o FALLIDO."
NO_VIGENTE = "Esta tutoría ya no está vigente: no se puede pagar."
NO_SIMULABLE = "Este pago ya está pagado o reembolsado."
RECHAZADO = "Pago rechazado en la simulación."
REEMBOLSO_AUTOMATICO = "Reembolso automático: la reserva se canceló mientras se pagaba."


class Rechazo(APIException):
    """Error con codigo propio, en el formato uniforme de la API."""

    def __init__(self, mensaje, codigo, estado=status.HTTP_400_BAD_REQUEST):
        self.status_code = estado
        super().__init__(detail=mensaje, code=codigo)


def instante_json(valor):
    """ISO 8601 en UTC y con Z, por ejemplo 2026-12-01T23:00:00Z."""
    return valor.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def intento_json(intento):
    return {
        "tipo": intento.tipo,
        "resultado": intento.resultado,
        "mensaje": intento.mensaje,
        "creado_en": instante_json(intento.creado_en),
    }


def pago_json(pago):
    """El formato de un pago. La pantalla de pago (HU-24) usa estos nombres.

    Los intentos van del mas nuevo al mas antiguo.
    """
    intentos = pago.intentos.order_by("-creado_en", "-id")
    return {
        "id": str(pago.id),
        "reserva_id": str(pago.reserva_id),
        # int: un Decimal sale como 5000.0.
        "monto": int(pago.monto),
        "estado": pago.estado,
        "proveedor": pago.proveedor,
        "creado_en": instante_json(pago.creado_en),
        "actualizado_en": instante_json(pago.actualizado_en),
        "intentos": [intento_json(intento) for intento in intentos],
    }


def leer_uuid(valor):
    """Un uuid en texto, o None si no lo es."""
    try:
        return uuid.UUID(valor) if isinstance(valor, str) else None
    except ValueError:
        return None


def cuerpo(request):
    return request.data if isinstance(request.data, dict) else {}


# ------------------------------------------------- el aviso a Tutorias


def avisar_a_tutorias(pago):
    """Avisa a Tutorias el estado del pago y actua segun lo que responda.

    Corre despues del commit de cada cambio (on_commit) y en el reintento.
    - AVISADO: marca notificado_en, solo si el pago sigue con el mismo
      actualizado_en. update no mueve actualizado_en, y si entretanto llego un
      estado mas nuevo, no marca nada.
    - RESERVA_CANCELADA: la reserva se cancelo mientras se pagaba. Si el pago
      sigue PAGADO, se reembolsa solo; si ya no (por ejemplo, porque HU-28 ya
      pidio el reembolso), no hace nada. Asi un pago nunca se reembolsa dos
      veces.
    - SIN_AVISO: el pago queda con notificado_en en null para el reintento, y
      la linea ya quedo en el log.
    """
    resultado = llamadas.informar_estado(pago)
    if resultado == llamadas.AVISADO:
        Pago.objects.filter(pk=pago.pk, actualizado_en=pago.actualizado_en).update(
            notificado_en=timezone.now()
        )
    elif resultado == llamadas.RESERVA_CANCELADA:
        with transaction.atomic():
            bloqueado = Pago.objects.select_for_update().get(pk=pago.pk)
            if bloqueado.estado == EstadoPago.PAGADO:
                logger.warning(
                    "Reembolso automático del pago %s: la reserva %s se canceló "
                    "mientras se pagaba",
                    bloqueado.id,
                    bloqueado.reserva_id,
                )
                reembolsar(bloqueado, REEMBOLSO_AUTOMATICO)


def reembolsar(pago, mensaje=None):
    """Reembolsa un pago PAGADO, que viene bloqueado (select_for_update).

    Va dentro de una transaccion: crea un intento REEMBOLSO EXITOSO, deja el
    pago REEMBOLSADO con notificado_en en null y registra el aviso a Tutorias
    para despues del commit. La usan el reembolso interno (internas.py, para
    HU-28) y el reembolso automatico.
    """
    IntentoPago.objects.create(
        pago=pago,
        tipo=TipoIntento.REEMBOLSO,
        resultado=ResultadoIntento.EXITOSO,
        mensaje=mensaje,
    )
    pago.estado = EstadoPago.REEMBOLSADO
    pago.notificado_en = None
    # Sin actualizado_en en update_fields, auto_now no llega a la base.
    pago.save(update_fields=["estado", "notificado_en", "actualizado_en"])
    transaction.on_commit(partial(avisar_a_tutorias, pago))


def reenviar_si_falta(pago):
    """El reintento del aviso (anexo A, seccion 7.2).

    Si el aviso del ultimo cambio no salio (notificado_en en null), lo reenvia
    fuera de cualquier transaccion y devuelve el pago leido de nuevo. A-06
    descarta los avisos repetidos.
    """
    if pago.notificado_en is not None:
        return pago
    avisar_a_tutorias(pago)
    return Pago.objects.get(pk=pago.pk)


# ------------------------------------------------- crear y consultar


def guardar_nuevo(pago):
    """Crea el pago. Devuelve (el pago que quedo, si lo creo).

    Si dos peticiones lo crean a la vez, la base rechaza la segunda por
    ux_pago_reserva: entonces devuelve el pago que ya estaba. Cualquier otro
    IntegrityError se deja pasar.
    """
    try:
        with transaction.atomic():
            pago.save(force_insert=True)
    except IntegrityError as error:
        diagnostico = getattr(error.__cause__, "diag", None)
        if getattr(diagnostico, "constraint_name", None) != RESTRICCION_UNICA:
            raise
        return Pago.objects.get(reserva_id=pago.reserva_id), False
    return pago, True


def crear(request):
    """Criterios 1 y 5. Responde 201 si crea el pago y 200 si ya existia."""
    reserva_id = leer_uuid(cuerpo(request).get("reserva_id"))
    if reserva_id is None:
        raise Rechazo(RESERVA_INVALIDA, "reserva_invalida")

    reserva = llamadas.reserva(reserva_id)
    # El tutor tampoco crea pagos: solo quien pidio la tutoria.
    if reserva is None or reserva["solicitante_usuario_id"] != request.user.usuario_id:
        raise Rechazo(
            RESERVA_NO_ENCONTRADA, "reserva_no_encontrada", status.HTTP_404_NOT_FOUND
        )
    if reserva["monto"] == 0:
        raise Rechazo(GRATUITA, "sin_pago", status.HTTP_409_CONFLICT)

    # Un pago por reserva. Va antes de mirar el estado, para que la misma
    # peticion responda igual aunque la reserva ya haya cambiado.
    existente = Pago.objects.filter(reserva_id=reserva_id).first()
    if existente is not None:
        return Response(pago_json(reenviar_si_falta(existente)))

    if reserva["estado"] not in ESTADOS_PAGABLES:
        raise Rechazo(NO_CONFIRMADA, "reserva_no_confirmada", status.HTTP_409_CONFLICT)

    with transaction.atomic():
        nuevo = Pago(
            reserva_id=reserva_id,
            monto=reserva["monto"],
            estado=EstadoPago.PENDIENTE,
            proveedor=PROVEEDOR,
        )
        pago, creado = guardar_nuevo(nuevo)
        if creado:
            # M-10: con este aviso Tutorias pasa la reserva a PENDIENTE.
            transaction.on_commit(partial(avisar_a_tutorias, pago))
    if not creado:
        return Response(pago_json(pago))
    return Response(pago_json(pago), status=status.HTTP_201_CREATED)


def consultar(request):
    """GET /pagos?reserva=<id>: el pago de una reserva, con sus intentos.

    Lo ven quien pidio la tutoria y el tutor.
    """
    reserva_id = leer_uuid(request.query_params.get("reserva"))
    if reserva_id is None:
        raise Rechazo(CONSULTA_INVALIDA, "reserva_invalida")

    # Sin pago no se llama a Tutorias.
    pago = Pago.objects.filter(reserva_id=reserva_id).first()
    if pago is None:
        raise Rechazo(TODAVIA_SIN_PAGO, "pago_no_encontrado", status.HTTP_404_NOT_FOUND)

    reserva = llamadas.reserva(reserva_id)
    usuario_id = request.user.usuario_id
    if reserva is None or usuario_id not in (
        reserva["solicitante_usuario_id"],
        reserva["tutor_usuario_id"],
    ):
        raise Rechazo(TODAVIA_SIN_PAGO, "pago_no_encontrado", status.HTTP_404_NOT_FOUND)
    return Response(pago_json(reenviar_si_falta(pago)))


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def crear_o_consultar(request):
    """POST /pagos (crear el pago) y GET /pagos?reserva=<id> (consultarlo)."""
    if request.method == "POST":
        return crear(request)
    return consultar(request)


# ------------------------------------------------- simular el resultado


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def simular(request, pago_id):
    """POST /pagos/<id>/simular: el resultado simulado de un cobro.

    Criterios 2, 3 y 4. Un pago PENDIENTE o FALLIDO queda PAGADO o FALLIDO,
    con un intento nuevo. El reintento despues de un FALLIDO es esta misma
    ruta: otro intento sobre el mismo pago (criterio 3).
    """
    resultado = cuerpo(request).get("resultado")
    if resultado not in ResultadoIntento.values:
        raise Rechazo(RESULTADO_INVALIDO, "resultado_invalido")

    pago = Pago.objects.filter(pk=pago_id).first()
    if pago is None:
        raise Rechazo(
            PAGO_NO_ENCONTRADO, "pago_no_encontrado", status.HTTP_404_NOT_FOUND
        )
    reserva = llamadas.reserva(pago.reserva_id)
    if reserva is None or reserva["solicitante_usuario_id"] != request.user.usuario_id:
        raise Rechazo(
            PAGO_NO_ENCONTRADO, "pago_no_encontrado", status.HTTP_404_NOT_FOUND
        )
    if reserva["estado"] in ESTADOS_NO_VIGENTES:
        raise Rechazo(NO_VIGENTE, "reserva_no_confirmada", status.HTTP_409_CONFLICT)

    with transaction.atomic():
        pago = Pago.objects.select_for_update().get(pk=pago_id)
        if pago.estado not in (EstadoPago.PENDIENTE, EstadoPago.FALLIDO):
            raise Rechazo(NO_SIMULABLE, "pago_no_simulable", status.HTTP_409_CONFLICT)
        exitoso = resultado == ResultadoIntento.EXITOSO
        IntentoPago.objects.create(
            pago=pago,
            tipo=TipoIntento.COBRO,
            resultado=resultado,
            mensaje=None if exitoso else RECHAZADO,
        )
        pago.estado = EstadoPago.PAGADO if exitoso else EstadoPago.FALLIDO
        pago.notificado_en = None
        # Sin actualizado_en en update_fields, auto_now no llega a la base.
        pago.save(update_fields=["estado", "notificado_en", "actualizado_en"])
        transaction.on_commit(partial(avisar_a_tutorias, pago))

    # Leido de nuevo despues del commit y del aviso: si Tutorias respondio
    # reserva_cancelada, ya viene REEMBOLSADO.
    return Response(pago_json(Pago.objects.get(pk=pago_id)))
