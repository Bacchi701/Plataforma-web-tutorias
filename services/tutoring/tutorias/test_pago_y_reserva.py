"""RN-05 en Tutorias: el aviso de un pago no cambia la reserva (HU-36).

Pagos es la unica fuente del estado del pago. Tutorias guarda una copia, que
cambia solo con PATCH /internal/reservas/<id>/estado-pago (internas.py, HU-23).
test_internas.py revisa esa copia; estas pruebas revisan que el aviso no toque
nada mas: un pago rechazado deja la reserva CONFIRMADA y su bloque OCUPADO, y
el reintento aprobado tampoco la da por realizada. La tutoria pasa a REALIZADA
solo por la hora (cerrar_realizadas, HU-29). La reserva se crea directo en la
base y la ruta se llama con X-Clave-Servicio, sin token, como en
test_internas.py.
"""

import uuid
from datetime import UTC, timedelta

import pytest
from django.utils import timezone

from .models import (
    AsignaturaRef,
    BloqueDisponibilidad,
    EstadoBloque,
    EstadoPago,
    EstadoReserva,
    Modalidad,
    Reserva,
    UsuarioRef,
)

URL = "/api/tutoring/v1/internal/reservas"
CLAVE = "clave-de-prueba"
CON_CLAVE = {"HTTP_X_CLAVE_SERVICIO": CLAVE}
MANANA = (timezone.now() + timedelta(days=1)).replace(
    hour=12, minute=0, second=0, microsecond=0
)


@pytest.fixture(autouse=True)
def clave_servicio(settings):
    # En la integracion continua CLAVE_SERVICIO no existe: se fija aqui.
    settings.CLAVE_SERVICIO = CLAVE


def persona(nombre):
    return UsuarioRef.objects.create(
        usuario_id=uuid.uuid4(), nombre=nombre, apellido="Demo"
    )


@pytest.fixture
def tutoria(db):
    """Una tutoria CONFIRMADA de $5.000, con su bloque OCUPADO y el pago PENDIENTE.

    Como la dejan HU-22 al confirmarla y HU-23 cuando Pagos crea el pago.
    """
    asignatura = AsignaturaRef.objects.create(
        asignatura_id=uuid.uuid4(), sigla="BDD1101", nombre="Base de Datos"
    )
    bloque = BloqueDisponibilidad.objects.create(
        usuario=persona("Valentina"),
        inicio_en=MANANA,
        fin_en=MANANA + timedelta(hours=1),
        estado=EstadoBloque.OCUPADO,
    )
    return Reserva.objects.create(
        bloque=bloque,
        solicitante_usuario=persona("Camila"),
        asignatura=asignatura,
        estado=EstadoReserva.CONFIRMADA,
        modalidad=Modalidad.EN_LINEA,
        lugar_o_enlace="https://meet.example.com/prueba",
        confirmada_en=timezone.now(),
        monto=5000,
        estado_pago=EstadoPago.PENDIENTE,
        pago_actualizado_en=timezone.now() - timedelta(minutes=10),
    )


def avisar(client, reserva, estado_pago, instante):
    """El aviso de Pagos, con su instante en UTC, con microsegundos y con Z."""
    texto = instante.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return client.patch(
        f"{URL}/{reserva.id}/estado-pago",
        {"estado_pago": estado_pago, "actualizado_en": texto},
        content_type="application/json",
        **CON_CLAVE,
    )


def como_esta(reserva):
    """La reserva, su bloque y la copia del pago, leidos de la base."""
    reserva.refresh_from_db()
    bloque = BloqueDisponibilidad.objects.get(pk=reserva.bloque_id)
    return (
        reserva.estado,
        reserva.cerrada_en,
        bloque.estado,
        reserva.estado_pago,
        reserva.pago_actualizado_en,
    )


@pytest.mark.django_db
def test_un_pago_rechazado_deja_la_reserva_confirmada(client, tutoria):
    rechazo = timezone.now()

    respuesta = avisar(client, tutoria, "FALLIDO", rechazo)

    assert respuesta.status_code == 200
    assert respuesta.json() == {"aplicado": True, "estado_pago": "FALLIDO"}
    # Cambia solo la copia del pago: la reserva y su bloque quedan como estaban.
    assert como_esta(tutoria) == (
        EstadoReserva.CONFIRMADA,
        None,
        EstadoBloque.OCUPADO,
        EstadoPago.FALLIDO,
        rechazo,
    )


@pytest.mark.django_db
def test_el_reintento_aprobado_tampoco_da_la_reserva_por_realizada(client, tutoria):
    """Si el pago falla, el estudiante lo reintenta sobre la misma reserva."""
    rechazo = timezone.now()
    aprobado = rechazo + timedelta(seconds=30)

    respuestas = [
        avisar(client, tutoria, "FALLIDO", rechazo),
        avisar(client, tutoria, "PAGADO", aprobado),
    ]

    assert [r.json() for r in respuestas] == [
        {"aplicado": True, "estado_pago": "FALLIDO"},
        {"aplicado": True, "estado_pago": "PAGADO"},
    ]
    assert como_esta(tutoria) == (
        EstadoReserva.CONFIRMADA,
        None,
        EstadoBloque.OCUPADO,
        EstadoPago.PAGADO,
        aprobado,
    )
