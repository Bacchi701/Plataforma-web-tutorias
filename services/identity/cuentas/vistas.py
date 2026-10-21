"""API publica de Identidad (Pilar 2, seccion 4.1).

HU-04: POST /registro y POST /verificar-correo.
HU-05: POST /login, POST /refresh, POST /logout y GET /yo.
"""

from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .autenticacion import TokenDeAcceso
from .correos import enviar_verificacion
from .models import DOMINIO_INSTITUCIONAL, RefreshToken, TokenVerificacion, Usuario
from .secretos import hash_de, token_opaco
from .tokens import emitir_acceso

YA_EXISTE = "Ya existe una cuenta con este correo."

# La renovacion viaja en una cookie httpOnly que solo se envia a Identidad
# (Pilar 2, seccion 5.5): el JavaScript de la pagina nunca la ve.
COOKIE_RENOVACION = "refresh_token"
RUTA_COOKIE = "/api/identity/v1/"


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


# ---------------------------------------------------------------- sesion (HU-05)


class LoginSerializer(serializers.Serializer):
    email = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=128, trim_whitespace=False)


def respuesta_error(codigo, mensaje, estado):
    return Response(
        {"codigo": codigo, "mensaje": mensaje, "detalles": None}, status=estado
    )


def respuesta_con_sesion(usuario):
    """Token de acceso en el cuerpo y renovacion nueva en la cookie."""
    try:
        acceso = emitir_acceso(usuario)
    except ImproperlyConfigured as error:
        raise Rechazo(str(error), "claves_no_configuradas", 503) from error

    token, token_hash = token_opaco()
    ahora = timezone.now()
    RefreshToken.objects.create(
        usuario=usuario,
        token_hash=token_hash,
        creado_en=ahora,
        expira_en=ahora + timedelta(days=settings.REFRESH_DIAS),
    )
    respuesta = Response(
        {
            "token_acceso": acceso,
            "tipo_token": "Bearer",
            "expira_en_segundos": settings.JWT_MINUTOS_ACCESO * 60,
        }
    )
    respuesta.set_cookie(
        COOKIE_RENOVACION,
        token,
        max_age=settings.REFRESH_DIAS * 24 * 60 * 60,
        path=RUTA_COOKIE,
        httponly=True,
        secure=settings.COOKIE_REFRESH_SEGURA,
        samesite="Strict",
    )
    return respuesta


def cerrar_cookie(respuesta):
    respuesta.delete_cookie(COOKIE_RENOVACION, path=RUTA_COOKIE, samesite="Strict")
    return respuesta


@api_view(["POST"])
def login(request):
    """Inicio de sesion (HU-05, criterios 1, 2 y 5; HU-04, criterio 4)."""
    datos = LoginSerializer(data=request.data)
    datos.is_valid(raise_exception=True)
    email = datos.validated_data["email"].strip().lower()
    clave = datos.validated_data["password"]

    usuario = Usuario.objects.filter(email=email).first()
    if usuario is None:
        # Igual que el ModelBackend de Django: se calcula un hash para que la
        # respuesta tarde lo mismo exista o no la cuenta.
        Usuario().set_password(clave)
        raise Rechazo("Correo o contraseña incorrectos.", "credenciales_invalidas", 401)
    if not usuario.check_password(clave):
        raise Rechazo("Correo o contraseña incorrectos.", "credenciales_invalidas", 401)
    if not usuario.activo:
        raise Rechazo("Tu cuenta está desactivada.", "cuenta_desactivada", 403)
    if not usuario.email_verificado:
        raise Rechazo(
            "Verifica tu correo antes de iniciar sesión: revisa tu bandeja.",
            "correo_no_verificado",
            403,
        )
    return respuesta_con_sesion(usuario)


@api_view(["POST"])
def refresh(request):
    """Token de acceso nuevo sin volver a escribir la clave (HU-05, criterio 3).

    La renovacion usada se revoca y se entrega otra (rotacion): una cookie
    robada sirve, como mucho, hasta que el dueno vuelve a usar la suya.
    """
    token = request.COOKIES.get(COOKIE_RENOVACION, "")
    with transaction.atomic():
        sesion = None
        if token:
            sesion = (
                RefreshToken.objects.select_for_update()
                .select_related("usuario")
                .filter(
                    token_hash=hash_de(token),
                    revocado_en__isnull=True,
                    expira_en__gt=timezone.now(),
                )
                .first()
            )
        if sesion is None or not sesion.usuario.activo:
            # No se borra la cookie: si dos pestanas renuevan a la vez, la que
            # pierde borraria la renovacion nueva que acaba de recibir la otra.
            return respuesta_error(
                "sesion_invalida", "La sesión no es válida o venció.", 401
            )
        sesion.revocado_en = timezone.now()
        sesion.save(update_fields=["revocado_en"])
        return respuesta_con_sesion(sesion.usuario)


@api_view(["POST"])
def logout(request):
    """Revoca la renovacion de esta sesion (HU-05, criterio 4)."""
    token = request.COOKIES.get(COOKIE_RENOVACION)
    if token:
        RefreshToken.objects.filter(
            token_hash=hash_de(token), revocado_en__isnull=True
        ).update(revocado_en=timezone.now())
    return cerrar_cookie(Response(status=204))


@api_view(["GET"])
@authentication_classes([TokenDeAcceso])
@permission_classes([IsAuthenticated])
def yo(request):
    """Datos del usuario autenticado. El correo sale solo de aqui (RNF-07)."""
    usuario = request.user
    return Response(
        {
            "id": str(usuario.id),
            "email": usuario.email,
            "nombre": usuario.nombre,
            "apellido": usuario.apellido,
            "carrera_id": str(usuario.carrera_id) if usuario.carrera_id else None,
            "nivel": usuario.nivel,
            "sede_id": str(usuario.sede_id) if usuario.sede_id else None,
            "es_admin": usuario.es_admin,
        }
    )
