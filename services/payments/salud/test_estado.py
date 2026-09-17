import pytest
from rest_framework import status


@pytest.mark.django_db
def test_estado_responde_ok(client):
    respuesta = client.get("/api/payments/v1/estado")

    assert respuesta.status_code == status.HTTP_200_OK

    cuerpo = respuesta.json()
    assert cuerpo["servicio"] == "payments"
    assert cuerpo["estado"] == "ok"
    assert cuerpo["base_de_datos"] == "ok"
