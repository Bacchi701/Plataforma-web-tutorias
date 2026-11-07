from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Avg, Count, DecimalField

from .models import Evaluacion, UsuarioRef

DOS_DECIMALES = Decimal("0.01")
CERO_REPUTACION = Decimal("0.00")


def recalcular_reputacion(tutor_id):
    """Recalcula el promedio y total de evaluaciones activas del tutor (RN-06)."""
    with transaction.atomic():
        UsuarioRef.objects.select_for_update().filter(pk=tutor_id).first()

        resumen = Evaluacion.objects.filter(
            reserva__bloque__usuario_id=tutor_id,
            retirada_en__isnull=True,
        ).aggregate(
            promedio=Avg("calificacion", output_field=DecimalField()),
            total=Count("id"),
        )

        total = resumen["total"] or 0
        if total == 0 or resumen["promedio"] is None:
            promedio = CERO_REPUTACION
        else:
            promedio = Decimal(resumen["promedio"]).quantize(
                DOS_DECIMALES, rounding=ROUND_HALF_UP
            )

        UsuarioRef.objects.filter(pk=tutor_id).update(
            reputacion_promedio=promedio,
            reputacion_total=total,
        )

        return promedio, total
