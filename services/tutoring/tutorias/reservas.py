"""Solicitar una tutoria y consultar las reservas (HU-21, RF-07).

POST /reservas, GET /reservas y GET /reservas/<id>, todo con sesion: quien
pide sale del token (HU-17).

- RN-03: la solicitud no ocupa el bloque. La reserva queda SOLICITADA y el
  bloque sigue LIBRE para otras solicitudes, hasta que el tutor confirme una
  (HU-22).
- T-166: solicitar es un contacto con Tutorias: crea o pone al dia la copia
  del solicitante (usuario_ref) con GET /yo de Identidad (copias.py). Se
  consulta antes de abrir la transaccion, para no dejarla abierta mientras se
  espera la respuesta.
- A-04: el monto es una copia congelada de la tarifa del perfil al solicitar.
- La base rechaza tambien la solicitud repetida (ux_reserva_solicitud_unica)
  y la del propio bloque (ck_reserva_no_auto, el disparador de la migracion
  0003): aqui solo se traduce ese rechazo.
- HU-16: despues de guardar, Tutorias pide a Identidad el aviso al tutor
  (pedir_aviso, llamadas.py). Si el aviso no sale, la solicitud queda igual.
- Las consultas salen de tutoring_db, sin llamar a otros servicios. Ninguna
  respuesta trae un correo: no esta en esta base (RNF-07). Son el backend de
  las pantallas «Mis reservas y solicitudes recibidas» (HU-30) y de pago
  (HU-24).
"""

import uuid
from functools import partial

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .bloques import Rechazo, instante_json
from .copias import asegurar_usuario_ref
from .llamadas import pedir_aviso
from .models import (
    BloqueDisponibilidad,
    EstadoBloque,
    EstadoReserva,
    PerfilTutor,
    Reserva,
)

RESTRICCION_SOLICITUD_UNICA = "ux_reserva_solicitud_unica"
RESTRICCION_NO_AUTO = "ck_reserva_no_auto"
SOLICITUD_RECIBIDA = "SOLICITUD_RECIBIDA"
LARGO_NOTA = 500
MAXIMO_RESERVAS = 100
ESTUDIANTE = "estudiante"
TUTOR = "tutor"

BLOQUE_INVALIDO = "Elige uno de los horarios disponibles del tutor."
ASIGNATURA_INVALIDA = "Elige la asignatura de la tutoría."
BLOQUE_NO_ENCONTRADO = (
    "No encontramos ese horario: puede que el tutor lo haya eliminado."
)
BLOQUE_PROPIO = "No puedes solicitar una tutoría en tu propio bloque."
YA_EMPEZO = "Ese horario ya empezó. Elige otro."
NO_DISPONIBLE = "Ese horario ya tiene una tutoría confirmada. Elige otro."
NO_OFRECIDA = "El tutor no ofrece esa asignatura."
DUPLICADA = "Ya tienes una solicitud pendiente para ese horario."
ROL_INVALIDO = "Indica el rol: ?rol=estudiante o ?rol=tutor."
ESTADO_INVALIDO = (
    "El estado tiene que ser uno de estos: SOLICITADA, CONFIRMADA, RECHAZADA, "
    "EXPIRADA, CANCELADA, REALIZADA o EVALUADA."
)
RESERVA_NO_ENCONTRADA = "No encontramos esa tutoría."


# ------------------------------------------------------------ el formato


def fecha_o_nada(valor):
    return None if valor is None else instante_json(valor)


def persona_json(usuario):
    """Lo de usuario_ref que se muestra: sin correo, que no esta aqui."""
    return {
        "usuario_id": str(usuario.usuario_id),
        "nombre": usuario.nombre,
        "apellido": usuario.apellido,
    }


