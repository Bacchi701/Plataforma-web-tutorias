"""Modelo de datos de Identidad (anexo A del Pilar 2, seccion 4).

Cuatro tablas: usuario, token_verificacion, refresh_token y aviso_correo.
Los nombres de tabla y de columna son los del anexo; por eso cada modelo
declara su db_table.
"""

import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower
from django.utils import timezone

DOMINIO_INSTITUCIONAL = "@duocuc.cl"


class PlantillaAviso(models.TextChoices):
    VERIFICACION_CORREO = "VERIFICACION_CORREO", "Verificación del correo"
    SOLICITUD_RECIBIDA = "SOLICITUD_RECIBIDA", "Solicitud recibida"
    RESERVA_CONFIRMADA = "RESERVA_CONFIRMADA", "Reserva confirmada"
    RESERVA_RECHAZADA = "RESERVA_RECHAZADA", "Reserva rechazada"
    RESERVA_CANCELADA = "RESERVA_CANCELADA", "Reserva cancelada"
    CUENTA_DESACTIVADA = "CUENTA_DESACTIVADA", "Cuenta desactivada"


class EstadoAviso(models.TextChoices):
    ENVIADO = "ENVIADO", "Enviado"
    FALLIDO = "FALLIDO", "Fallido"


class UsuarioManager(BaseUserManager):
    def create_user(self, email, password=None, **campos):
        if not email:
            raise ValueError("El correo es obligatorio")
        # Se guarda siempre en minusculas: la unicidad es por lower(email).
        usuario = self.model(email=self.normalize_email(email).lower(), **campos)
        usuario.set_password(password)
        usuario.save(using=self._db)
        return usuario


class Usuario(AbstractBaseUser):
    """Cuenta unica por persona (RN-08). Unica base que conoce correos."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # La unicidad la da ux_usuario_email sobre lower(email), que es mas
    # estricta que un UNIQUE sobre la columna. Si algun dia se instala
    # django.contrib.auth, su revision pedira ademas unique=True aqui.
    email = models.EmailField(max_length=150)
    # AbstractBaseUser llama "password" al campo; en la base se llama como
    # en el anexo. Guarda el hash PBKDF2 de Django, nunca la clave (RNF-01).
    password = models.CharField(max_length=128, db_column="password_hash")
    # El anexo no tiene last_login: se quita el campo heredado.
    last_login = None
    nombre = models.CharField(max_length=80)
    apellido = models.CharField(max_length=80)
    # Referencias logicas a catalog_db, sin FK (AD-15).
    carrera_id = models.UUIDField(null=True, blank=True)
    nivel = models.SmallIntegerField(null=True, blank=True)
    sede_id = models.UUIDField(null=True, blank=True)
    email_verificado = models.BooleanField(default=False)
    activo = models.BooleanField(default=True)
    es_admin = models.BooleanField(default=False)
    creado_en = models.DateTimeField(default=timezone.now)
    actualizado_en = models.DateTimeField(auto_now=True)

    objects = UsuarioManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["nombre", "apellido"]

    class Meta:
        db_table = "usuario"
        constraints = [
            models.UniqueConstraint(Lower("email"), name="ux_usuario_email"),
            models.CheckConstraint(
                condition=Q(email__iendswith=DOMINIO_INSTITUCIONAL),
                name="ck_usuario_email_dominio",
            ),
            models.CheckConstraint(
                condition=Q(nivel__isnull=True) | Q(nivel__gte=1, nivel__lte=12),
                name="ck_usuario_nivel",
            ),
        ]
        indexes = [
            models.Index(fields=["activo", "-creado_en"], name="ix_usuario_admin"),
        ]

    # Django pregunta por is_active; en la base la columna es "activo".
    @property
    def is_active(self):
        return self.activo

    def __str__(self):
        return self.email


class TokenVerificacion(models.Model):
    """Token de un solo uso que verifica el correo (CA1, ajuste A-12)."""

    id = models.BigAutoField(primary_key=True)
    usuario = models.ForeignKey(
        Usuario, on_delete=models.CASCADE, related_name="tokens_verificacion"
    )
    # sha256 en hexadecimal del token enviado por correo; el token no se guarda.
    token_hash = models.CharField(max_length=64)
    expira_en = models.DateTimeField()
    usado_en = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "token_verificacion"
        constraints = [
            models.UniqueConstraint(fields=["token_hash"], name="ux_token_verif_hash"),
            models.CheckConstraint(
                condition=Q(expira_en__gt=F("creado_en")),
                name="ck_token_verif_expira",
            ),
        ]
        indexes = [
            models.Index(
                fields=["usuario"],
                condition=Q(usado_en__isnull=True),
                name="ix_token_verif_vigente",
            ),
        ]


class RefreshToken(models.Model):
    """Una fila por sesion abierta; el unico token revocable (Pilar 2, 5.3)."""

    id = models.BigAutoField(primary_key=True)
    usuario = models.ForeignKey(
        Usuario, on_delete=models.CASCADE, related_name="refresh_tokens"
    )
    token_hash = models.CharField(max_length=64)
    expira_en = models.DateTimeField()
    revocado_en = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "refresh_token"
        constraints = [
            models.UniqueConstraint(fields=["token_hash"], name="ux_refresh_hash"),
            models.CheckConstraint(
                condition=Q(expira_en__gt=F("creado_en")),
                name="ck_refresh_expira",
            ),
        ]
        indexes = [
            models.Index(
                fields=["usuario"],
                condition=Q(revocado_en__isnull=True),
                name="ix_refresh_activo",
            ),
        ]


class AvisoCorreo(models.Model):
    """Registro de cada correo enviado (RF-09, ajuste A-08)."""

    id = models.BigAutoField(primary_key=True)
    usuario = models.ForeignKey(
        Usuario, on_delete=models.CASCADE, related_name="avisos", db_index=False
    )
    plantilla = models.CharField(max_length=40, choices=PlantillaAviso.choices)
    asunto = models.CharField(max_length=150)
    # Reserva que origino el aviso. Da idempotencia a la llamada interna.
    referencia_id = models.UUIDField(null=True, blank=True)
    estado = models.CharField(
        max_length=10, choices=EstadoAviso.choices, default=EstadoAviso.ENVIADO
    )
    error = models.CharField(max_length=300, null=True, blank=True)
    enviado_en = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "aviso_correo"
        constraints = [
            models.CheckConstraint(
                condition=Q(plantilla__in=PlantillaAviso.values),
                name="ck_aviso_plantilla",
            ),
            models.CheckConstraint(
                condition=Q(estado__in=EstadoAviso.values),
                name="ck_aviso_estado",
            ),
            models.UniqueConstraint(
                fields=["plantilla", "referencia_id", "usuario"],
                condition=Q(referencia_id__isnull=False),
                name="ux_aviso_idempotente",
            ),
        ]
        indexes = [
            models.Index(fields=["usuario", "-enviado_en"], name="ix_aviso_usuario"),
        ]
