"""Modelo de Tutorias (anexo A del Pilar 2, seccion 6).

Siete tablas. usuario_ref y asignatura_ref son copias de lectura de otros
servicios (AD-07): dentro de esta base son tablas normales con FK reales.

Dos diferencias con el anexo, por la revision de 3FN del 30-09:
- usuario_ref no guarda carrera_nombre ni sede_nombre: dependian de
  carrera_id y sede_id (dependencia transitiva).
- reserva no guarda tutor_usuario_id: se deduce del bloque. La regla de que
  nadie se reserva a si mismo (ck_reserva_no_auto) la sostiene un disparador
  en la migracion 0003.
"""

import uuid
from decimal import Decimal

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import (
    DateTimeRangeField,
    RangeBoundary,
    RangeOperators,
)
from django.db import models
from django.db.models import F, Func, Q
from django.utils import timezone


class TsTzRange(Func):
    """tstzrange(inicio, fin, '[)') para la restriccion de no solapamiento."""

    function = "TSTZRANGE"
    output_field = DateTimeRangeField()


class EstadoBloque(models.TextChoices):
    LIBRE = "LIBRE", "Libre"
    OCUPADO = "OCUPADO", "Ocupado"
    # Borrado logico de un bloque que ya tuvo solicitudes (T-169).
    ELIMINADO = "ELIMINADO", "Eliminado"


class EstadoReserva(models.TextChoices):
    SOLICITADA = "SOLICITADA", "Solicitada"
    CONFIRMADA = "CONFIRMADA", "Confirmada"
    RECHAZADA = "RECHAZADA", "Rechazada"
    EXPIRADA = "EXPIRADA", "Expirada"
    CANCELADA = "CANCELADA", "Cancelada"
    REALIZADA = "REALIZADA", "Realizada"
    EVALUADA = "EVALUADA", "Evaluada"


class Modalidad(models.TextChoices):
    PRESENCIAL = "PRESENCIAL", "Presencial"
    EN_LINEA = "EN_LINEA", "En línea"


class EstadoPago(models.TextChoices):
    PENDIENTE = "PENDIENTE", "Pendiente"
    PAGADO = "PAGADO", "Pagado"
    FALLIDO = "FALLIDO", "Fallido"
    REEMBOLSADO = "REEMBOLSADO", "Reembolsado"


# Estados en que la reserva ocupa el bloque (ajuste A-03).
ESTADOS_QUE_OCUPAN = [
    EstadoReserva.CONFIRMADA,
    EstadoReserva.REALIZADA,
    EstadoReserva.EVALUADA,
]


class UsuarioRef(models.Model):
    """Copia de lectura del usuario mas su reputacion (dato propio)."""

    # El id de identity_db es la clave primaria: no hay id propio.
    usuario_id = models.UUIDField(primary_key=True)
    nombre = models.CharField(max_length=80)
    apellido = models.CharField(max_length=80)
    carrera_id = models.UUIDField(null=True, blank=True)
    sede_id = models.UUIDField(null=True, blank=True)
    # Ajuste A-01: sin esta copia, RN-08 no se cumple en la busqueda.
    activo = models.BooleanField(default=True)
    # Dato derivado de evaluacion, guardado a proposito (RN-06, RNF-02).
    reputacion_promedio = models.DecimalField(
        max_digits=3, decimal_places=2, default=Decimal("0.00")
    )
    reputacion_total = models.IntegerField(default=0)
    # Hora del ultimo refresco desde Identidad: no es auto_now, porque
    # recalcular la reputacion no refresca la copia.
    actualizado_en = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "usuario_ref"
        constraints = [
            models.CheckConstraint(
                condition=Q(reputacion_promedio__gte=0, reputacion_promedio__lte=5),
                name="ck_usuario_ref_promedio",
            ),
            models.CheckConstraint(
                condition=Q(reputacion_total__gte=0), name="ck_usuario_ref_total"
            ),
        ]
        indexes = [
            models.Index(fields=["actualizado_en"], name="ix_usuario_ref_refresco"),
        ]

    def __str__(self):
        return f"{self.nombre} {self.apellido}"


class AsignaturaRef(models.Model):
    """Copia de lectura de catalog_db.asignatura (evita el N+1 de AD-07)."""

    asignatura_id = models.UUIDField(primary_key=True)
    sigla = models.CharField(max_length=15)
    nombre = models.CharField(max_length=150)
    actualizado_en = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "asignatura_ref"
        indexes = [
            models.Index(fields=["sigla"], name="ix_asignatura_ref_sigla"),
        ]

    def __str__(self):
        return f"{self.sigla} {self.nombre}"


