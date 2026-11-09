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

HU-22: POST /reservas/<id>/confirmar y POST /reservas/<id>/rechazar, solo para
el tutor, que es el dueno del bloque de la reserva.

- Confirmar escribe estado, modalidad, lugar_o_enlace y confirmada_en, pasa el
  bloque a OCUPADO y las demas solicitudes del bloque a RECHAZADA, todo en una
  transaccion (anexo A, seccion 9). Rechazar escribe estado y cerrada_en.
- Las dos bloquean siempre en el mismo orden: primero el bloque y despues la
  reserva. Asi dos confirmaciones del mismo bloque, o una confirmacion y un
  rechazo, se esperan en vez de bloquearse entre si, y la segunda ve lo que
  dejo la primera. Si aun asi llegaran dos confirmaciones, la base deja una
  sola (ux_reserva_bloque_ocupado, ajuste A-03).
- T-174: estado_pago queda nulo al confirmar. Pasa a PENDIENTE cuando Pagos
  crea el pago y lo informa a Tutorias (HU-23): Pagos es la unica fuente del
  estado del pago.
- Despues de guardar se pide a Identidad el aviso a cada estudiante
  (RESERVA_CONFIRMADA o RESERVA_RECHAZADA, HU-16).

HU-28 (parte A): POST /reservas/<id>/cancelar, para el solicitante o el tutor.

- El estudiante retira su solicitud SOLICITADA: queda CANCELADA y el bloque
  no cambia, porque nunca estuvo ocupado. El tutor no retira una solicitud:
  la rechaza (RN-04).
- Cualquiera de las dos partes cancela una reserva CONFIRMADA que todavia no
  empieza: queda CANCELADA y el bloque vuelve a LIBRE (RN-04, CA9).
- Las dos escriben estado, cerrada_en y quien cancelo (cancelada_por_usuario),
  y bloquean en el mismo orden que confirmar y rechazar.
- Despues de guardar se pide a Identidad el aviso RESERVA_CANCELADA para la
  otra parte (HU-16).
- El reembolso de una reserva pagada (criterio 3) no esta aqui: llega con la
  parte B de HU-28, cuando exista Pagos (HU-23). La expiracion de las
  solicitudes esta en por_tiempo.py.
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
    Modalidad,
    PerfilTutor,
    Reserva,
)

RESTRICCION_SOLICITUD_UNICA = "ux_reserva_solicitud_unica"
RESTRICCION_NO_AUTO = "ck_reserva_no_auto"
RESTRICCION_BLOQUE_OCUPADO = "ux_reserva_bloque_ocupado"
SOLICITUD_RECIBIDA = "SOLICITUD_RECIBIDA"
RESERVA_CONFIRMADA = "RESERVA_CONFIRMADA"
RESERVA_RECHAZADA = "RESERVA_RECHAZADA"
RESERVA_CANCELADA = "RESERVA_CANCELADA"
LARGO_NOTA = 500
LARGO_LUGAR = 300
PREFIJOS_ENLACE = ("http://", "https://")
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
MODALIDAD_INVALIDA = "Indica la modalidad de la tutoría: PRESENCIAL o EN_LINEA."
SIN_LUGAR = "Indica el lugar de la tutoría presencial."
SIN_ENLACE = "Indica el enlace de la tutoría en línea."
LUGAR_NO_ES_TEXTO = "El lugar o el enlace tiene que ser un texto."
LUGAR_CON_CARACTERES = "El lugar o el enlace tiene caracteres que no se pueden guardar."
LUGAR_LARGO = f"El lugar o el enlace puede tener hasta {LARGO_LUGAR} caracteres."
ENLACE_INVALIDO = (
    "El enlace de una tutoría en línea tiene que empezar con http:// o https://."
)
NO_PENDIENTE = "Esa solicitud ya no está pendiente."
YA_EMPEZO_AL_CONFIRMAR = "Ese horario ya empezó: la tutoría ya no se puede confirmar."
BLOQUE_OCUPADO = "Ese horario ya tiene otra tutoría confirmada."
NO_CANCELABLE = "Esta reserva ya no se puede cancelar: está {estado}."
SOLO_RETIRA_QUIEN_PIDIO = (
    "Una solicitud pendiente solo la retira quien la pidió. Como tutor, puedes "
    "rechazarla."
)
YA_EMPEZO_AL_CANCELAR = "La tutoría ya empezó: ya no se puede cancelar ni retirar."


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


