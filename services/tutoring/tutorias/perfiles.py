"""Asignaturas que el usuario declara que puede ensenar (HU-14, RF-03).

GET y POST /perfiles, y PATCH /perfiles/<id>, todo con sesion: el usuario sale
del token (HU-17). Cada fila de perfil_tutor es una asignatura que el usuario
ensena, con su tarifa.

- RN-01: solo se declara una asignatura de la malla vigente de su carrera que
  este en un semestre anterior al que cursa. La carrera y el nivel los da
  Identidad (GET /yo) y la malla, Catalogo (llamadas.py). Lo valida el
  servidor; la pagina solo ofrece las opciones que pasan.
- RN-05: la tarifa es un entero de pesos desde 0, y 0 es una tutoria gratuita.
  Cambiarla no toca el monto de las reservas ya creadas: reserva.monto es una
  copia congelada (A-04).
- T-166: declarar es un contacto con Tutorias: crea o pone al dia usuario_ref,
  y asignatura_ref con lo que trajo Catalogo (copias.py).
- Las consultas a otros servicios se hacen antes de abrir la transaccion, para
  no dejarla abierta mientras se espera la respuesta.
"""

import uuid

from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .bloques import Rechazo, instante_json
from .copias import asegurar_usuario_ref, copiar_asignatura
from .llamadas import malla_cursada
from .models import PerfilTutor

RESTRICCION_UNICA = "ux_perfil_usuario_asignatura"
# perfil_tutor.tarifa es numeric(8, 0).
TARIFA_MAXIMA = 99_999_999
LARGO_DESCRIPCION = 500

ASIGNATURA_INVALIDA = "Elige la asignatura que quieres enseñar."
TARIFA_INVALIDA = (
    "La tarifa tiene que ser un número entero de pesos, desde 0 (gratuita) "
    "hasta 99.999.999."
)
YA_DECLARADA = "Ya declaraste esa asignatura: puedes cambiar su tarifa en tu lista."
PERFIL_INCOMPLETO = (
    "Completa tu carrera y tu nivel en Mi perfil antes de declarar asignaturas."
)
CARRERA_NO_VALIDA = "Tu carrera no está en el catálogo. Revisa tu perfil."


def perfil_json(perfil):
    asignatura = perfil.asignatura
    return {
        "id": str(perfil.id),
        "asignatura": {
            "asignatura_id": str(asignatura.asignatura_id),
            "sigla": asignatura.sigla,
            "nombre": asignatura.nombre,
        },
        "tarifa": int(perfil.tarifa),
        "descripcion": perfil.descripcion,
        "activo": perfil.activo,
        "creado_en": instante_json(perfil.creado_en),
    }


# ------------------------------------------------------------ el cuerpo


def cuerpo(request):
    return request.data if isinstance(request.data, dict) else {}


def leer_asignatura_id(datos):
    valor = datos.get("asignatura_id")
    try:
        return uuid.UUID(valor) if isinstance(valor, str) else None
    except ValueError:
        return None


def leer_tarifa(datos):
    valor = datos.get("tarifa")
    # bool es subclase de int: un true no es una tarifa. Tampoco 1.5 ni "5000".
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise Rechazo(TARIFA_INVALIDA, "tarifa_invalida")
    if not 0 <= valor <= TARIFA_MAXIMA:
        raise Rechazo(TARIFA_INVALIDA, "tarifa_invalida")
    return valor


def leer_descripcion(datos):
    """Texto de hasta 500 caracteres, sin espacios a los lados, o None."""
    valor = datos.get("descripcion")
    if valor is None:
        return None
    # PostgreSQL no guarda el caracter nulo, y una mitad de par sustituto no se
    # puede codificar: los dos terminarian en un error 500 al guardar.
    if not isinstance(valor, str) or any(
        c == "\x00" or "\ud800" <= c <= "\udfff" for c in valor
    ):
        raise Rechazo("La descripción tiene que ser un texto.", "descripcion_invalida")
    valor = valor.strip()
    if len(valor) > LARGO_DESCRIPCION:
        raise Rechazo(
            f"La descripción puede tener hasta {LARGO_DESCRIPCION} caracteres.",
            "descripcion_invalida",
        )
    return valor or None


def leer_activo(datos):
    valor = datos.get("activo")
    if not isinstance(valor, bool):
        raise Rechazo("Indica activo como true o false.", "activo_invalido")
    return valor


# ------------------------------------------------------------ RN-01


def asignatura_habilitada(request, asignatura_id):
    """(usuario_ref, asignatura de Catalogo) si RN-01 la habilita.

    Una llamada a Identidad y otra a Catalogo, sin transaccion abierta.
    """
    usuario, nivel = asegurar_usuario_ref(request)
    if usuario.carrera_id is None or not nivel:
        raise Rechazo(PERFIL_INCOMPLETO, "perfil_incompleto")
    habilitadas = malla_cursada(usuario.carrera_id, nivel - 1)
    if habilitadas is None:
        raise Rechazo(CARRERA_NO_VALIDA, "carrera_no_valida")
    asignatura = habilitadas.get(asignatura_id)
    if asignatura is None:
        raise Rechazo(
            "Solo puedes declarar asignaturas de la malla de tu carrera que estén "
            f"en semestres anteriores al que cursas ({nivel}).",
            "asignatura_no_habilitada",
        )
    return usuario, asignatura


