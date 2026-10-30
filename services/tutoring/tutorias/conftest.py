"""Comun a todas las pruebas de Tutorias.

Ninguna prueba llama de verdad a otro servicio: las consultas a Identidad y a
Catalogo (llamadas.py) se reemplazan con monkeypatch. Si una lo intenta,
falla con un mensaje claro. Sin esto, la prueba pasaria en el contenedor, que
alcanza a los otros servicios, y fallaria en la integracion continua, que no.
La base no pasa por aqui: psycopg conecta con libpq, no con el modulo socket.
"""

import socket

import pytest


@pytest.fixture(autouse=True)
def sin_otros_servicios(monkeypatch):
    def conectar(*args, **kwargs):
        # pytest.fail no hereda de Exception: ningun except la esconde.
        pytest.fail(
            "La prueba intentó llamar a otro servicio: reemplaza llamadas.abrir "
            "con monkeypatch."
        )

    monkeypatch.setattr(socket, "create_connection", conectar)
