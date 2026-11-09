"""Pruebas del reembolso interno de Pagos (internas.py, HU-23 criterio 6).

Es la ruta que pide Tutorias cuando se cancela una tutoria pagada (HU-28):
con la clave de servicio y sin token. Corren contra PostgreSQL. El aviso
REEMBOLSADO a Tutorias sale despues del commit: las pruebas lo ejecutan con
django_capture_on_commit_callbacks y lo reciben con un reemplazo de
llamadas.abrir.
"""

import io
import json
import urllib.parse
import uuid
from datetime import UTC

import pytest
from django.utils import timezone

from . import llamadas
from .models import EstadoPago, IntentoPago, Pago, ResultadoIntento, TipoIntento

URL = "/api/payments/v1/internal/pagos/reembolso"
CLAVE = "clave-de-prueba"
CON_CLAVE = {"HTTP_X_CLAVE_SERVICIO": CLAVE}


class Respuesta(io.BytesIO):
    """Lo que entrega abrir() con un 2xx: se usa con with y trae status."""

    def __init__(self, cuerpo, status=200):
        super().__init__(json.dumps(cuerpo).encode())
        self.status = status


class AvisosFalsos:
    """Hace de Tutorias: anota cada PATCH y responde 200 aplicado true.

    El reembolso no le pregunta la reserva a Tutorias: cualquier otra llamada
    hace fallar la prueba.
    """

    def __init__(self):
        self.avisos = []

    def abrir(self, peticion):
        if peticion.get_method() != "PATCH":
            # pytest.fail no hereda de Exception: informar_estado no la esconde.
            pytest.fail(f"El reembolso no pide {peticion.get_method()} a Tutorias")
        cuerpo = json.loads(peticion.data)
        ruta = urllib.parse.urlsplit(peticion.full_url).path
        self.avisos.append((ruta, cuerpo))
        return Respuesta({"aplicado": True, "estado_pago": cuerpo["estado_pago"]})


@pytest.fixture(autouse=True)
def tutorias(monkeypatch, settings):
    # En la integracion continua CLAVE_SERVICIO no existe: se fija aqui.
    settings.URL_TUTORIAS = "http://tutoring:8000"
    settings.CLAVE_SERVICIO = CLAVE
    falsa = AvisosFalsos()
    monkeypatch.setattr(llamadas, "abrir", falsa.abrir)
    return falsa


def pago_con_intentos(estado, *tipos):
    """Un pago de $5.000 con su aviso ya marcado y esos intentos exitosos."""
    pago = Pago.objects.create(
        reserva_id=uuid.uuid4(),
        monto=5000,
        estado=estado,
        notificado_en=timezone.now(),
    )
    for tipo in tipos:
        IntentoPago.objects.create(
            pago=pago, tipo=tipo, resultado=ResultadoIntento.EXITOSO
        )
    return pago


def pedir_reembolso(client, reserva_id, **cabeceras):
    return client.post(
        URL,
        {"reserva_id": str(reserva_id)},
        content_type="application/json",
        **cabeceras,
    )


def preciso(instante):
    """El actualizado_en que manda Pagos: UTC, con microsegundos y con Z."""
    return instante.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@pytest.mark.django_db
def test_un_pago_pagado_queda_reembolsado_y_tutorias_recibe_el_aviso(
    client, tutorias, django_capture_on_commit_callbacks
):
    pago = pago_con_intentos(EstadoPago.PAGADO, TipoIntento.COBRO)

    with django_capture_on_commit_callbacks(execute=True):
        respuesta = pedir_reembolso(client, pago.reserva_id, **CON_CLAVE)

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert (datos["id"], datos["estado"]) == (str(pago.id), "REEMBOLSADO")
    assert [(i["tipo"], i["resultado"]) for i in datos["intentos"]] == [
        ("REEMBOLSO", "EXITOSO"),
        ("COBRO", "EXITOSO"),
    ]
    pago.refresh_from_db()
    [(ruta, cuerpo)] = tutorias.avisos
    assert ruta == f"/api/tutoring/v1/internal/reservas/{pago.reserva_id}/estado-pago"
    assert cuerpo == {
        "estado_pago": "REEMBOLSADO",
        "actualizado_en": preciso(pago.actualizado_en),
    }
    assert pago.notificado_en is not None