# ------------------------------------------------------------ confirmar (HU-22)


def leer_modalidad(datos):
    """PRESENCIAL o EN_LINEA (RN-07)."""
    modalidad = datos.get("modalidad")
    if modalidad not in Modalidad.values:
        raise Rechazo(MODALIDAD_INVALIDA, "modalidad_invalida")
    return modalidad


def leer_lugar_o_enlace(datos, modalidad):
    """Texto de 1 a 300 caracteres, sin espacios a los lados (RN-07).

    En linea, un enlace que empieza con http:// o https://.
    """
    valor = datos.get("lugar_o_enlace")
    falta = SIN_ENLACE if modalidad == Modalidad.EN_LINEA else SIN_LUGAR
    if valor is None:
        raise Rechazo(falta, "lugar_o_enlace_invalido")
    if not isinstance(valor, str):
        raise Rechazo(LUGAR_NO_ES_TEXTO, "lugar_o_enlace_invalido")
    # Como en la nota: el caracter nulo y una mitad de par sustituto
    # terminarian en un error 500 al guardar.
    if any(c == "\x00" or "\ud800" <= c <= "\udfff" for c in valor):
        raise Rechazo(LUGAR_CON_CARACTERES, "lugar_o_enlace_invalido")
    valor = valor.strip()
    if not valor:
        raise Rechazo(falta, "lugar_o_enlace_invalido")
    if len(valor) > LARGO_LUGAR:
        raise Rechazo(LUGAR_LARGO, "lugar_o_enlace_invalido")
    if modalidad == Modalidad.EN_LINEA and not valor.startswith(PREFIJOS_ENLACE):
        raise Rechazo(ENLACE_INVALIDO, "lugar_o_enlace_invalido")
    return valor


def solicitud_bloqueada(request, reserva_id):
    """La solicitud y su bloque, bloqueados hasta el fin de la transaccion.

    Siempre en este orden, el mismo de las dos rutas:
    a. la reserva, sin bloquearla, solo para saber su bloque y que el bloque
       es del usuario del token;
    b. el bloque;
    c. la reserva otra vez, ahora bloqueada (solo su fila). Recien ahi se
       revisa su estado: si otra peticion la cambio mientras se esperaba el
       bloque, aqui ya se ve el cambio.
    """
    # a. El solicitante, otro usuario o una reserva que no existe: el mismo 404,
    # para no revelar que existe.
    usuario_id = request.user.usuario_id
    bloque_id = (
        Reserva.objects.filter(id=reserva_id, bloque__usuario_id=usuario_id)
        .values_list("bloque_id", flat=True)
        .first()
    )
    if bloque_id is None:
        raise Rechazo(
            RESERVA_NO_ENCONTRADA, "reserva_no_encontrada", status.HTTP_404_NOT_FOUND
        )
    # b.
    bloque = BloqueDisponibilidad.objects.select_for_update().get(pk=bloque_id)
    # c. Con of=("self",): el tutor, el solicitante y la asignatura se leen en
    # la misma consulta, sin bloquear sus filas.
    reserva = (
        Reserva.objects.select_for_update(of=("self",))
        .select_related("bloque__usuario", "solicitante_usuario", "asignatura")
        .get(pk=reserva_id)
    )
    if reserva.estado != EstadoReserva.SOLICITADA:
        raise Rechazo(NO_PENDIENTE, "reserva_no_pendiente", status.HTTP_409_CONFLICT)
    return bloque, reserva


def guardar_confirmacion(reserva):
    """Guarda la reserva CONFIRMADA.

    Si la base la rechaza porque el bloque ya tiene una reserva que lo ocupa
    (ux_reserva_bloque_ocupado, la garantia de ultimo recurso del criterio 4),
    responde 409.
    """
    try:
        with transaction.atomic():
            reserva.save(
                update_fields=["estado", "modalidad", "lugar_o_enlace", "confirmada_en"]
            )
    except IntegrityError as error:
        diagnostico = getattr(error.__cause__, "diag", None)
        if getattr(diagnostico, "constraint_name", None) != RESTRICCION_BLOQUE_OCUPADO:
            raise
        raise Rechazo(
            BLOQUE_OCUPADO, "bloque_ocupado", status.HTTP_409_CONFLICT
        ) from error