class PerfilTutor(models.Model):
    """Una fila por asignatura que el usuario declara tutorear (RF-03)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    usuario = models.ForeignKey(
        UsuarioRef, on_delete=models.CASCADE, related_name="perfiles", db_index=False
    )
    asignatura = models.ForeignKey(
        AsignaturaRef,
        on_delete=models.RESTRICT,
        related_name="perfiles",
        db_index=False,
    )
    # Pesos chilenos. 0 es una tutoria gratuita y sin pago (RN-05).
    tarifa = models.DecimalField(max_digits=8, decimal_places=0, default=Decimal("0"))
    descripcion = models.CharField(max_length=500, null=True, blank=True)
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(default=timezone.now)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "perfil_tutor"
        constraints = [
            models.UniqueConstraint(
                fields=["usuario", "asignatura"], name="ux_perfil_usuario_asignatura"
            ),
            models.CheckConstraint(condition=Q(tarifa__gte=0), name="ck_perfil_tarifa"),
        ]
        indexes = [
            models.Index(
                fields=["asignatura", "activo"],
                include=["usuario", "tarifa"],
                name="ix_perfil_busqueda",
            ),
            models.Index(fields=["usuario"], name="ix_perfil_usuario"),
        ]


class BloqueDisponibilidad(models.Model):
    """Bloque con fecha y hora concretas, guardado como dos instantes (A-02)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    usuario = models.ForeignKey(
        UsuarioRef, on_delete=models.CASCADE, related_name="bloques"
    )
    inicio_en = models.DateTimeField()
    fin_en = models.DateTimeField()
    estado = models.CharField(
        max_length=10, choices=EstadoBloque.choices, default=EstadoBloque.LIBRE
    )
    creado_en = models.DateTimeField(default=timezone.now)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "bloque_disponibilidad"
        constraints = [
            models.CheckConstraint(
                condition=Q(fin_en__gt=F("inicio_en")), name="ck_bloque_fin_posterior"
            ),
            models.CheckConstraint(
                condition=Q(estado__in=EstadoBloque.values), name="ck_bloque_estado"
            ),
            # RN-02: dos bloques vigentes del mismo tutor no se solapan. Lo
            # garantiza la base (EXCLUDE con btree_gist), no el codigo. Los
            # bloques eliminados no cuentan (T-169).
            ExclusionConstraint(
                name="ex_bloque_sin_solape",
                expressions=[
                    ("usuario", RangeOperators.EQUAL),
                    (
                        TsTzRange("inicio_en", "fin_en", RangeBoundary()),
                        RangeOperators.OVERLAPS,
                    ),
                ],
                condition=~Q(estado=EstadoBloque.ELIMINADO),
            ),
        ]
        indexes = [
            models.Index(
                fields=["usuario", "inicio_en"],
                condition=Q(estado=EstadoBloque.LIBRE),
                name="ix_bloque_libre",
            ),
            models.Index(fields=["inicio_en"], name="ix_bloque_inicio"),
        ]


