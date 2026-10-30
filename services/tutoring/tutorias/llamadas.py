"""Consultas de Tutorias a Identidad y a Catalogo (HU-14 y HU-41).

Tutorias guarda copias de lectura del usuario y de la asignatura (usuario_ref
y asignatura_ref, AD-07). Para crearlas o ponerlas al dia, y para validar
RN-01, pregunta a las rutas publicas de los otros servicios:

- Identidad, GET /api/identity/v1/yo, con la misma cabecera Authorization que
  trajo la peticion. Asi Tutorias solo lee los datos de quien hace la
  peticion, y no necesita una clave de servicio.
- Catalogo, GET /api/catalog/v1/carreras/<id>/asignaturas: la malla vigente
  de la carrera, por semestre. Es publica.

Las rutas /internal con clave de servicio (Pilar 2, seccion 5.4) quedan para
lo que necesite datos de otro usuario, como la sincronizacion de las copias.

De esa convencion se toma lo demas: urllib de la biblioteca estandar, 3
segundos de espera y un solo intento. Si el otro servicio no responde, se
demora o responde 5xx, la peticion termina en un 503 servicio_no_disponible
que dice que servicio fallo. urllib solo envuelve en URLError lo que falla al
conectar: si el servicio acepta la conexion y no contesta a tiempo sale un
TimeoutError suelto; si corta la respuesta, un ConnectionError o un
http.client.HTTPException, y si el cuerpo no es JSON, un ValueError. Todos
terminan en el mismo 503.
"""

import http.client
import json
import logging
import urllib.error
import urllib.request
import uuid

from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import APIException, AuthenticationFailed

from .autenticacion import VENCIDO
from .bloques import Rechazo

logger = logging.getLogger(__name__)

IDENTIDAD = "Identidad"
CATALOGO = "Catálogo"
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


def _pedir(servicio, url, cabeceras=None):
    """GET a otro servicio. Devuelve (estado, cuerpo) si responde 2xx o 4xx.

    Si no responde, se demora o responde 5xx, lanza ServicioNoDisponible.
    """
    peticion = urllib.request.Request(
        url, headers={"Accept": "application/json", **(cabeceras or {})}
    )
    try:
        with abrir(peticion) as respuesta:
            return respuesta.status, json.loads(respuesta.read())
    except urllib.error.HTTPError as error:
        if error.code >= 500:
            error.close()
            logger.warning("%s respondió %s a GET %s", servicio, error.code, url)
            raise no_disponible(servicio) from error
        return error.code, _cuerpo_del_error(error)
    except (OSError, http.client.HTTPException, ValueError) as error:
        # OSError cubre URLError (no se pudo conectar), TimeoutError (no
        # contesto a tiempo) y ConnectionError (corto la conexion).
        logger.warning("No se pudo consultar a %s (GET %s): %r", servicio, url, error)
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