def rechazar_las_demas(bloque, confirmada, ahora):
    """Criterio 3 (RN-03): las otras solicitudes pendientes del bloque.

    Pasan a RECHAZADA con cerrada_en. Se leen bloqueadas, con lo que necesita
    su aviso, y se devuelven para pedirlo.
    """
    demas = list(
        Reserva.objects.select_for_update(of=("self",))
        .select_related("bloque__usuario", "solicitante_usuario", "asignatura")
        .filter(bloque_id=bloque.id, estado=EstadoReserva.SOLICITADA)
        .exclude(id=confirmada.id)
        .order_by("creada_en", "id")
    )
    for otra in demas:
        otra.estado = EstadoReserva.RECHAZADA
        otra.cerrada_en = ahora
    Reserva.objects.filter(id__in=[otra.id for otra in demas]).update(
        estado=EstadoReserva.RECHAZADA, cerrada_en=ahora
    )
    return demas


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def confirmar(request, reserva_id):
    """POST /reservas/<id>/confirmar: el tutor confirma una solicitud.

    Criterios 1 a 4, 6 y 7. Responde 200 con la reserva CONFIRMADA.
    """
    # 1. El cuerpo, antes de tocar la base (criterio 2, RN-07).
    datos = cuerpo(request)
    modalidad = leer_modalidad(datos)
    lugar_o_enlace = leer_lugar_o_enlace(datos, modalidad)

    # 2. Todo en una transaccion, con el bloque y la reserva bloqueados.
    with transaction.atomic():
        bloque, reserva = solicitud_bloqueada(request, reserva_id)
        ahora = timezone.now()
        if bloque.inicio_en <= ahora:
            raise Rechazo(YA_EMPEZO_AL_CONFIRMAR, "bloque_en_el_pasado")
        if bloque.estado == EstadoBloque.OCUPADO:
            raise Rechazo(BLOQUE_OCUPADO, "bloque_ocupado", status.HTTP_409_CONFLICT)

        # Criterio 1 (CA4). estado_pago no se toca: queda nulo hasta que Pagos
        # cree el pago (T-174).
        reserva.estado = EstadoReserva.CONFIRMADA
        reserva.modalidad = modalidad
        reserva.lugar_o_enlace = lugar_o_enlace
        reserva.confirmada_en = ahora
        guardar_confirmacion(reserva)
        bloque.estado = EstadoBloque.OCUPADO
        bloque.save(update_fields=["estado", "actualizado_en"])
        rechazadas = rechazar_las_demas(bloque, reserva, ahora)

        # 3. Criterio 7: los avisos salen cuando todo quedo guardado. Si la
        # transaccion se deshace, no sale ninguno.
        transaction.on_commit(
            partial(
                pedir_aviso, reserva.solicitante_usuario_id, RESERVA_CONFIRMADA, reserva
            )
        )
        for otra in rechazadas:
            transaction.on_commit(
                partial(
                    pedir_aviso, otra.solicitante_usuario_id, RESERVA_RECHAZADA, otra
                )
            )
    # 4.
    return Response(reserva_json(reserva, TUTOR))


# ------------------------------------------------------------ rechazar (HU-22)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def rechazar(request, reserva_id):
    """POST /reservas/<id>/rechazar: el tutor rechaza una solicitud.

    Criterio 5: la reserva pasa a RECHAZADA y el bloque no cambia. Sin cuerpo.
    Bloquea en el mismo orden que la confirmacion, porque un rechazo puede
    llegar al mismo tiempo que una confirmacion del mismo bloque. Responde 200
    con la reserva RECHAZADA.
    """
    with transaction.atomic():
        _, reserva = solicitud_bloqueada(request, reserva_id)
        reserva.estado = EstadoReserva.RECHAZADA
        reserva.cerrada_en = timezone.now()
        reserva.save(update_fields=["estado", "cerrada_en"])
        # Criterio 7.
        transaction.on_commit(
            partial(
                pedir_aviso, reserva.solicitante_usuario_id, RESERVA_RECHAZADA, reserva
            )
        )
    return Response(reserva_json(reserva, TUTOR))


# ------------------------------------------------------------ cancelar (HU-28)


