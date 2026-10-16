"""Modelo de Pagos simulados (anexo A del Pilar 2, seccion 7).

Dos tablas. Pagos no conoce usuarios ni asignaturas: solo reservas y montos.
reserva_id es una referencia logica a tutoring_db, sin FK (AD-08).
"""

import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone


class EstadoPago(models.TextChoices):
    PENDIENTE = "PENDIENTE", "Pendiente"
    PAGADO = "PAGADO", "Pagado"
    FALLIDO = "FALLIDO", "Fallido"
    REEMBOLSADO = "REEMBOLSADO", "Reembolsado"


class TipoIntento(models.TextChoices):
    COBRO = "COBRO", "Cobro"
    REEMBOLSO = "REEMBOLSO", "Reembolso"


class ResultadoIntento(models.TextChoices):
    EXITOSO = "EXITOSO", "Exitoso"
    FALLIDO = "FALLIDO", "Fallido"


class Pago(models.Model):
    """Un pago por reserva, solo si la tarifa es mayor que cero (RN-05)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reserva_id = models.UUIDField()
    monto = models.DecimalField(max_digits=8, decimal_places=0)
    estado = models.CharField(
        max_length=12, choices=EstadoPago.choices, default=EstadoPago.PENDIENTE
    )
    # Punto exacto donde entraria una pasarela real (RF-18).
    proveedor = models.CharField(max_length=30, default="SIMULADO")
    referencia_externa = models.CharField(max_length=100, null=True, blank=True)
    # Tutorias confirmo el aviso; si es NULL, el aviso se reintenta.
    notificado_en = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(default=timezone.now)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pago"
        constraints = [
            # Los reintentos son filas de intento_pago, no pagos nuevos.
            models.UniqueConstraint(fields=["reserva_id"], name="ux_pago_reserva"),
            models.UniqueConstraint(
                fields=["proveedor", "referencia_externa"],
                condition=Q(referencia_externa__isnull=False),
                name="ux_pago_referencia",
            ),
            models.CheckConstraint(
                condition=Q(estado__in=EstadoPago.values), name="ck_pago_estado"
            ),
            models.CheckConstraint(condition=Q(monto__gt=0), name="ck_pago_monto"),
        ]
        indexes = [
            # Cola de reintento del aviso a Tutorias.
            models.Index(
                fields=["id"],
                condition=Q(notificado_en__isnull=True)
                & ~Q(estado=EstadoPago.PENDIENTE),
                name="ix_pago_sin_notificar",
            ),
        ]


class IntentoPago(models.Model):
    """Historial de cobros y reembolsos de un pago (ajuste A-10)."""

    id = models.BigAutoField(primary_key=True)
    pago = models.ForeignKey(
        Pago, on_delete=models.CASCADE, related_name="intentos", db_index=False
    )
    tipo = models.CharField(
        max_length=10, choices=TipoIntento.choices, default=TipoIntento.COBRO
    )
    resultado = models.CharField(max_length=10, choices=ResultadoIntento.choices)
    mensaje = models.CharField(max_length=200, null=True, blank=True)
    referencia_externa = models.CharField(max_length=100, null=True, blank=True)
    creado_en = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "intento_pago"
        constraints = [
            models.CheckConstraint(
                condition=Q(tipo__in=TipoIntento.values), name="ck_intento_tipo"
            ),
            models.CheckConstraint(
                condition=Q(resultado__in=ResultadoIntento.values),
                name="ck_intento_resultado",
            ),
        ]
        indexes = [
            models.Index(fields=["pago", "-creado_en"], name="ix_intento_pago"),
        ]
