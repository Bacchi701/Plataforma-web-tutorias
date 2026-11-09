"""Administracion de usuarios (HU-31, SCRUM-45; Pilar 2, seccion 4.1).

GET /admin/usuarios lista las cuentas, con busqueda por nombre y por paginas,
y PATCH /admin/usuarios/<id> activa o desactiva una. Las usa el panel de
administracion (HU-33), que no tiene pantallas en esta historia.

- Responden solo a un token con la marca es_admin (AD-09): sin un token
  valido, 401, como /yo; con un token sin la marca, 403 no_es_administrador.
- Desactivar revoca en la misma transaccion las renovaciones abiertas de la
  cuenta (criterio 2, CA7): no puede renovar la sesion ni volver a iniciarla.
  Su token de acceso deja de servir de inmediato en Identidad, porque
  TokenDeAcceso busca la cuenta activa en cada peticion, pero sirve hasta que
  vence en Tutorias y Pagos, que solo verifican la firma (Pilar 2, seccion
  5.3). La busqueda de tutores la deja fuera tras la siguiente sincronizacion
  de las copias de Tutorias (HU-19).
- Cada cuenta trae su correo: es lo que distingue dos cuentas con el mismo
  nombre. Lo ve solo un administrador y no sale de Identidad (RNF-07).
- Desactivar no envia correo: CUENTA_DESACTIVADA es de RF-14, que no se
  promovio (anexo A, seccion 8).

No se llama admin.py: en Django ese nombre es del panel de Django, que este
proyecto no usa.
"""

from datetime import UTC

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from .autenticacion import TokenDeAcceso
from .models import RefreshToken, Usuario
from .vistas import Rechazo

LARGO_MAXIMO_BUSQUEDA = 80
LIMITE_POR_DEFECTO = 50
LIMITE_MAXIMO = 100

BUSQUEDA_INVALIDA = (
    f"Escribe hasta {LARGO_MAXIMO_BUSQUEDA} caracteres para buscar a un usuario."
)
FILTRO_INVALIDO = "El filtro activo tiene que ser true o false."
PAGINA_INVALIDA = "La página tiene que ser un número entero desde 1."
LIMITE_INVALIDO = f"El límite tiene que ser un número entero de 1 a {LIMITE_MAXIMO}."
CUERPO_INVALIDO = "Envía solo el campo activo, con true o false."
# El mismo mensaje de la ruta interna un_usuario (internas.py).
NO_EXISTE = "El usuario no existe."
CUENTA_PROPIA = "No puedes desactivar tu propia cuenta."


class EsAdministrador(BasePermission):
    """Solo un token con la marca es_admin en true (AD-09).

    Va despues de IsAuthenticated. DRF responde 403 con este mensaje y este
    codigo, en el formato unico: los mismos del permiso de las rutas /admin
    de Tutorias (HU-33), para que el panel maneje un solo codigo. Se escribe
    aqui y no se importa de Tutorias: cada servicio es autocontenido.
    """

    message = "Esta sección es solo para administradores."
    code = "no_es_administrador"

    def has_permission(self, request, view):
        # La marca es la del token, como en Tutorias, y solo un true de JSON
        # cuenta. usuario.es_admin se copia al token al emitirlo: un cambio de
        # la marca rige con el siguiente token de acceso (Pilar 2, 5.3).
        reclamaciones = request.auth or {}
        return reclamaciones.get("es_admin") is True


def instante_json(valor):
    """ISO 8601 en UTC y con Z, sin fraccion de segundo: 2026-09-12T16:40:00Z."""
    return valor.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def usuario_json(usuario):
    """Una cuenta como la ve el panel. Nunca el hash de la clave."""
    return {
        "id": str(usuario.id),
        "email": usuario.email,
        "nombre": usuario.nombre,
        "apellido": usuario.apellido,
        "carrera_id": str(usuario.carrera_id) if usuario.carrera_id else None,
        "sede_id": str(usuario.sede_id) if usuario.sede_id else None,
        "nivel": usuario.nivel,
        "email_verificado": usuario.email_verificado,
        "activo": usuario.activo,
        "es_admin": usuario.es_admin,
        "creado_en": instante_json(usuario.creado_en),
    }


# ------------------------------------------------- GET /admin/usuarios


def palabras_pedidas(request):
    """Las palabras de ?buscar=, sin los espacios de sobra.

    El caracter nulo se rechaza: PostgreSQL no lo acepta en un texto y la
    consulta terminaria en un error 500.
    """
    texto = request.query_params.get("buscar", "")
    palabras = texto.split()
    if "\x00" in texto or len(" ".join(palabras)) > LARGO_MAXIMO_BUSQUEDA:
        raise Rechazo(BUSQUEDA_INVALIDA, "busqueda_invalida")
    return palabras


def activo_pedido(request):
    """True o False si viene ?activo=, o None para traer todas las cuentas.

    Solo true o false, en minusculas. Vacio (?activo=) tambien es un valor
    invalido: para no filtrar, el parametro no se manda.
    """
    if "activo" not in request.query_params:
        return None
    texto = request.query_params["activo"]
    if texto not in ("true", "false"):
        raise Rechazo(FILTRO_INVALIDO, "activo_invalido")
    return texto == "true"