def no_cancelable(estado):
    """409 de una reserva que ya no esta SOLICITADA ni CONFIRMADA (criterio 4).

    El mensaje dice en que estado esta, por ejemplo «...: está rechazada.».
    """
    return Rechazo(
        NO_CANCELABLE.format(estado=estado.lower()),
        "reserva_no_cancelable",
        status.HTTP_409_CONFLICT,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def cancelar(request, reserva_id):
    """POST /reservas/<id>/cancelar: retirar una solicitud o cancelar una tutoria.

    Criterios 1, 2 y 4 de HU-28. Sin cuerpo: si viene uno, se ignora. Responde
    200 con la reserva CANCELADA, leida de nuevo despues de la transaccion.
    """
    # 1. Sin bloquear: la reserva y su bloque. Si no existe, o si quien pide
    # no es el solicitante ni el tutor (el dueno del bloque), el mismo 404 de
    # GET /reservas/<id>, para no revelar que existe.
    usuario_id = request.user.usuario_id
    leida = (
        Reserva.objects.select_related("bloque")
        .filter(id=reserva_id)
        .filter(Q(solicitante_usuario_id=usuario_id) | Q(bloque__usuario_id=usuario_id))
        .first()
    )
    if leida is None:
        raise Rechazo(
            RESERVA_NO_ENCONTRADA, "reserva_no_encontrada", status.HTTP_404_NOT_FOUND
        )
    # Nadie se reserva su propio bloque (ck_reserva_no_auto): es una o la otra.
    es_tutor = leida.bloque.usuario_id == usuario_id

    # 2. En una transaccion, en el orden de confirmar (HU-22): asi una
    # cancelacion y una confirmacion del mismo bloque se esperan, en vez de
    # bloquearse entre si, y la segunda ve lo que dejo la primera.
    with transaction.atomic():
        # b. El bloque.
        bloque = BloqueDisponibilidad.objects.select_for_update().get(
            pk=leida.bloque_id
        )
        # c. La reserva otra vez, ahora bloqueada (solo su fila). Recien aqui
        # se revisa su estado.
        reserva = (
            Reserva.objects.select_for_update(of=("self",))
            .select_related("bloque__usuario", "solicitante_usuario", "asignatura")
            .get(pk=reserva_id)
        )
        estado = reserva.estado
        if estado not in (EstadoReserva.SOLICITADA, EstadoReserva.CONFIRMADA):
            raise no_cancelable(estado)
        if estado == EstadoReserva.SOLICITADA and es_tutor:
            # RN-04: retirar es del estudiante; el tutor la rechaza (HU-22).
            raise Rechazo(
                SOLO_RETIRA_QUIEN_PIDIO,
                "reserva_no_cancelable",
                status.HTTP_409_CONFLICT,
            )
        ahora = timezone.now()
        if bloque.inicio_en <= ahora:
            # Tambien una solicitud que el programador todavia no expira.
            raise Rechazo(YA_EMPEZO_AL_CANCELAR, "bloque_en_el_pasado")

        # Criterios 1 y 2: queda registrado quien cancelo. Las dos partes ya
        # tienen su fila en usuario_ref, asi que la FK se cumple.
        reserva.estado = EstadoReserva.CANCELADA
        reserva.cerrada_en = ahora
        reserva.cancelada_por_usuario_id = usuario_id
        reserva.save(update_fields=["estado", "cerrada_en", "cancelada_por_usuario"])
        if estado == EstadoReserva.CONFIRMADA:
            # Criterio 2: el horario vuelve a estar disponible. Una solicitud
            # nunca ocupo el bloque: ahi no cambia (criterio 1).
            bloque.estado = EstadoBloque.LIBRE
            bloque.save(update_fields=["estado", "actualizado_en"])

        # 3. El aviso a la otra parte sale cuando todo quedo guardado, y asi
        # otra_persona, que calcula pedir_aviso, es quien cancelo. Si la
        # transaccion se deshace, no sale.
        destinatario = reserva.solicitante_usuario_id if es_tutor else bloque.usuario_id
        transaction.on_commit(
            partial(pedir_aviso, destinatario, RESERVA_CANCELADA, reserva)
        )

    # 4. Con el formato de HU-21, leida de nuevo despues de la transaccion.
    reserva = reservas_con_todo().get(pk=reserva_id)
    return Response(reserva_json(reserva, TUTOR if es_tutor else ESTUDIANTE))
