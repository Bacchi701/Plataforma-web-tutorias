"""Ruta interna de Pagos: el reembolso que pide Tutorias (HU-23, para HU-28).

POST /api/payments/v1/internal/pagos/reembolso, con la convencion de las
llamadas internas (Pilar 2, seccion 5.4; orden F1): solo existe dentro de la
red de Docker (desde fuera, el gateway responde 404), no usa el token del
usuario y se autentica con la cabecera X-Clave-Servicio, que tiene que calzar
con CLAVE_SERVICIO. Sin la cabecera, con otra clave o con CLAVE_SERVICIO vacia
responde 404 ruta_no_encontrada. No se documenta en docs/api.

El contrato para HU-28 (la cancelacion con reembolso):
- Cuerpo: {"reserva_id": "<uuid de la reserva>"}. Sin un uuid valido: 400
  reserva_invalida.
- 200 con el pago REEMBOLSADO, en el formato de GET /pagos (vistas.pago_json):
  si estaba PAGADO, se reembolsa con un intento REEMBOLSO EXITOSO y se avisa
  REEMBOLSADO a Tutorias; si ya estaba REEMBOLSADO, no cambia nada ni avisa
  (si HU-28 lo pide dos veces, no pasa nada).
- 404 pago_no_encontrado: la reserva no tiene pago.
- 409 pago_no_reembolsable: el pago esta PENDIENTE o FALLIDO.
- Si Pagos no responde a tiempo, quien llama recibe su propio 503
  servicio_no_disponible.
No le pregunta la reserva a Tutorias: quien pide el reembolso es Tutorias.

Tutorias tiene que pedir el reembolso despues del commit de la cancelacion,
nunca con la reserva bloqueada: Pagos llama de vuelta a Tutorias dentro de la
misma peticion, y con la reserva bloqueada ese aviso esperaria hasta el tiempo
maximo de 3 segundos.
"""

import hmac

from django.conf import settings
from django.db import transaction
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from .models import EstadoPago, Pago
from .vistas import Rechazo, leer_uuid, pago_json, reembolsar

RESERVA_INVALIDA = "Indica en reserva_id la reserva que se reembolsa."
SIN_PAGO = "Esa reserva no tiene pago."
NO_REEMBOLSABLE = "Solo se reembolsa un pago PAGADO."


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


@api_view(["POST"])
@authentication_classes([])
@permission_classes([ClaveDeServicio])
def reembolso(request):
    """POST /internal/pagos/reembolso: el reembolso de un pago (criterio 6)."""
    datos = request.data if isinstance(request.data, dict) else {}
    reserva_id = leer_uuid(datos.get("reserva_id"))
    if reserva_id is None:
        raise Rechazo(RESERVA_INVALIDA, "reserva_invalida")

    with transaction.atomic():
        pago = Pago.objects.select_for_update().filter(reserva_id=reserva_id).first()
        if pago is None:
            raise Rechazo(SIN_PAGO, "pago_no_encontrado", status.HTTP_404_NOT_FOUND)
        if pago.estado == EstadoPago.PAGADO:
            reembolsar(pago)
        elif pago.estado != EstadoPago.REEMBOLSADO:
            raise Rechazo(
                NO_REEMBOLSABLE, "pago_no_reembolsable", status.HTTP_409_CONFLICT
            )
    return Response(pago_json(Pago.objects.get(pk=pago.pk)))