def entero_o_none(texto):
    """El numero de un parametro escrito solo con cifras, o None.

    int() aceptaria tambien "+5", " 5" o "1_0", y con mas de 4300 cifras lanza
    ValueError.
    """
    if not (texto.isascii() and texto.isdigit()):
        return None
    try:
        return int(texto)
    except ValueError:
        return None


def pagina_pedida(request):
    """La pagina de ?pagina=, desde 1. Sin el parametro, la primera."""
    texto = request.query_params.get("pagina")
    if texto is None:
        return 1
    pagina = entero_o_none(texto)
    if pagina is None or pagina < 1:
        raise Rechazo(PAGINA_INVALIDA, "pagina_invalida")
    return pagina


def limite_pedido(request):
    """Las cuentas por pagina de ?limite=, de 1 a 100. Sin el parametro, 50."""
    texto = request.query_params.get("limite")
    if texto is None:
        return LIMITE_POR_DEFECTO
    limite = entero_o_none(texto)
    if limite is None or not 1 <= limite <= LIMITE_MAXIMO:
        raise Rechazo(LIMITE_INVALIDO, "limite_invalido")
    return limite


@api_view(["GET"])
@authentication_classes([TokenDeAcceso])
@permission_classes([IsAuthenticated, EsAdministrador])
def listar_usuarios(request):
    """Las cuentas, de la mas nueva a la mas antigua (criterio 1).

    - ?buscar= deja las cuentas en que cada palabra aparece en el nombre o en
      el apellido, sin distinguir mayusculas (icontains). Las tildes cuentan:
      «matias» no encuentra a «Matías», porque identity_db no tiene la
      extension unaccent. Con 500 usuarios basta recorrer la tabla (anexo A,
      seccion 4.2).
    - ?activo= deja solo las activas o solo las desactivadas.
    - La respuesta usa los nombres de la busqueda paginada de Catalogo.

    Dos consultas ademas de la del token: una cuenta y la otra trae la pagina.
    Una pagina mas alla de la ultima responde vacia sin la segunda: asi un
    numero de pagina enorme no llega a PostgreSQL.
    """
    palabras = palabras_pedidas(request)
    activo = activo_pedido(request)
    pagina = pagina_pedida(request)
    limite = limite_pedido(request)

    cuentas = Usuario.objects.all()
    for palabra in palabras:
        cuentas = cuentas.filter(
            Q(nombre__icontains=palabra) | Q(apellido__icontains=palabra)
        )
    if activo is not None:
        cuentas = cuentas.filter(activo=activo)

    total = cuentas.count()
    inicio = (pagina - 1) * limite
    fin = inicio + limite
    de_esta_pagina = []
    if inicio < total:
        de_esta_pagina = cuentas.order_by("-creado_en", "id")[inicio:fin]

    return Response(
        {
            "total": total,
            "pagina": pagina,
            "total_paginas": max(1, (total + limite - 1) // limite),
            "limite": limite,
            "resultados": [usuario_json(cuenta) for cuenta in de_esta_pagina],
        }
    )


# ------------------------------------------ PATCH /admin/usuarios/<id>


def activo_del_cuerpo(request):
    """El true o false de {"activo": ...}, el unico cuerpo que se acepta.

    Un texto ("false"), un numero (0), null, un campo de mas (es_admin,
    email...) o un cuerpo que no es un objeto se rechazan: desde el panel no
    se cambia nada mas de una cuenta.
    """
    datos = request.data
    if (
        not isinstance(datos, dict)
        or set(datos) != {"activo"}
        or not isinstance(datos["activo"], bool)
    ):
        raise Rechazo(CUERPO_INVALIDO, "activo_invalido")
    return datos["activo"]


@api_view(["PATCH"])
@authentication_classes([TokenDeAcceso])
@permission_classes([IsAuthenticated, EsAdministrador])
def cambiar_estado(request, usuario_id):
    """Activa o desactiva una cuenta (criterio 2; Pilar 2, seccion 4.1).

    Primero el cuerpo y despues, en una transaccion con la cuenta bloqueada:
    que exista (404) y que el administrador no se desactive a si mismo (409).

    - Con false, la cuenta queda desactivada y todas sus renovaciones sin
      revocar quedan revocadas con un solo UPDATE (CA7). Las que ya estaban
      revocadas conservan su fecha.
    - Con true, vuelve a estar activa. No se crea ninguna sesion: la persona
      vuelve a iniciar sesion.
    - Si ya estaba en ese estado, no cambia nada y responde igual.

    Un /refresh que se cruce con la desactivacion no deja una sesion viva:
    refresh (vistas.py) responde 401 sesion_invalida con la cuenta inactiva,
    y login, 403 cuenta_desactivada.
    """
    activo = activo_del_cuerpo(request)
    revocadas = 0
    with transaction.atomic():
        usuario = Usuario.objects.select_for_update().filter(id=usuario_id).first()
        if usuario is None:
            raise Rechazo(NO_EXISTE, "usuario_no_encontrado", 404)
        # Asi el panel no se queda sin administrador por un clic.
        if not activo and usuario.id == request.user.id:
            raise Rechazo(CUENTA_PROPIA, "cuenta_propia", 409)
        if usuario.activo != activo:
            usuario.activo = activo
            usuario.save(update_fields=["activo", "actualizado_en"])
            if not activo:
                revocadas = RefreshToken.objects.filter(
                    usuario=usuario, revocado_en__isnull=True
                ).update(revocado_en=timezone.now())
    return Response({**usuario_json(usuario), "sesiones_revocadas": revocadas})
