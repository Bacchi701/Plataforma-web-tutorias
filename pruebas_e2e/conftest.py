"""Base de las pruebas de extremo a extremo (HU-34; Pilar 5, seccion 9.1).

Son pruebas de pytest sobre el sistema levantado con Docker, desde fuera de
los servicios: todo lo de la API se pide por el gateway, como lo pide el
navegador, y a la bandeja de Mailpit se va solo a buscar los correos. Usan solo
la biblioteca estandar (urllib) y pytest, para correr en un contenedor
desechable python:3.12-slim conectado a la red plataforma-tutorias_borde
(docker run --network plataforma-tutorias_borde ...).

URL_GATEWAY (por defecto http://gateway) y URL_BANDEJA (por defecto
http://mailpit:8025) se cambian con variables de entorno: asi tambien corren
desde un computador con Python, con http://localhost:8080 y
http://localhost:8025.
"""

import http.client
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

URL_GATEWAY = os.environ.get("URL_GATEWAY", "http://gateway").rstrip("/")
URL_BANDEJA = os.environ.get("URL_BANDEJA", "http://mailpit:8025").rstrip("/")

# Segundos de espera de cada peticion: lo mismo que espera el gateway a un
# servicio antes de cortar (proxy_read_timeout en infra/nginx/nginx.conf).
ESPERA_MAXIMA = 30
# Mailpit responde solo al nombre localhost (MP_ALLOWED_HOSTS en
# docker-compose.yml): es el Host con que la consulta la integracion continua.
HOST_BANDEJA = "localhost:8025"
# Segundos que se espera un correo, y cada cuanto se vuelve a mirar la bandeja.
ESPERA_CORREO = 20
PAUSA_CORREO = 0.5

# Sin proxy, como _ABRIDOR en services/tutoring/tutorias/llamadas.py: si el
# computador tiene uno configurado, Docker puede pasarlo al contenedor en
# HTTP_PROXY, y urllib lo usaria tambien para gateway y mailpit.
_ABRIDOR = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _json_o_none(contenido):
    """El JSON de una respuesta, o None si viene vacia o no es JSON."""
    try:
        return json.loads(contenido)
    except ValueError:
        return None


class Cliente:
    """La API del sistema, por el gateway."""

    def __init__(self, url_base):
        self.url_base = url_base

    def pedir(self, metodo, ruta, cuerpo=None, token=None):
        """Devuelve (estado, JSON o None, segundos que tardo).

        Un 4xx o un 5xx no lanza una excepcion: se devuelve igual, para que la
        prueba lo revise. Si el gateway no contesta, urllib si lanza (URLError
        o TimeoutError). Los segundos van desde que sale la peticion hasta que
        llega el ultimo byte de la respuesta (time.perf_counter).
        """
        cabeceras = {"Accept": "application/json"}
        datos = None
        if cuerpo is not None:
            datos = json.dumps(cuerpo).encode("utf-8")
            cabeceras["Content-Type"] = "application/json"
        if token is not None:
            cabeceras["Authorization"] = f"Bearer {token}"
        peticion = urllib.request.Request(
            self.url_base + ruta, data=datos, headers=cabeceras, method=metodo
        )
        inicio = time.perf_counter()
        try:
            with _ABRIDOR.open(peticion, timeout=ESPERA_MAXIMA) as respuesta:
                estado, contenido = respuesta.status, respuesta.read()
        except urllib.error.HTTPError as error:
            try:
                estado, contenido = error.code, error.read()
            finally:
                error.close()
        segundos = time.perf_counter() - inicio
        return estado, _json_o_none(contenido), segundos


class Bandeja:
    """La bandeja de Mailpit, donde llegan los correos que envia Identidad."""

    def __init__(self, url_base):
        self.url_base = url_base

    def _leer_json(self, ruta):
        peticion = urllib.request.Request(
            self.url_base + ruta,
            headers={"Accept": "application/json", "Host": HOST_BANDEJA},
        )
        with _ABRIDOR.open(peticion, timeout=ESPERA_MAXIMA) as respuesta:
            return json.loads(respuesta.read())

    def listar(self):
        """Los correos de la bandeja, del mas nuevo al mas antiguo.

        Cada uno es un elemento de messages en GET /api/v1/messages: su "ID",
        sus destinatarios en "To" (una lista de {"Name", "Address"}) y su
        "Subject".
        """
        return self._leer_json("/api/v1/messages")["messages"]

    def leer(self, id_correo):
        """El texto del correo: "Text" de GET /api/v1/message/<ID>."""
        ruta = "/api/v1/message/" + urllib.parse.quote(id_correo)
        return self._leer_json(ruta)["Text"]

    def esperar(self, direccion, asunto, segundos=ESPERA_CORREO):
        """El correo mas nuevo para esa direccion con ese texto en el asunto.

        Mira la bandeja cada medio segundo, hasta que pasan esos segundos.
        Devuelve el correo como lo trae listar(), o None si no llego.
        """
        direccion = direccion.lower()
        limite = time.monotonic() + segundos
        while True:
            for correo in self.listar():
                destinatarios = [
                    (persona.get("Address") or "").lower()
                    for persona in correo.get("To") or []
                ]
                titulo = correo.get("Subject") or ""
                if direccion in destinatarios and asunto in titulo:
                    return correo
            if time.monotonic() >= limite:
                return None
            time.sleep(PAUSA_CORREO)


@pytest.fixture(scope="session")
def cliente():
    """El cliente del gateway, uno para toda la sesion."""
    return Cliente(URL_GATEWAY)


@pytest.fixture(scope="session")
def bandeja():
    """La bandeja de Mailpit, una para toda la sesion."""
    return Bandeja(URL_BANDEJA)


@pytest.fixture(scope="session", autouse=True)
def sistema_levantado(cliente):
    """Antes de la primera prueba, el gateway tiene que responder GET /estado.

    Si no responde 200, pytest.exit corta la sesion: sin el sistema levantado,
    todas las pruebas fallarian por lo mismo.
    """
    try:
        estado, _, _ = cliente.pedir("GET", "/estado")
        detalle = f"respondió {estado}"
    except (OSError, http.client.HTTPException, ValueError) as error:
        estado, detalle = None, f"no respondió: {error}"
    if estado != 200:
        pytest.exit(
            "Levanta el sistema: docker compose up -d --wait "
            f"(GET {URL_GATEWAY}/estado {detalle})"
        )
