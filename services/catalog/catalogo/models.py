"""Modelo del catalogo academico (anexo A del Pilar 2, seccion 5).

Ocho tablas: las siete del anexo mas importacion_error, que reemplaza a la
columna errores jsonb de importacion_catalogo para cumplir la 1FN.
"""

import uuid

from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Upper
from django.utils import timezone


class TipoImportacion(models.TextChoices):
    CARRERAS = "CARRERAS", "Carreras"
    ASIGNATURAS = "ASIGNATURAS", "Asignaturas"
    MALLA = "MALLA", "Malla"
    # No esta en el anexo, pero HU-07 (criterio 2) tambien carga sedes por CSV.
    SEDES = "SEDES", "Sedes"


class Carrera(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Clave natural del CSV de carga.
    codigo = models.CharField(max_length=20)
    nombre = models.CharField(max_length=150)
    # Etiqueta: ninguna consulta del MVP filtra por escuela (anexo, 5.2).
    escuela = models.CharField(max_length=120)
    activa = models.BooleanField(default=True)
    creada_en = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "carrera"
        constraints = [
            models.UniqueConstraint(fields=["codigo"], name="ux_carrera_codigo"),
        ]
        indexes = [
            models.Index(fields=["activa", "nombre"], name="ix_carrera_activa"),
        ]

    def __str__(self):
        return self.nombre


class Malla(models.Model):
    """Version del plan de estudios de una carrera."""

    id = models.BigAutoField(primary_key=True)
    carrera = models.ForeignKey(
        Carrera, on_delete=models.CASCADE, related_name="mallas", db_index=False
    )
    version = models.CharField(max_length=20)
    # date a proposito: la vigencia de un plan es un dia, no un instante.
    vigente_desde = models.DateField()
    vigente_hasta = models.DateField(null=True, blank=True)
    creada_en = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "malla"
        constraints = [
            models.UniqueConstraint(
                fields=["carrera", "version"], name="ux_malla_carrera_version"
            ),
            models.CheckConstraint(
                condition=Q(vigente_hasta__isnull=True)
                | Q(vigente_hasta__gt=F("vigente_desde")),
                name="ck_malla_vigencia",
            ),
            # Una sola malla vigente por carrera: la que consume RN-01.
            models.UniqueConstraint(
                fields=["carrera"],
                condition=Q(vigente_hasta__isnull=True),
                name="ux_malla_vigente",
            ),
        ]
        indexes = [
            models.Index(fields=["carrera"], name="ix_malla_carrera"),
        ]


class Asignatura(models.Model):
    """Transversal entre carreras (Pilar 2, seccion 6.2)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sigla = models.CharField(max_length=15)
    nombre = models.CharField(max_length=150)
    area = models.CharField(max_length=100, null=True, blank=True)
    creditos = models.SmallIntegerField(null=True, blank=True)
    activa = models.BooleanField(default=True)
    creada_en = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "asignatura"
        constraints = [
            models.UniqueConstraint(fields=["sigla"], name="ux_asignatura_sigla"),
            models.CheckConstraint(
                condition=Q(creditos__isnull=True)
                | Q(creditos__gte=1, creditos__lte=30),
                name="ck_asignatura_creditos",
            ),
        ]
        indexes = [
            # Indice trigram de la busqueda (RNF-02). Va sobre upper() porque
            # icontains de Django compara UPPER(columna) LIKE UPPER(texto):
            # asi PostgreSQL puede usar el indice. Requiere pg_trgm (0001).
            GinIndex(
                OpClass(Upper("sigla"), name="gin_trgm_ops"),
                OpClass(Upper("nombre"), name="gin_trgm_ops"),
                name="ix_asignatura_busqueda",
            ),
        ]

    def __str__(self):
        return f"{self.sigla} {self.nombre}"


class MallaAsignatura(models.Model):
    """Ubica una asignatura en un semestre de una malla (sostiene RN-01)."""

    id = models.BigAutoField(primary_key=True)
    malla = models.ForeignKey(
        Malla, on_delete=models.CASCADE, related_name="asignaturas", db_index=False
    )
    asignatura = models.ForeignKey(
        Asignatura, on_delete=models.RESTRICT, related_name="en_mallas"
    )
    semestre = models.SmallIntegerField()

    class Meta:
        db_table = "malla_asignatura"
        constraints = [
            models.UniqueConstraint(
                fields=["malla", "asignatura"], name="ux_malla_asignatura"
            ),
            models.CheckConstraint(
                condition=Q(semestre__gte=1, semestre__lte=12),
                name="ck_malla_asig_semestre",
            ),
        ]
        indexes = [
            models.Index(
                fields=["malla", "semestre"],
                include=["asignatura"],
                name="ix_malla_asig_semestre",
            ),
        ]


class Prerrequisito(models.Model):
    """Estructura preparada, sin uso funcional en el MVP (Pilar 2, 6.2)."""

    id = models.BigAutoField(primary_key=True)
    malla_asignatura = models.ForeignKey(
        MallaAsignatura,
        on_delete=models.CASCADE,
        related_name="prerrequisitos",
        db_index=False,
    )
    requiere = models.ForeignKey(
        MallaAsignatura, on_delete=models.CASCADE, related_name="exigida_por"
    )

    class Meta:
        db_table = "prerrequisito"
        constraints = [
            models.UniqueConstraint(
                fields=["malla_asignatura", "requiere"], name="ux_prerrequisito"
            ),
            models.CheckConstraint(
                condition=~Q(malla_asignatura_id=F("requiere_id")),
                name="ck_prerrequisito_distinto",
            ),
        ]
        indexes = [
            models.Index(fields=["malla_asignatura"], name="ix_prerrequisito_origen"),
        ]


class Sede(models.Model):
    """Tabla de referencia (ajuste A-07). Menos de veinte filas."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    codigo = models.CharField(max_length=20)
    nombre = models.CharField(max_length=120)
    region = models.CharField(max_length=80, null=True, blank=True)
    activa = models.BooleanField(default=True)

    class Meta:
        db_table = "sede"
        constraints = [
            models.UniqueConstraint(fields=["codigo"], name="ux_sede_codigo"),
        ]
        indexes = [
            models.Index(fields=["activa", "nombre"], name="ix_sede_activa"),
        ]

    def __str__(self):
        return self.nombre


class ImportacionCatalogo(models.Model):
    """Una fila por ejecucion de la carga desde CSV (RF-04 y RF-16)."""

    id = models.BigAutoField(primary_key=True)
    archivo = models.CharField(max_length=200)
    tipo = models.CharField(max_length=20, choices=TipoImportacion.choices)
    filas_leidas = models.IntegerField(default=0)
    filas_creadas = models.IntegerField(default=0)
    filas_omitidas = models.IntegerField(default=0)
    # Referencia logica al administrador; NULL si la corrio el script.
    ejecutada_por = models.UUIDField(null=True, blank=True)
    ejecutada_en = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "importacion_catalogo"
        constraints = [
            models.CheckConstraint(
                condition=Q(tipo__in=TipoImportacion.values),
                name="ck_importacion_tipo",
            ),
        ]
        indexes = [
            models.Index(fields=["-ejecutada_en"], name="ix_importacion_fecha"),
        ]


class ImportacionError(models.Model):
    """Una fila por error de una importacion (reemplaza errores jsonb: 1FN)."""

    id = models.BigAutoField(primary_key=True)
    importacion = models.ForeignKey(
        ImportacionCatalogo,
        on_delete=models.CASCADE,
        related_name="errores",
        db_index=False,
    )
    # Numero de fila del CSV, contando el encabezado como fila 1.
    fila = models.IntegerField()
    mensaje = models.CharField(max_length=300)

    class Meta:
        db_table = "importacion_error"
        constraints = [
            models.CheckConstraint(
                condition=Q(fila__gte=1), name="ck_importacion_error_fila"
            ),
        ]
        indexes = [
            models.Index(fields=["importacion", "fila"], name="ix_importacion_error"),
        ]
