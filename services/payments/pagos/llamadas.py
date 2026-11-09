"""Llamadas de Pagos a Tutorias (HU-23; Pilar 2, seccion 5.4; orden F1).

Pagos no conoce usuarios ni asignaturas: de quien es una reserva, en que
estado esta y cuanto vale se lo pregunta a Tutorias, y le avisa cada cambio
del pago. Las dos son rutas /internal de Tutorias (tutorias/internas.py):

- GET /api/tutoring/v1/internal/reservas/<id> (reserva);
- PATCH /api/tutoring/v1/internal/reservas/<id>/estado-pago (informar_estado).

Tiene la estructura de tutorias/llamadas.py, copiada y no importada: ningun
servicio importa codigo de otro (Pilar 2, seccion 9). De esa convencion se
toma lo demas: urllib de la biblioteca estandar, 3 segundos de espera, un solo
intento, sin proxy y la cabecera X-Clave-Servicio en las rutas /internal, sin
el token del usuario. Si Tutorias no responde, se demora o responde 5xx, la
peticion termina en un 503 servicio_no_disponible que dice que fallo
Tutorias. urllib solo envuelve en URLError lo que falla al conectar: si el
servicio acepta la conexion y no contesta a tiempo sale un TimeoutError
suelto; si corta la respuesta, un ConnectionError o un
http.client.HTTPException, y si el cuerpo no es JSON, un ValueError. Todos
terminan en el mismo 503.
"""

import http.client
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC

from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import APIException

logger = logging.getLogger(__name__)

TUTORIAS = "Tutorías"
# Segundos. urllib los aplica a cada operacion del socket, no a la llamada entera.
ESPERA_MAXIMA = 3

# Lo que devuelve informar_estado.
AVISADO = "AVISADO"
RESERVA_CANCELADA = "RESERVA_CANCELADA"
SIN_AVISO = "SIN_AVISO"

# Sin proxy: son llamadas dentro de la red de Docker. Si el computador tiene un
# proxy configurado, Docker puede pasarlo a los contenedores en HTTP_PROXY, y
# urlopen lo usaria tambien para tutoring:8000.
_ABRIDOR = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ServicioNoDisponible(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = "servicio_no_disponible"


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


def instante_preciso(valor):
    """ISO 8601 en UTC, con Z y con microsegundos: 2026-11-08T15:30:00.123456Z."""
    return (
        valor.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def _datos_de_reserva(cuerpo):
    """Lo que Pagos usa de la reserva, o None si la respuesta no tiene esa forma."""
    if not isinstance(cuerpo, dict):
        return None
    estado = cuerpo.get("estado")
    monto = cuerpo.get("monto")
    estado_pago = cuerpo.get("estado_pago")
    # bool es subclase de int: un true no es un monto.
    if isinstance(monto, bool) or not isinstance(monto, int):
        return None
    if not isinstance(estado, str):
        return None
    if estado_pago is not None and not isinstance(estado_pago, str):
        return None
    try:
        identificadores = {
            campo: uuid.UUID(cuerpo[campo])
            for campo in ("id", "solicitante_usuario_id", "tutor_usuario_id")
        }
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    return {
        **identificadores,
        "estado": estado,
        "monto": monto,
        "estado_pago": estado_pago,
    }


def reserva(reserva_id):
    """GET a la ruta interna de Tutorias: la reserva que se va a cobrar.

    Devuelve un diccionario con id, solicitante_usuario_id y tutor_usuario_id
    (uuid.UUID), estado (texto), monto (entero) y estado_pago (texto o None).
    - 200: devuelve el diccionario.
    - 404 reserva_no_encontrada: devuelve None.
    - 404 sin codigo conocido (o HTML): lanza ServicioNoDisponible y registra
      el error en el log pidiendo revisar CLAVE_SERVICIO.
    - Cualquier otra respuesta, o un 200 con otra forma: al log y 503.
    """
    url = f"{settings.URL_TUTORIAS}/api/tutoring/v1/internal/reservas/{reserva_id}"
    estado, cuerpo = _pedir(TUTORIAS, url)
    codigo = _codigo(cuerpo)

    if estado == 200:
        datos = _datos_de_reserva(cuerpo)
        if datos is not None:
            return datos
    elif estado == 404:
        if codigo == "reserva_no_encontrada":
            return None
        logger.error(
            "404 sin código conocido desde %s: revisa CLAVE_SERVICIO", TUTORIAS
        )
        raise no_disponible(TUTORIAS)

    logger.error("Tutorías respondió %s (codigo %s) a GET %s", estado, codigo, url)
    raise no_disponible(TUTORIAS)


def informar_estado(pago):
    """PATCH a la ruta interna de Tutorias con el estado del pago (A-06).

    Manda estado_pago y actualizado_en: el del pago tal como quedo guardado,
    en UTC, con Z y con microsegundos. En segundos no sirve: el aviso PENDIENTE
    (al crear) y el PAGADO (al simular) pueden caer en el mismo segundo, y con
    el mismo instante Tutorias descarta el segundo. Devuelve:
    - AVISADO, con un 2xx, tambien si Tutorias responde aplicado false (ya
      tiene algo mas nuevo);
    - RESERVA_CANCELADA, con un 409 reserva_cancelada: la reserva se cancelo
      mientras se pagaba;
    - SIN_AVISO, con cualquier otra respuesta o error, y deja una linea en el
      log con la reserva, el estado y la respuesta o el error.
    Nunca lanza una excepcion: un aviso que no sale no deshace el pago.
    """
    try:
        url = (
            f"{settings.URL_TUTORIAS}/api/tutoring/v1/internal/reservas/"
            f"{pago.reserva_id}/estado-pago"
        )
        cuerpo = {
            "estado_pago": pago.estado,
            "actualizado_en": instante_preciso(pago.actualizado_en),
        }
        estado, respuesta = _pedir(TUTORIAS, url, metodo="PATCH", cuerpo=cuerpo)
    except Exception as error:
        logger.warning(
            "No salió el aviso %s de la reserva %s a Tutorías: %r",
            pago.estado,
            pago.reserva_id,
            error,
        )
        return SIN_AVISO

    codigo = _codigo(respuesta)
    if 200 <= estado < 300:
        return AVISADO
    if estado == 409 and codigo == "reserva_cancelada":
        return RESERVA_CANCELADA
    logger.warning(
        "No salió el aviso %s de la reserva %s: Tutorías respondió %s (codigo %s)",
        pago.estado,
        pago.reserva_id,
        estado,
        codigo,
    )
    return SIN_AVISO
