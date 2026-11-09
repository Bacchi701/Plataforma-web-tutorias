"""Vistas internas de Identidad (Pilar 2, seccion 5.4).

Se comunican exclusivamente dentro de la red de Docker autenticadas con
la cabecera X-Clave-Servicio.
"""

import hmac
import uuid

from django.conf import settings
from rest_framework import serializers
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from .correos import MODALIDADES, PLANTILLAS_DE_RESERVA, enviar_aviso_de_reserva
from .models import PlantillaAviso, Usuario
from .vistas import Rechazo


class ClaveDeServicio(BasePermission):
    """Permiso para rutas internas entre servicios."""

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


def usuario_json(usuario):
    """Los siete campos de un usuario en las rutas internas.

    Nunca el correo, el hash de la clave ni es_admin (RNF-07).
    """
    return {
        "id": str(usuario.id),
        "nombre": usuario.nombre,
        "apellido": usuario.apellido,
        "carrera_id": str(usuario.carrera_id) if usuario.carrera_id else None,
        "nivel": usuario.nivel,
        "sede_id": str(usuario.sede_id) if usuario.sede_id else None,
        "activo": usuario.activo,
    }


@api_view(["GET"])
@authentication_classes([])
@permission_classes([ClaveDeServicio])
def un_usuario(request, usuario_id):
    """Consulta interna de los datos de un usuario por su UUID."""
    try:
        usuario = Usuario.objects.get(id=usuario_id)
    except Usuario.DoesNotExist:
        raise NotFound("El usuario no existe.", code="usuario_no_encontrado") from None

    return Response(usuario_json(usuario))


@api_view(["GET"])
@authentication_classes([])
@permission_classes([ClaveDeServicio])
def varios_usuarios(request):
    """GET /internal/usuarios?ids=<uuid>,<uuid>,... (HU-19, ajuste A-01).

    Los datos de hasta 100 usuarios en una sola consulta, para la
    sincronizacion de las copias de Tutorias. Los ids van separados por comas
    en un solo parametro: se ignoran los espacios y las partes vacias, y un id
    repetido cuenta una vez. Los que no existen no salen, asi que la lista
    puede venir mas corta, o vacia. Una cuenta desactivada sale con activo
    false. Ordenada por id.
    """
    invalidos = "Indica los usuarios en ?ids=, separados por comas."
    ids = set()
    for parte in request.query_params.get("ids", "").split(","):
        texto = parte.strip()
        if not texto:
            continue
        try:
            ids.add(uuid.UUID(texto))
        except ValueError:
            raise Rechazo(invalidos, "ids_invalidos") from None
    if not ids:
        raise Rechazo(invalidos, "ids_invalidos")
    # Tutorias pide de a 50.
    if len(ids) > 100:
        raise Rechazo("Pide hasta 100 usuarios por llamada.", "demasiados_ids")

    usuarios = Usuario.objects.filter(id__in=ids).order_by("id")
    return Response([usuario_json(usuario) for usuario in usuarios])


# --------------------------------------------- POST /internal/avisos (HU-16)

PLANTILLA_INVALIDA = (
    "La plantilla tiene que ser un aviso de reserva: SOLICITUD_RECIBIDA, "
    "RESERVA_CONFIRMADA, RESERVA_RECHAZADA o RESERVA_CANCELADA."
)
SIN_MODALIDAD = "Indica la modalidad de la tutoría confirmada: PRESENCIAL o EN_LINEA."
SIN_LUGAR_O_ENLACE = "Indica el lugar o el enlace de la tutoría confirmada."


# Los largos son los de las columnas de Tutorias de donde salen los datos:
# asignatura_ref, usuario_ref y reserva.
class AsignaturaDelAviso(serializers.Serializer):
    sigla = serializers.CharField(max_length=15)
    nombre = serializers.CharField(max_length=150)


class PersonaDelAviso(serializers.Serializer):
    nombre = serializers.CharField(max_length=80)
    apellido = serializers.CharField(max_length=80)


class DatosDelAviso(serializers.Serializer):
    asignatura = AsignaturaDelAviso()
    inicio_en = serializers.DateTimeField()
    fin_en = serializers.DateTimeField()
    otra_persona = PersonaDelAviso()
    # Opcionales, y aceptan null o vacio: una solicitud no tiene modalidad.
    nota = serializers.CharField(
        max_length=500, required=False, allow_null=True, allow_blank=True
    )
    modalidad = serializers.ChoiceField(
        choices=list(MODALIDADES), required=False, allow_null=True, allow_blank=True
    )
    lugar_o_enlace = serializers.CharField(
        max_length=300, required=False, allow_null=True, allow_blank=True
    )


