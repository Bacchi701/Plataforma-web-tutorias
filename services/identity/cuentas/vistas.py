"""API publica de Identidad (Pilar 2, seccion 4.1).

HU-04: POST /registro y POST /verificar-correo.
"""

from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response

from .correos import enviar_verificacion
from .models import DOMINIO_INSTITUCIONAL, TokenVerificacion, Usuario
from .secretos import hash_de, token_opaco

YA_EXISTE = "Ya existe una cuenta con este correo."


class Rechazo(APIException):
    """Error con codigo propio, en el formato uniforme de la API."""

    def __init__(self, mensaje, codigo, estado=400):
        self.status_code = estado
        super().__init__(detail=mensaje, code=codigo)


class RegistroSerializer(serializers.Serializer):
    nombre = serializers.CharField(max_length=80)
    apellido = serializers.CharField(max_length=80)
    email = serializers.EmailField(max_length=150)
    password = serializers.CharField(
        min_length=8,
        max_length=128,
        trim_whitespace=False,
        error_messages={
            "min_length": "La contraseña debe tener al menos 8 caracteres."
        },
    )

    def validate_email(self, valor):
        email = valor.strip().lower()
        if not email.endswith(DOMINIO_INSTITUCIONAL):
            raise serializers.ValidationError(
                "Usa tu correo institucional, que termina en @duocuc.cl."
            )
        if Usuario.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError(YA_EXISTE)
        return email


@api_view(["POST"])
def registro(request):
    """Crea la cuenta sin verificar y envia el enlace (HU-04, criterios 1 y 2)."""
    datos = RegistroSerializer(data=request.data)
    datos.is_valid(raise_exception=True)

    try:
        with transaction.atomic():
            usuario = Usuario.objects.create_user(**datos.validated_data)
            token, token_hash = token_opaco()
            ahora = timezone.now()
            TokenVerificacion.objects.create(
                usuario=usuario,
                token_hash=token_hash,
                creado_en=ahora,
                expira_en=ahora + timedelta(hours=settings.VERIFICACION_HORAS),
            )
    except IntegrityError as error:
        # Dos registros simultaneos con el mismo correo: gana el primero.
        raise ValidationError({"email": [YA_EXISTE]}) from error

    enviado = enviar_verificacion(usuario, token)
    return Response(
        {"id": str(usuario.id), "email": usuario.email, "correo_enviado": enviado},
        status=201,
    )


@api_view(["POST"])
def verificar_correo(request):
    """Verifica la cuenta con el token del correo (HU-04, criterio 3)."""
    token = str(request.data.get("token", "")).strip()
    if not token:
        raise ValidationError({"token": ["Falta el token del enlace."]})

    with transaction.atomic():
        fila = (
            TokenVerificacion.objects.select_for_update()
            .select_related("usuario")
            .filter(token_hash=hash_de(token))
            .first()
        )
        if fila is None:
            raise Rechazo("El enlace no es válido.", "token_invalido")
        if fila.usado_en is not None:
            raise Rechazo(
                "Este enlace ya se usó. Si tu cuenta está verificada, inicia sesión.",
                "token_usado",
            )
        if fila.expira_en <= timezone.now():
            raise Rechazo("El enlace venció. Pide uno nuevo.", "token_vencido")

        fila.usado_en = timezone.now()
        fila.save(update_fields=["usado_en"])
        usuario = fila.usuario
        usuario.email_verificado = True
        usuario.save(update_fields=["email_verificado", "actualizado_en"])

    return Response(
        {"mensaje": "Tu correo quedó verificado. Ya puedes iniciar sesión."}
    )
