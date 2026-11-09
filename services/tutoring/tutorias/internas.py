"""Rutas internas de Tutorias que usa Pagos (HU-23; Pilar 2, secciones 4.3 y 5.4).

- GET /api/tutoring/v1/internal/reservas/<id> (ver_reserva): lo que Pagos
  necesita de una reserva para cobrarla. Pagos no conoce usuarios: de quien es
  la reserva, en que estado esta y cuanto vale se lo pregunta a Tutorias.
- PATCH /api/tutoring/v1/internal/reservas/<id>/estado-pago
  (cambiar_estado_pago): el aviso de Pagos con cada cambio del pago. Pagos es
  la unica fuente del estado del pago; la reserva guarda una copia
  (estado_pago y pago_actualizado_en) que solo cambia con estos avisos (M-10,
  decision T-174), y descarta los que llegan fuera de orden (A-06).

La convencion de las llamadas internas (Pilar 2, seccion 5.4; orden F1):
- Solo existen dentro de la red de Docker: desde fuera, el gateway responde
  404 a toda ruta /internal (infra/nginx/nginx.conf).
- No usan el token del usuario: se autentican con la cabecera
  X-Clave-Servicio, que tiene que calzar con CLAVE_SERVICIO, la misma en los
  cuatro servicios. Sin la cabecera, con otra clave o con CLAVE_SERVICIO vacia
  responden 404 ruta_no_encontrada, como si no existieran. Una cabecera
  Authorization, aunque traiga un token vencido, no cambia nada.
- No se documentan en docs/api.

Las dos rutas se declaran al final de este archivo, en urlpatterns, y
tutorias/urls.py las incluye.
"""

import hmac
from datetime import UTC

from django.conf import settings
from django.db import transaction
from django.urls import path
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from .bloques import Rechazo
from .models import EstadoPago, EstadoReserva, Reserva

NO_EXISTE = "No existe una reserva con ese identificador."
ESTADO_PAGO_INVALIDO = "Indica estado_pago: PENDIENTE, PAGADO, FALLIDO o REEMBOLSADO."
ACTUALIZADO_EN_INVALIDO = (
    "Indica actualizado_en en ISO 8601 y con zona, por ejemplo "
    "2026-11-08T15:30:00.123456Z."
)
SIN_PAGO = "La reserva no tiene monto: no lleva pago (RN-05)."
YA_CANCELADA = "La reserva está cancelada: el pago se reembolsa."


class ClaveDeServicio(BasePermission):
    """Permiso para rutas internas entre servicios.

    Copia del de Identidad (cuentas/internas.py), sin cambiar lo que hace:
    ningun servicio importa codigo de otro (Pilar 2, seccion 9).
    """

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


def instante_preciso(valor):
    """Como instante_json de bloques.py, pero con microsegundos.

    ISO 8601 en UTC y con Z, por ejemplo 2026-11-08T15:30:00.123456Z. Es el
    formato de pago_actualizado_en: Pagos compara los avisos al microsegundo.
    """
    return (
        valor.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def reserva_interna_json(reserva):
    """Lo que Pagos usa de la reserva. Ni correos ni nombres (RNF-07)."""
    actualizado = reserva.pago_actualizado_en
    return {
        "id": str(reserva.id),
        "estado": reserva.estado,
        "monto": int(reserva.monto),
        "estado_pago": reserva.estado_pago,
        "pago_actualizado_en": instante_preciso(actualizado) if actualizado else None,
        "solicitante_usuario_id": str(reserva.solicitante_usuario_id),
        # El tutor es el dueno del bloque: la reserva no lo guarda aparte (3FN).
        "tutor_usuario_id": str(reserva.bloque.usuario_id),
    }


def leer_estado_pago(datos):
    valor = datos.get("estado_pago")
    if valor not in EstadoPago.values:
        raise Rechazo(ESTADO_PAGO_INVALIDO, "estado_pago_invalido")
    return valor


def leer_actualizado_en(datos):
    """El instante del aviso: texto ISO 8601 con zona, pasado a UTC."""
    texto = datos.get("actualizado_en")
    try:
        instante = parse_datetime(texto) if isinstance(texto, str) else None
    except ValueError:
        instante = None
    if instante is None or timezone.is_naive(instante):
        raise Rechazo(ACTUALIZADO_EN_INVALIDO, "actualizado_en_invalido")
    try:
        return instante.astimezone(UTC)
    except OverflowError:
        # Una fecha en el limite (0001 o 9999) con desfase se sale del rango.
        raise Rechazo(ACTUALIZADO_EN_INVALIDO, "actualizado_en_invalido") from None


@api_view(["GET"])
@authentication_classes([])
@permission_classes([ClaveDeServicio])
def ver_reserva(request, reserva_id):
    """GET /internal/reservas/<id>: la reserva que Pagos va a cobrar."""
    reserva = Reserva.objects.select_related("bloque").filter(id=reserva_id).first()
    if reserva is None:
        raise NotFound(NO_EXISTE, code="reserva_no_encontrada")
    return Response(reserva_interna_json(reserva))


@api_view(["PATCH"])
@authentication_classes([])
@permission_classes([ClaveDeServicio])
def cambiar_estado_pago(request, reserva_id):
    """PATCH /internal/reservas/<id>/estado-pago: el aviso de Pagos (A-06).

    Cuerpo: {"estado_pago", "actualizado_en"}. El aviso se aplica solo si su
    instante es posterior al guardado en pago_actualizado_en, y se guarda el
    instante que mando Pagos, no la hora de Tutorias. Uno igual o anterior
    llego fuera de orden: responde aplicado false y no cambia nada.
    """
    # 1. El cuerpo, antes de tocar la base.
    datos = request.data if isinstance(request.data, dict) else {}
    estado_pago = leer_estado_pago(datos)
    instante = leer_actualizado_en(datos)

    # 2. La reserva, bloqueada hasta el fin de la transaccion.
    with transaction.atomic():
        reserva = Reserva.objects.select_for_update().filter(id=reserva_id).first()
        if reserva is None:
            raise NotFound(NO_EXISTE, code="reserva_no_encontrada")
        if reserva.monto == 0:
            # Sin esto, ck_reserva_pago_con_monto rechazaria el cambio con un 500.
            raise Rechazo(SIN_PAGO, "sin_pago", status.HTTP_409_CONFLICT)
        # 3. La carrera entre pagar y cancelar: Pagos lee la reserva antes de su
        # transaccion, y la cancelacion (HU-28) se puede guardar entre medio. Un
        # PAGADO sobre una reserva CANCELADA no se aplica: Pagos lo reembolsa
        # solo. Los demas avisos sobre una reserva CANCELADA siguen la regla
        # A-06, y los demas estados de la reserva no se miran.
        if (
            reserva.estado == EstadoReserva.CANCELADA
            and estado_pago == EstadoPago.PAGADO
        ):
            raise Rechazo(YA_CANCELADA, "reserva_cancelada", status.HTTP_409_CONFLICT)
        anterior = reserva.pago_actualizado_en
        if anterior is not None and instante <= anterior:
            return Response({"aplicado": False, "estado_pago": reserva.estado_pago})
        reserva.estado_pago = estado_pago
        reserva.pago_actualizado_en = instante
        reserva.save(update_fields=["estado_pago", "pago_actualizado_en"])
    return Response({"aplicado": True, "estado_pago": estado_pago})


urlpatterns = [
    path("internal/reservas/<uuid:reserva_id>", ver_reserva, name="interna-reserva"),
    path(
        "internal/reservas/<uuid:reserva_id>/estado-pago",
        cambiar_estado_pago,
        name="interna-estado-pago",
    ),
]