# ------------------------------------------------------------ las rutas


def guardar_nuevo(perfil):
    """Crea el perfil. Si dos envios llegan a la vez, la base rechaza el segundo."""
    try:
        with transaction.atomic():
            perfil.save(force_insert=True)
    except IntegrityError as error:
        diagnostico = getattr(error.__cause__, "diag", None)
        if getattr(diagnostico, "constraint_name", None) != RESTRICCION_UNICA:
            raise
        raise Rechazo(
            YA_DECLARADA, "asignatura_ya_declarada", status.HTTP_409_CONFLICT
        ) from error


def listar(request):
    """Los perfiles de ?usuario=, por sigla.

    Los propios, activos y desactivados; los de otro usuario, solo los activos
    y si su cuenta esta activa (RN-08). No llama a otros servicios.
    """
    try:
        usuario_id = uuid.UUID(request.query_params.get("usuario", ""))
    except ValueError:
        raise Rechazo(
            "Indica de quién son las asignaturas: ?usuario=<id del usuario>.",
            "usuario_requerido",
        ) from None
    perfiles = PerfilTutor.objects.filter(usuario_id=usuario_id)
    if usuario_id != request.user.usuario_id:
        perfiles = perfiles.filter(activo=True, usuario__activo=True)
    perfiles = perfiles.select_related("asignatura").order_by("asignatura__sigla", "id")
    return Response([perfil_json(perfil) for perfil in perfiles])


def declarar(request):
    """Criterios 1 a 4 y 6. Responde 201 si lo crea y 200 si lo reactiva."""
    datos = cuerpo(request)
    asignatura_id = leer_asignatura_id(datos)
    if asignatura_id is None:
        raise Rechazo(ASIGNATURA_INVALIDA, "asignatura_invalida")
    tarifa = leer_tarifa(datos)
    descripcion = leer_descripcion(datos)
    usuario, asignatura = asignatura_habilitada(request, asignatura_id)

    with transaction.atomic():
        copia = copiar_asignatura(asignatura_id, asignatura)
        perfil = (
            PerfilTutor.objects.select_for_update()
            .filter(usuario=usuario, asignatura=copia)
            .first()
        )
        if perfil is None:
            perfil = PerfilTutor(
                usuario=usuario,
                asignatura=copia,
                tarifa=tarifa,
                descripcion=descripcion,
            )
            guardar_nuevo(perfil)
            return Response(perfil_json(perfil), status=status.HTTP_201_CREATED)
        if perfil.activo:
            raise Rechazo(
                YA_DECLARADA, "asignatura_ya_declarada", status.HTTP_409_CONFLICT
            )
        perfil.tarifa, perfil.descripcion, perfil.activo = tarifa, descripcion, True
        perfil.save(update_fields=["tarifa", "descripcion", "activo", "actualizado_en"])
    return Response(perfil_json(perfil))


def perfil_propio(request, perfil_id, bloquear=False):
    """El perfil del usuario del token. Uno de otro o que no existe: el mismo 404."""
    perfiles = PerfilTutor.objects.select_related("asignatura")
    if bloquear:
        perfiles = perfiles.select_for_update(of=("self",))
    perfil = perfiles.filter(id=perfil_id, usuario_id=request.user.usuario_id).first()
    if perfil is None:
        raise NotFound("No tienes una asignatura declarada con ese identificador.")
    return perfil


def editar(request, perfil_id):
    """Cambia la tarifa, la descripcion o si esta activo (criterio 5).

    Desactivar y cambiar la tarifa no llaman a nadie. Pedir activo = true
    vuelve a validar RN-01, porque la carrera o el nivel pudieron cambiar. Se
    valida aunque ya este activo: decidirlo con una lectura sin bloqueo dejaria
    pasar una desactivacion que llegue entre medio.
    """
    perfil = perfil_propio(request, perfil_id)
    datos = cuerpo(request)
    cambios = {}
    if "tarifa" in datos:
        cambios["tarifa"] = leer_tarifa(datos)
    if "descripcion" in datos:
        cambios["descripcion"] = leer_descripcion(datos)
    if "activo" in datos:
        cambios["activo"] = leer_activo(datos)
    if not cambios:
        return Response(perfil_json(perfil))
    asignatura = None
    if cambios.get("activo"):
        _, asignatura = asignatura_habilitada(request, perfil.asignatura_id)

    with transaction.atomic():
        # Primero asignatura_ref y despues el perfil, el mismo orden de
        # bloqueos de declarar: dos peticiones a la vez no se bloquean entre si.
        copia = None
        if asignatura is not None:
            copia = copiar_asignatura(perfil.asignatura_id, asignatura)
        perfil = perfil_propio(request, perfil_id, bloquear=True)
        if copia is not None:
            perfil.asignatura = copia
        for campo, valor in cambios.items():
            setattr(perfil, campo, valor)
        perfil.save(update_fields=[*cambios, "actualizado_en"])
    return Response(perfil_json(perfil))


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def declarar_o_listar(request):
    """GET /perfiles?usuario=<id> y POST /perfiles."""
    if request.method == "POST":
        return declarar(request)
    return listar(request)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def un_perfil(request, perfil_id):
    """PATCH /perfiles/<id>."""
    return editar(request, perfil_id)
