"""Consultas de Tutorias a otros servicios (HU-14, HU-41, HU-19 y HU-28).

Tutorias guarda copias de lectura del usuario y de la asignatura (usuario_ref
y asignatura_ref, AD-07). Para crearlas o ponerlas al dia, y para validar
RN-01, pregunta a las rutas publicas de los otros servicios:

- Identidad, GET /api/identity/v1/yo, con la misma cabecera Authorization que
  trajo la peticion. Asi Tutorias solo lee los datos de quien hace la
  peticion, y no necesita una clave de servicio.
- Catalogo, GET /api/catalog/v1/carreras/<id>/asignaturas: la malla vigente
  de la carrera, por semestre. Es publica.
- Catalogo, GET /api/catalog/v1/asignaturas?paginado=1: todas las asignaturas
  activas, pagina por pagina (asignaturas_del_catalogo). Es publica: la usa
  la sincronizacion de las copias (HU-19) sin las rutas internas de Catalogo.

Las rutas /internal con clave de servicio (Pilar 2, seccion 5.4) se llaman
con _pedir() y la clave de servicio:
- en Identidad, para lo que necesite datos de otro usuario: los de uno
  (usuario_por_id) o los de varios en una sola llamada (usuarios_por_ids,
  GET /internal/usuarios?ids=, para la sincronizacion de las copias, HU-19),
  y para los avisos por correo (pedir_aviso, HU-16);
- en Pagos, para el reembolso de una tutoria cancelada (pedir_reembolso,
  HU-28): la cuarta llamada interna del Pilar 2 (anexo A, seccion 9).

De esa convencion se toma lo demas: urllib de la biblioteca estandar, 3
segundos de espera y un solo intento. Si el otro servicio no responde, se
demora o responde 5xx, la peticion termina en un 503 servicio_no_disponible
que dice que servicio fallo. urllib solo envuelve en URLError lo que falla al
conectar: si el servicio acepta la conexion y no contesta a tiempo sale un
TimeoutError suelto; si corta la respuesta, un ConnectionError o un
http.client.HTTPException, y si el cuerpo no es JSON, un ValueError. Todos
terminan en el mismo 503. Salvo pedir_aviso y pedir_reembolso: corren despues
de guardar y nunca lanzan una excepcion, y lo que no sale queda en el log.
"""

import http.client
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
import uuid

from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import APIException, AuthenticationFailed

from .autenticacion import VENCIDO
from .bloques import Rechazo, instante_json

logger = logging.getLogger(__name__)

IDENTIDAD = "Identidad"
CATALOGO = "Catálogo"
PAGOS = "Pagos"
# Segundos. urllib los aplica a cada operacion del socket, no a la llamada entera.
ESPERA_MAXIMA = 3