@pytest.mark.django_db
def test_un_pago_ya_reembolsado_responde_200_sin_cambiar_nada(
    client, tutorias, django_capture_on_commit_callbacks
):
    # Si HU-28 lo pide dos veces, no pasa nada.
    pago = pago_con_intentos(
        EstadoPago.REEMBOLSADO, TipoIntento.COBRO, TipoIntento.REEMBOLSO
    )
    antes = pago.actualizado_en

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        respuesta = pedir_reembolso(client, pago.reserva_id, **CON_CLAVE)

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "REEMBOLSADO"
    pago.refresh_from_db()
    assert pago.actualizado_en == antes
    assert pago.intentos.count() == 2
    assert callbacks == []
    assert tutorias.avisos == []


@pytest.mark.django_db
@pytest.mark.parametrize("estado", ["PENDIENTE", "FALLIDO"])
def test_un_pago_pendiente_o_fallido_no_se_reembolsa(
    client, tutorias, django_capture_on_commit_callbacks, estado
):
    pago = pago_con_intentos(estado)

    with django_capture_on_commit_callbacks(execute=True):
        respuesta = pedir_reembolso(client, pago.reserva_id, **CON_CLAVE)

    assert respuesta.status_code == 409
    assert respuesta.json() == {
        "codigo": "pago_no_reembolsable",
        "mensaje": "Solo se reembolsa un pago PAGADO.",
        "detalles": None,
    }
    pago.refresh_from_db()
    assert pago.estado == estado
    assert not pago.intentos.exists()
    assert tutorias.avisos == []


@pytest.mark.django_db
def test_una_reserva_sin_pago_responde_404_pago_no_encontrado(client):
    respuesta = pedir_reembolso(client, uuid.uuid4(), **CON_CLAVE)

    assert respuesta.status_code == 404
    assert respuesta.json()["codigo"] == "pago_no_encontrado"


SIN_CLAVE_VALIDA = {
    "sin_cabecera": {},
    "clave_equivocada": {"HTTP_X_CLAVE_SERVICIO": "clave-equivocada"},
    "con_tilde": {"HTTP_X_CLAVE_SERVICIO": "clave-con-é"},
    "cabecera_vacia": {"HTTP_X_CLAVE_SERVICIO": ""},
    "solo_authorization": {"HTTP_AUTHORIZATION": "Bearer token-cualquiera"},
}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "cabeceras", list(SIN_CLAVE_VALIDA.values()), ids=list(SIN_CLAVE_VALIDA)
)
def test_sin_clave_valida_responde_404_ruta_no_encontrada(client, cabeceras):
    pago = pago_con_intentos(EstadoPago.PAGADO, TipoIntento.COBRO)

    respuesta = pedir_reembolso(client, pago.reserva_id, **cabeceras)

    assert respuesta.status_code == 404
    assert respuesta.json()["codigo"] == "ruta_no_encontrada"
    pago.refresh_from_db()
    assert pago.estado == "PAGADO"


@pytest.mark.django_db
def test_con_clave_servicio_vacia_en_settings_responde_404(client, settings):
    settings.CLAVE_SERVICIO = ""
    pago = pago_con_intentos(EstadoPago.PAGADO, TipoIntento.COBRO)

    respuesta = pedir_reembolso(client, pago.reserva_id, **CON_CLAVE)

    assert respuesta.status_code == 404
    assert respuesta.json()["codigo"] == "ruta_no_encontrada"
    pago.refresh_from_db()
    assert pago.estado == "PAGADO"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "cuerpo",
    [{}, {"reserva_id": "abc"}, {"reserva_id": 123}],
    ids=["falta", "texto", "numero"],
)
def test_un_reserva_id_invalido_responde_400(client, cuerpo):
    respuesta = client.post(URL, cuerpo, content_type="application/json", **CON_CLAVE)

    assert respuesta.status_code == 400
    assert respuesta.json()["codigo"] == "reserva_invalida"