def reserva_json(reserva, rol):
    """Una reserva, vista por quien consulta (rol: estudiante o tutor)."""
    bloque = reserva.bloque
    asignatura = reserva.asignatura
    return {
        "id": str(reserva.id),
        "estado": reserva.estado,
        "nota": reserva.nota,
        "modalidad": reserva.modalidad,
        "lugar_o_enlace": reserva.lugar_o_enlace,
        "monto": int(reserva.monto),
        "estado_pago": reserva.estado_pago,
        "creada_en": instante_json(reserva.creada_en),
        "confirmada_en": fecha_o_nada(reserva.confirmada_en),
        "cerrada_en": fecha_o_nada(reserva.cerrada_en),
        "bloque": {
            "id": str(bloque.id),
            "inicio_en": instante_json(bloque.inicio_en),
            "fin_en": instante_json(bloque.fin_en),
        },
        "asignatura": {
            "asignatura_id": str(asignatura.asignatura_id),
            "sigla": asignatura.sigla,
            "nombre": asignatura.nombre,
        },
        # El tutor es el dueno del bloque: la reserva no lo guarda (3FN).
        "tutor": persona_json(bloque.usuario),
        "solicitante": persona_json(reserva.solicitante_usuario),
        "rol": rol,
    }


def reservas_con_todo():
    """Reservas con el bloque y su tutor, el solicitante y la asignatura.

    Todo en la misma consulta: sin una consulta por fila.
    """
    return Reserva.objects.select_related(
        "bloque__usuario", "solicitante_usuario", "asignatura"
    )


# ------------------------------------------------------------ el cuerpo


def cuerpo(request):
    return request.data if isinstance(request.data, dict) else {}


def leer_uuid(datos, campo):
    valor = datos.get(campo)
    try:
        return uuid.UUID(valor) if isinstance(valor, str) else None
    except ValueError:
        return None


def leer_nota(datos):
    """Texto de hasta 500 caracteres, sin espacios a los lados, o None."""
    valor = datos.get("nota")
    if valor is None:
        return None
    if not isinstance(valor, str):
        raise Rechazo("La nota tiene que ser un texto.", "nota_invalida")
    # PostgreSQL no guarda el caracter nulo, y una mitad de par sustituto no se
    # puede codificar: los dos terminarian en un error 500 al guardar.
    if any(c == "\x00" or "\ud800" <= c <= "\udfff" for c in valor):
        raise Rechazo(
            "La nota tiene caracteres que no se pueden guardar.", "nota_invalida"
        )
    valor = valor.strip()
    if len(valor) > LARGO_NOTA:
        raise Rechazo(
            f"La nota puede tener hasta {LARGO_NOTA} caracteres.", "nota_invalida"
        )
    return valor or None


# ------------------------------------------------------------ solicitar


def guardar_solicitud(reserva):
    """Crea la reserva. Si la base la rechaza por una regla de HU-21, responde."""
    try:
        with transaction.atomic():
            reserva.save(force_insert=True)
    except IntegrityError as error:
        diagnostico = getattr(error.__cause__, "diag", None)
        restriccion = getattr(diagnostico, "constraint_name", None)
        if restriccion == RESTRICCION_SOLICITUD_UNICA:
            raise Rechazo(
                DUPLICADA, "solicitud_duplicada", status.HTTP_409_CONFLICT
            ) from error
        if restriccion == RESTRICCION_NO_AUTO:
            raise Rechazo(BLOQUE_PROPIO, "bloque_propio") from error
        raise