class Reserva(models.Model):
    """La entidad con mas reglas del sistema (maquina de estados, anexo 9)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # El tutor es el dueno del bloque: no se guarda aparte (3FN).
    bloque = models.ForeignKey(
        BloqueDisponibilidad, on_delete=models.RESTRICT, related_name="reservas"
    )
    solicitante_usuario = models.ForeignKey(
        UsuarioRef,
        on_delete=models.RESTRICT,
        related_name="reservas_solicitadas",
        db_index=False,
    )
    asignatura = models.ForeignKey(
        AsignaturaRef, on_delete=models.RESTRICT, related_name="reservas"
    )
    estado = models.CharField(
        max_length=12,
        choices=EstadoReserva.choices,
        default=EstadoReserva.SOLICITADA,
    )
    nota = models.CharField(max_length=500, null=True, blank=True)
    modalidad = models.CharField(
        max_length=12, choices=Modalidad.choices, null=True, blank=True
    )
    lugar_o_enlace = models.CharField(max_length=300, null=True, blank=True)
    # Copia congelada de la tarifa al solicitar (A-04): es una fotografia.
    monto = models.DecimalField(max_digits=8, decimal_places=0, default=Decimal("0"))
    # Copia de lectura de Pagos. NULL al confirmar; Pagos informa PENDIENTE
    # cuando crea el pago (T-174).
    estado_pago = models.CharField(
        max_length=12, choices=EstadoPago.choices, null=True, blank=True
    )
    pago_actualizado_en = models.DateTimeField(null=True, blank=True)
    cancelada_por_usuario = models.ForeignKey(
        UsuarioRef,
        on_delete=models.RESTRICT,
        related_name="reservas_canceladas",
        null=True,
        blank=True,
    )
    creada_en = models.DateTimeField(default=timezone.now)
    confirmada_en = models.DateTimeField(null=True, blank=True)
    cerrada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "reserva"
        constraints = [
            models.CheckConstraint(
                condition=Q(estado__in=EstadoReserva.values), name="ck_reserva_estado"
            ),
            models.CheckConstraint(
                condition=Q(modalidad__isnull=True) | Q(modalidad__in=Modalidad.values),
                name="ck_reserva_modalidad",
            ),
            models.CheckConstraint(
                condition=Q(estado_pago__isnull=True)
                | Q(estado_pago__in=EstadoPago.values),
                name="ck_reserva_estado_pago",
            ),
            models.CheckConstraint(condition=Q(monto__gte=0), name="ck_reserva_monto"),
            # RN-07: no hay reserva confirmada sin modalidad ni lugar.
            models.CheckConstraint(
                condition=~Q(estado__in=ESTADOS_QUE_OCUPAN)
                | Q(
                    modalidad__isnull=False,
                    lugar_o_enlace__isnull=False,
                    confirmada_en__isnull=False,
                ),
                name="ck_reserva_confirmada_completa",
            ),
            # RN-05: sin tarifa no hay pago.
            models.CheckConstraint(
                condition=Q(estado_pago__isnull=True) | Q(monto__gt=0),
                name="ck_reserva_pago_con_monto",
            ),
            # RN-03: la primera confirmacion gana (A-03).
            models.UniqueConstraint(
                fields=["bloque"],
                condition=Q(estado__in=ESTADOS_QUE_OCUPAN),
                name="ux_reserva_bloque_ocupado",
            ),
            models.UniqueConstraint(
                fields=["bloque", "solicitante_usuario"],
                condition=Q(estado=EstadoReserva.SOLICITADA),
                name="ux_reserva_solicitud_unica",
            ),
        ]
        indexes = [
            models.Index(
                fields=["solicitante_usuario", "-creada_en"],
                name="ix_reserva_solicitante",
            ),
            models.Index(
                fields=["bloque"],
                condition=Q(estado=EstadoReserva.SOLICITADA),
                name="ix_reserva_pendientes",
            ),
        ]


class Evaluacion(models.Model):
    """Una por reserva, solo sobre una reserva realizada (RN-06)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reserva = models.OneToOneField(
        Reserva, on_delete=models.CASCADE, related_name="evaluacion"
    )
    calificacion = models.SmallIntegerField()
    comentario = models.CharField(max_length=500, null=True, blank=True)
    # Retirada por el administrador: deja de contar en la reputacion (CA7).
    retirada_en = models.DateTimeField(null=True, blank=True)
    retirada_por_usuario_id = models.UUIDField(null=True, blank=True)
    creada_en = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "evaluacion"
        constraints = [
            models.CheckConstraint(
                condition=Q(calificacion__gte=1, calificacion__lte=5),
                name="ck_evaluacion_calificacion",
            ),
            models.CheckConstraint(
                condition=Q(
                    retirada_en__isnull=True, retirada_por_usuario_id__isnull=True
                )
                | Q(retirada_en__isnull=False, retirada_por_usuario_id__isnull=False),
                name="ck_evaluacion_retiro",
            ),
        ]
        indexes = [
            models.Index(
                fields=["reserva"],
                condition=Q(retirada_en__isnull=True),
                name="ix_evaluacion_visible",
            ),
        ]


class EjecucionTarea(models.Model):
    """Registro de cada ejecucion del programador (AD-10, ajuste A-09)."""

    id = models.BigAutoField(primary_key=True)
    comando = models.CharField(max_length=40)
    solicitudes_expiradas = models.IntegerField(default=0)
    reservas_cerradas = models.IntegerField(default=0)
    refs_sincronizadas = models.IntegerField(default=0)
    perfiles_desactivados = models.IntegerField(default=0)
    error = models.CharField(max_length=300, null=True, blank=True)
    iniciada_en = models.DateTimeField(default=timezone.now)
    # NULL indica una ejecucion interrumpida.
    terminada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ejecucion_tarea"
        indexes = [
            models.Index(fields=["-iniciada_en"], name="ix_ejecucion_fecha"),
        ]