# Sin proxy: son llamadas dentro de la red de Docker. Si el computador tiene un
# proxy configurado, Docker puede pasarlo a los contenedores en HTTP_PROXY, y
# urlopen lo usaria tambien para identity:8000.
_ABRIDOR = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ServicioNoDisponible(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = "servicio_no_disponible"


class CuentaInactiva(Rechazo):
    """Identidad no reconoce la cuenta del token: no existe o esta desactivada."""

    def __init__(self):
        super().__init__(
            "La cuenta no existe o está desactivada.",
            "cuenta_inactiva",
            status.HTTP_403_FORBIDDEN,
        )


def no_disponible(servicio):
    return ServicioNoDisponible(
        f"No pudimos comunicarnos con el servicio de {servicio}. "
        "Intenta de nuevo en unos minutos."
    )


def abrir(peticion):
    """La unica salida a la red de este modulo (las pruebas la reemplazan)."""
    return _ABRIDOR.open(peticion, timeout=ESPERA_MAXIMA)


def _cuerpo_del_error(error):
    """El JSON de un 4xx, o None si no trae JSON (la pagina 404 de Django)."""
    try:
        return json.loads(error.read())
    except (ValueError, OSError, http.client.HTTPException):
        return None
    finally:
        error.close()


def _pedir(servicio, url, cabeceras=None, *, metodo="GET", cuerpo=None):
    """Llamada HTTP a otro servicio. Devuelve (estado, cuerpo) si responde 2xx o 4xx.

    Si no responde, se demora o responde 5xx, lanza ServicioNoDisponible.
    """
    encabezados = {"Accept": "application/json", **(cabeceras or {})}
    datos = None
    if cuerpo is not None:
        datos = json.dumps(cuerpo).encode("utf-8")
        encabezados["Content-Type"] = "application/json"

    ruta = urllib.parse.urlsplit(url).path
    if "/v1/internal/" in ruta:
        encabezados["X-Clave-Servicio"] = getattr(settings, "CLAVE_SERVICIO", "")

    peticion = urllib.request.Request(
        url, data=datos, headers=encabezados, method=metodo
    )
    try:
        with abrir(peticion) as respuesta:
            contenido = respuesta.read()
            if not contenido:
                return respuesta.status, None
            return respuesta.status, json.loads(contenido)
    except urllib.error.HTTPError as error:
        if error.code >= 500:
            error.close()
            logger.warning("%s respondió %s a %s %s", servicio, error.code, metodo, url)
            raise no_disponible(servicio) from error
        return error.code, _cuerpo_del_error(error)
    except (OSError, http.client.HTTPException, ValueError) as error:
        # OSError cubre URLError (no se pudo conectar), TimeoutError (no
        # contesto a tiempo) y ConnectionError (corto la conexion).
        logger.warning(
            "No se pudo consultar a %s (%s %s): %r", servicio, metodo, url, error
        )
        raise no_disponible(servicio) from error


def _codigo(cuerpo):
    return cuerpo.get("codigo") if isinstance(cuerpo, dict) else None


def _uuid_o_nada(valor):
    return uuid.UUID(valor) if valor else None


def _datos_de_yo(cuerpo):
    """Lo que Tutorias usa de GET /yo, o None si la respuesta no tiene esa forma."""
    if not isinstance(cuerpo, dict):
        return None
    nombre, apellido, nivel = (cuerpo.get(c) for c in ("nombre", "apellido", "nivel"))
    if not isinstance(nombre, str) or not isinstance(apellido, str):
        return None
    try:
        identificadores = {
            "id": uuid.UUID(cuerpo["id"]),
            "carrera_id": _uuid_o_nada(cuerpo.get("carrera_id")),
            "sede_id": _uuid_o_nada(cuerpo.get("sede_id")),
        }
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    # bool es subclase de int: un true no es un nivel.
    if isinstance(nivel, bool) or not isinstance(nivel, int):
        nivel = None
    return {**identificadores, "nombre": nombre, "apellido": apellido, "nivel": nivel}


def _datos_internos(cuerpo):
    """Un usuario de las rutas /internal: lo de GET /yo mas activo, o None."""
    datos = _datos_de_yo(cuerpo)
    activo = cuerpo.get("activo") if isinstance(cuerpo, dict) else None
    if datos is None or not isinstance(activo, bool):
        return None
    return {**datos, "activo": activo}


def datos_del_usuario(autorizacion):
    """GET /yo de Identidad con la cabecera Authorization de la peticion.

    Devuelve un diccionario con id, nombre, apellido, carrera_id, sede_id
    (uuid.UUID o None) y nivel (entero o None).
    - Si Identidad no reconoce la cuenta (cuenta_inactiva): CuentaInactiva, 403.
    - Si el token vencio justo entre medio: 401 token_vencido, para que la
      pagina renueve la sesion y reintente.
    - Cualquier otra respuesta queda en el log y termina en un 503.
    """
    url = f"{settings.URL_IDENTIDAD}/api/identity/v1/yo"
    estado, cuerpo = _pedir(IDENTIDAD, url, {"Authorization": autorizacion})
    codigo = _codigo(cuerpo)
    if estado == 200:
        datos = _datos_de_yo(cuerpo)
        if datos is not None:
            return datos
    elif estado == 401 and codigo == "cuenta_inactiva":
        raise CuentaInactiva()
    elif estado == 401 and codigo == "token_vencido":
        raise AuthenticationFailed(VENCIDO, code="token_vencido")
    logger.error("Identidad respondió %s (codigo %s) a GET /yo", estado, codigo)
    raise no_disponible(IDENTIDAD)


def _cuerpo_del_aviso(destinatario, plantilla, reserva):
    """El cuerpo JSON de POST /internal/avisos (ver pedir_aviso)."""
    bloque = reserva.bloque
    # La otra parte de la reserva. El tutor es el dueno del bloque (3FN).
    if destinatario == bloque.usuario_id:
        otra_persona = reserva.solicitante_usuario
    else:
        otra_persona = bloque.usuario
    return {
        "usuario_id": str(destinatario),
        "plantilla": plantilla,
        "referencia_id": str(reserva.id),
        "datos": {
            "asignatura": {
                "sigla": reserva.asignatura.sigla,
                "nombre": reserva.asignatura.nombre,
            },
            "inicio_en": instante_json(bloque.inicio_en),
            "fin_en": instante_json(bloque.fin_en),
            "otra_persona": {
                "nombre": otra_persona.nombre,
                "apellido": otra_persona.apellido,
            },
            "nota": reserva.nota,
            "modalidad": reserva.modalidad,
            "lugar_o_enlace": reserva.lugar_o_enlace,
        },
    }


def pedir_aviso(usuario_id, plantilla, reserva):
    """Pide a Identidad el aviso por correo de una reserva (HU-16).

    Contrato provisional para HU-16, que construye la ruta en Identidad:
    POST /api/identity/v1/internal/avisos, con la clave de servicio (la pone
    _pedir, por ser una ruta /internal) y sin Authorization. El cuerpo:

        {"usuario_id": "<destinatario>",
         "plantilla": "SOLICITUD_RECIBIDA",
         "referencia_id": "<id de la reserva>",
         "datos": {"asignatura": {"sigla": "BDD1101", "nombre": "Base de Datos"},
                   "inicio_en": "2026-11-11T21:00:00Z",
                   "fin_en": "2026-11-11T22:00:00Z",
                   "otra_persona": {"nombre": "Camila", "apellido": "Rojas"},
                   "nota": "...", "modalidad": null, "lugar_o_enlace": null}}

    - usuario_id y referencia_id van como texto: _pedir escribe el cuerpo con
      json.dumps, que no sabe escribir un uuid.UUID.
    - plantilla es una del anexo A: SOLICITUD_RECIBIDA, RESERVA_CONFIRMADA,
      RESERVA_RECHAZADA o RESERVA_CANCELADA.
    - otra_persona es la otra parte de la reserva: el solicitante si el
      destinatario es el tutor (el dueno del bloque), y el tutor si es el
      solicitante.
    - referencia_id permite que Identidad no mande dos veces el mismo aviso
      (ux_aviso_idempotente).
    - Las fechas van en UTC con Z; la hora de Chile la pone el correo.

    Nunca lanza una excepcion: un aviso que no sale no puede deshacer la
    operacion que lo pidio. Si Identidad no responde o no responde un 2xx,
    deja una linea en el log y devuelve False. Devuelve True si Identidad
    acepto el aviso.
    """
    referencia = getattr(reserva, "id", None)
    try:
        destinatario = uuid.UUID(str(usuario_id))
        url = f"{settings.URL_IDENTIDAD}/api/identity/v1/internal/avisos"
        cuerpo = _cuerpo_del_aviso(destinatario, plantilla, reserva)
        estado, respuesta = _pedir(IDENTIDAD, url, metodo="POST", cuerpo=cuerpo)
    except Exception as error:
        logger.warning(
            "No salió el aviso %s de la reserva %s: %r", plantilla, referencia, error
        )
        return False
    if not 200 <= estado < 300:
        logger.warning(
            "No salió el aviso %s de la reserva %s: Identidad respondió %s "
            "(codigo %s)",
            plantilla,
            referencia,
            estado,
            _codigo(respuesta),
        )
        return False
    return True


def pedir_reembolso(reserva_id):
    """Pide a Pagos el reembolso del pago de una tutoria cancelada (HU-28, CA9).

    POST /api/payments/v1/internal/pagos/reembolso, con la clave de servicio
    (la pone _pedir, por ser una ruta /internal) y sin Authorization. El
    cuerpo es {"reserva_id": "<id de la reserva>"}, con el id como texto.
    Pagos es la unica fuente del estado del pago (T-174) y decide si hay algo
    que reembolsar (pagos/internas.py):

    - 2xx: Pagos reembolso el pago, o ya estaba reembolsado.
    - 404 pago_no_encontrado (la reserva no tiene pago) o 409
      pago_no_reembolsable (el pago no esta PAGADO): no hay nada que
      reembolsar. Deja una linea informativa en el log, con la reserva y el
      codigo. Con el nivel INFO no sale en docker compose logs: Tutorias no
      configura el registro, y lo que se ve parte en WARNING.
    - Cualquier otra respuesta, como un 404 sin codigo conocido (falta la ruta
      o la clave no calza), un 5xx o un error de red: el reembolso quedo
      pendiente. Deja una linea de error en el log, con la reserva y lo que
      paso.

    Devuelve True cuando no queda nada pendiente (un 2xx, o el 404 o el 409 de
    arriba) y False cuando el reembolso quedo pendiente. Nunca lanza una
    excepcion: un reembolso que no sale no puede deshacer una cancelacion ya
    guardada.

    Se llama despues del commit de la cancelacion (transaction.on_commit),
    nunca dentro de la transaccion ni con un bloqueo tomado: Pagos llama de
    vuelta a Tutorias dentro de la misma peticion, con el aviso PATCH
    /internal/reservas/<id>/estado-pago (internas.py), que bloquea la reserva
    con select_for_update. Con la reserva bloqueada, ese aviso esperaria hasta
    el tiempo maximo de 3 segundos.
    """
    try:
        url = f"{settings.URL_PAGOS}/api/payments/v1/internal/pagos/reembolso"
        cuerpo = {"reserva_id": str(reserva_id)}
        estado, respuesta = _pedir(PAGOS, url, metodo="POST", cuerpo=cuerpo)
    except Exception as error:
        # _pedir envuelve en ServicioNoDisponible un 5xx o un error de red: lo
        # que paso es la causa.
        causa = error if error.__cause__ is None else error.__cause__
        logger.error(
            "El reembolso de la reserva %s quedó pendiente: falló la llamada a "
            "%s (%r)",
            reserva_id,
            PAGOS,
            causa,
        )
        return False
    codigo = _codigo(respuesta)
    if 200 <= estado < 300:
        return True
    if (estado, codigo) in (
        (404, "pago_no_encontrado"),
        (409, "pago_no_reembolsable"),
    ):
        logger.info(
            "Nada que reembolsar en la reserva %s: %s respondió %s (codigo %s)",
            reserva_id,
            PAGOS,
            estado,
            codigo,
        )
        return True
    if estado == 404:
        logger.error(
            "El reembolso de la reserva %s quedó pendiente: 404 sin código "
            "conocido desde %s: revisa CLAVE_SERVICIO",
            reserva_id,
            PAGOS,
        )
        return False
    logger.error(
        "El reembolso de la reserva %s quedó pendiente: %s respondió %s (codigo %s)",
        reserva_id,
        PAGOS,
        estado,
        codigo,
    )
    return False


def usuario_por_id(usuario_id):
    """GET a la ruta interna de Identidad para obtener los datos de un usuario.

    Devuelve un diccionario con id, nombre, apellido, carrera_id, sede_id
    (uuid.UUID o None), nivel (entero o None) y activo (booleano).
    - 200: devuelve el diccionario completo.
    - 404 usuario_no_encontrado: devuelve None.
    - 404 sin codigo conocido (o HTML): lanza ServicioNoDisponible y registra
      el error en el log pidiendo revisar CLAVE_SERVICIO.
    - Cualquier otra respuesta: registra el error en el log y lanza 503.
    """
    url = f"{settings.URL_IDENTIDAD}/api/identity/v1/internal/usuarios/{usuario_id}"
    estado, cuerpo = _pedir(IDENTIDAD, url)
    codigo = _codigo(cuerpo)

    if estado == 200:
        datos = _datos_internos(cuerpo)
        if datos is not None:
            return datos
    elif estado == 404:
        if codigo == "usuario_no_encontrado":
            return None
        logger.error(
            "404 sin código conocido desde %s: revisa CLAVE_SERVICIO", IDENTIDAD
        )
        raise no_disponible(IDENTIDAD)

    logger.error("Identidad respondió %s (codigo %s) a GET %s", estado, codigo, url)
    raise no_disponible(IDENTIDAD)


def usuarios_por_ids(ids):
    """GET /internal/usuarios?ids= de Identidad: varios usuarios en una llamada.

    Es la consulta de la sincronizacion de las copias (HU-19). Devuelve
    {uuid.UUID: datos}, con datos de la misma forma que usuario_por_id. Los
    usuarios que Identidad no tiene no vienen, y sin ids no llama.
    - 404, con JSON o sin el: esta ruta no tiene un 404 de «no existe», asi
      que falta la ruta o la clave no calza. Lanza ServicioNoDisponible y el
      log pide revisar CLAVE_SERVICIO.
    - Cualquier otra respuesta, o una lista con otra forma: al log y 503.
    """
    ids = [str(usuario_id) for usuario_id in ids]
    if not ids:
        return {}
    url = (
        f"{settings.URL_IDENTIDAD}/api/identity/v1/internal/usuarios"
        f"?ids={','.join(ids)}"
    )
    estado, cuerpo = _pedir(IDENTIDAD, url)

    if estado == 200 and isinstance(cuerpo, list):
        usuarios = [_datos_internos(elemento) for elemento in cuerpo]
        if None not in usuarios:
            return {datos["id"]: datos for datos in usuarios}
    elif estado == 404:
        logger.error(
            "404 desde %s a GET /internal/usuarios: revisa CLAVE_SERVICIO", IDENTIDAD
        )
        raise no_disponible(IDENTIDAD)

    logger.error(
        "Identidad respondió %s (codigo %s) a GET /internal/usuarios con %s ids",
        estado,
        _codigo(cuerpo),
        len(ids),
    )
    raise no_disponible(IDENTIDAD)


def _asignaturas_hasta(cuerpo, hasta_semestre):
    """Las asignaturas de la malla hasta ese semestre, o None si no tiene la forma."""
    habilitadas = {}
    try:
        for grupo in cuerpo["semestres"]:
            semestre = grupo["semestre"]
            if semestre > hasta_semestre:
                continue
            for asignatura in grupo["asignaturas"]:
                habilitadas[uuid.UUID(asignatura["id"])] = {
                    "sigla": asignatura["sigla"],
                    "nombre": asignatura["nombre"],
                    "semestre": semestre,
                }
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    return habilitadas


def malla_cursada(carrera_id, hasta_semestre):
    """Las asignaturas de la malla vigente de la carrera hasta ese semestre.

    Es la consulta de RN-01, «las asignaturas que un usuario de ese nivel ya
    cursó»: se llama con hasta_semestre = nivel - 1. Devuelve un diccionario
    {asignatura_id: {"sigla", "nombre", "semestre"}}, o None si Catalogo no
    tiene esa carrera activa. Sin malla vigente, el diccionario viene vacio, y
    tambien con hasta_semestre 0 (primer semestre), sin llamar a Catalogo.
    """
    if hasta_semestre < 1:
        return {}
    url = f"{settings.URL_CATALOGO}/api/catalog/v1/carreras/{carrera_id}/asignaturas"
    estado, cuerpo = _pedir(CATALOGO, url)
    codigo = _codigo(cuerpo)
    if estado == 404 and codigo == "not_found":
        return None
    if estado == 200:
        habilitadas = _asignaturas_hasta(cuerpo, hasta_semestre)
        if habilitadas is not None:
            return habilitadas
    logger.error("Catálogo respondió %s (codigo %s) a GET %s", estado, codigo, url)
    raise no_disponible(CATALOGO)


def asignaturas_del_catalogo():
    """Todas las asignaturas activas de Catalogo (HU-19).

    Lee la ruta publica GET /api/catalog/v1/asignaturas con el formato
    paginado, sin la clave de servicio: la pagina 1 y despues las siguientes,
    hasta total_paginas, de a 200 (su limite maximo) y con un tope de 50
    paginas (10.000 asignaturas). Devuelve {asignatura_id: {"sigla",
    "nombre"}}. Si una respuesta no es 200 o no tiene esa forma: al log y 503,
    sin devolver una lista a medias.
    """
    # Si HU-12 (criterio 5) cambia el formato paginado de GET /asignaturas,
    # esta funcion cambia con el.
    asignaturas = {}
    pagina = total_paginas = 1
    while pagina <= min(total_paginas, 50):
        url = (
            f"{settings.URL_CATALOGO}/api/catalog/v1/asignaturas"
            f"?paginado=1&limite=200&pagina={pagina}"
        )
        estado, cuerpo = _pedir(CATALOGO, url)
        try:
            # Una respuesta que no es 200, o que tiene otra forma, termina en
            # el except.
            if estado != 200:
                raise ValueError(estado)
            total_paginas = cuerpo["total_paginas"]
            # bool es subclase de int: un true no es una cantidad de paginas.
            if isinstance(total_paginas, bool) or not isinstance(total_paginas, int):
                raise ValueError(total_paginas)
            for asignatura in cuerpo["resultados"]:
                sigla, nombre = asignatura["sigla"], asignatura["nombre"]
                if not isinstance(sigla, str) or not isinstance(nombre, str):
                    raise ValueError(asignatura)
                asignaturas[uuid.UUID(asignatura["id"])] = {
                    "sigla": sigla,
                    "nombre": nombre,
                }
        except (KeyError, TypeError, ValueError, AttributeError):
            logger.error(
                "Catálogo respondió %s (codigo %s) a GET %s",
                estado,
                _codigo(cuerpo),
                url,
            )
            raise no_disponible(CATALOGO) from None
        pagina += 1
    if total_paginas > 50:
        logger.warning(
            "Catálogo tiene %s páginas de asignaturas: se leyeron las primeras 50",
            total_paginas,
        )
    return asignaturas