def solicitar(request):
    """Criterios 1 a 6. Responde 201 con la reserva SOLICITADA."""
    # 1. El cuerpo, sin llamar a nadie.
    datos = cuerpo(request)
    bloque_id = leer_uuid(datos, "bloque_id")
    if bloque_id is None:
        raise Rechazo(BLOQUE_INVALIDO, "bloque_invalido")
    asignatura_id = leer_uuid(datos, "asignatura_id")
    if asignatura_id is None:
        raise Rechazo(ASIGNATURA_INVALIDA, "asignatura_invalida")
    nota = leer_nota(datos)

    # 2. La copia del solicitante (criterio 4): una llamada a Identidad, antes
    # de la transaccion. Sus errores ya responden 401, 403 o 503.
    usuario, _ = asegurar_usuario_ref(request)

    # 3. El bloque, bloqueado hasta el fin de la transaccion. Solo esa fila:
    # el tutor se lee en la misma consulta, sin bloquearlo.
    with transaction.atomic():
        bloque = (
            BloqueDisponibilidad.objects.select_for_update(of=("self",))
            .select_related("usuario")
            .filter(id=bloque_id)
            .exclude(estado=EstadoBloque.ELIMINADO)
            .first()
        )
        if bloque is None:
            raise Rechazo(
                BLOQUE_NO_ENCONTRADO,
                "bloque_no_encontrado",
                status.HTTP_404_NOT_FOUND,
            )
        if bloque.usuario_id == usuario.usuario_id:
            raise Rechazo(BLOQUE_PROPIO, "bloque_propio")
        if bloque.inicio_en <= timezone.now():
            raise Rechazo(YA_EMPEZO, "bloque_en_el_pasado")
        if bloque.estado != EstadoBloque.LIBRE:
            raise Rechazo(
                NO_DISPONIBLE, "bloque_no_disponible", status.HTTP_409_CONFLICT
            )
        perfil = (
            PerfilTutor.objects.select_related("asignatura")
            .filter(
                usuario_id=bloque.usuario_id, asignatura_id=asignatura_id, activo=True
            )
            .first()
        )
        if perfil is None or not bloque.usuario.activo:
            raise Rechazo(NO_OFRECIDA, "asignatura_no_ofrecida")

        # Criterios 1 y 5: SOLICITADA, con el monto congelado (A-04) y sin
        # estado de pago. El bloque no cambia: sigue LIBRE (RN-03).
        reserva = Reserva(
            bloque=bloque,
            solicitante_usuario=usuario,
            asignatura=perfil.asignatura,
            estado=EstadoReserva.SOLICITADA,
            nota=nota,
            monto=perfil.tarifa,
            estado_pago=None,
        )
        guardar_solicitud(reserva)
        # Criterio 6: el aviso al tutor sale cuando la reserva ya quedo
        # guardada. Si la transaccion se deshace, no sale.
        transaction.on_commit(
            partial(pedir_aviso, bloque.usuario_id, SOLICITUD_RECIBIDA, reserva)
        )
    return Response(reserva_json(reserva, ESTUDIANTE), status=status.HTTP_201_CREATED)


# ------------------------------------------------------------ consultar


def listar(request):
    """?rol=estudiante: las que solicito; ?rol=tutor: las de sus bloques.

    ?estado= deja solo las de ese estado. De la mas nueva a la mas antigua,
    hasta 100, en una sola consulta. No llama a otros servicios.
    """
    rol = request.query_params.get("rol")
    if rol not in (ESTUDIANTE, TUTOR):
        raise Rechazo(ROL_INVALIDO, "rol_invalido")
    estado = request.query_params.get("estado")
    if estado is not None and estado not in EstadoReserva.values:
        raise Rechazo(ESTADO_INVALIDO, "estado_invalido")

    usuario_id = request.user.usuario_id
    reservas = reservas_con_todo()
    if rol == ESTUDIANTE:
        reservas = reservas.filter(solicitante_usuario_id=usuario_id)
    else:
        reservas = reservas.filter(bloque__usuario_id=usuario_id)
    if estado is not None:
        reservas = reservas.filter(estado=estado)
    reservas = reservas.order_by("-creada_en", "id")[:MAXIMO_RESERVAS]
    return Response([reserva_json(reserva, rol) for reserva in reservas])


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def solicitar_o_listar(request):
    """GET /reservas?rol=estudiante|tutor[&estado=] y POST /reservas."""
    if request.method == "POST":
        return solicitar(request)
    return listar(request)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def una_reserva(request, reserva_id):
    """GET /reservas/<id>: una reserva en que es el solicitante o el tutor.

    Para cualquier otro, el mismo 404 que si no existiera, para no revelar que
    existe. No llama a otros servicios.
    """
    usuario_id = request.user.usuario_id
    reserva = (
        reservas_con_todo()
        .filter(id=reserva_id)
        .filter(Q(solicitante_usuario_id=usuario_id) | Q(bloque__usuario_id=usuario_id))
        .first()
    )
    if reserva is None:
        raise Rechazo(
            RESERVA_NO_ENCONTRADA, "reserva_no_encontrada", status.HTTP_404_NOT_FOUND
        )
    rol = ESTUDIANTE if reserva.solicitante_usuario_id == usuario_id else TUTOR
    return Response(reserva_json(reserva, rol))