class AvisoSerializer(serializers.Serializer):
    usuario_id = serializers.UUIDField()
    plantilla = serializers.ChoiceField(
        choices=[plantilla.value for plantilla in PLANTILLAS_DE_RESERVA],
        error_messages={"invalid_choice": PLANTILLA_INVALIDA},
    )
    referencia_id = serializers.UUIDField()
    datos = DatosDelAviso()

    def validate(self, valores):
        # La confirmacion muestra la modalidad y el lugar o el enlace (criterio 2).
        if valores["plantilla"] == PlantillaAviso.RESERVA_CONFIRMADA:
            datos = valores["datos"]
            faltan = {}
            if not datos.get("modalidad"):
                faltan["modalidad"] = [SIN_MODALIDAD]
            if not datos.get("lugar_o_enlace"):
                faltan["lugar_o_enlace"] = [SIN_LUGAR_O_ENLACE]
            if faltan:
                raise serializers.ValidationError({"datos": faltan})
        return valores


@api_view(["POST"])
@authentication_classes([])
@permission_classes([ClaveDeServicio])
def enviar_aviso(request):
    """POST /internal/avisos (HU-16): el aviso por correo de una reserva.

    Lo pide Tutorias con pedir_aviso (tutorias/llamadas.py), con la cabecera
    X-Clave-Servicio y sin Authorization. Las rutas /internal no van en
    docs/api (convencion de F1): este docstring es su contrato.

    El cuerpo:

        {"usuario_id": "<uuid del destinatario>",
         "plantilla": "SOLICITUD_RECIBIDA",
         "referencia_id": "<uuid de la reserva>",
         "datos": {"asignatura": {"sigla": "BDD1101", "nombre": "Base de Datos"},
                   "inicio_en": "2026-11-06T21:00:00Z",
                   "fin_en": "2026-11-06T22:00:00Z",
                   "otra_persona": {"nombre": "Camila", "apellido": "Rojas"},
                   "nota": "un texto o null",
                   "modalidad": "PRESENCIAL, EN_LINEA o null",
                   "lugar_o_enlace": "un texto o null"}}

    - plantilla: SOLICITUD_RECIBIDA, RESERVA_CONFIRMADA, RESERVA_RECHAZADA o
      RESERVA_CANCELADA. Con RESERVA_CONFIRMADA, modalidad y lugar_o_enlace
      son obligatorios.
    - otra_persona es la otra parte de la reserva. El correo del destinatario
      no viene en el cuerpo: lo pone Identidad.
    - Las fechas van en ISO 8601; Tutorias las manda en UTC, con Z. El correo
      las muestra en hora de Chile.
    - No se revisa si la cuenta esta activa o verificada, ni si la reserva
      existe: Identidad no conoce las reservas (Pilar 2, seccion 3).

    Respuestas (ninguna lleva el correo del destinatario ni el id del aviso):
    - 201 {"estado": "ENVIADO" o "FALLIDO", "repetido": false}: un aviso
      nuevo, registrado en aviso_correo. FALLIDO quiere decir que la bandeja
      no lo recibio; el aviso queda registrado igual, como en /registro.
    - 200 {"estado": <el del aviso que ya estaba>, "repetido": true}: ese
      aviso (plantilla, reserva y destinatario) ya existia, y no se envia otro
      correo, tampoco si el primero quedo FALLIDO (ux_aviso_idempotente, A-08).
    - 400 invalid: el cuerpo no calza, con los detalles por campo.
    - 404 usuario_no_encontrado: no existe el destinatario.
    - 404 ruta_no_encontrada: sin la clave de servicio, o con otra.
    - 405 method_not_allowed: otro metodo que POST, con la clave.
    """
    pedido = AvisoSerializer(data=request.data)
    pedido.is_valid(raise_exception=True)
    valores = pedido.validated_data
    try:
        usuario = Usuario.objects.get(id=valores["usuario_id"])
    except Usuario.DoesNotExist:
        raise NotFound("El usuario no existe.", code="usuario_no_encontrado") from None

    aviso, creado = enviar_aviso_de_reserva(
        usuario, valores["plantilla"], valores["referencia_id"], valores["datos"]
    )
    return Response(
        {"estado": aviso.estado, "repetido": not creado},
        status=201 if creado else 200,
    )
