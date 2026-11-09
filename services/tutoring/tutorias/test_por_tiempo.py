"""Pruebas de HU-28 (parte A), criterio 5: la expiracion de las solicitudes.

expirar_solicitudes (por_tiempo.py) no es una ruta: la ejecuta el comando del
programador (HU-29). Corren contra PostgreSQL. Los bloques que ya empezaron se
crean directo en la base, porque la API no los acepta, sin solaparse con otros
del mismo tutor (ex_bloque_sin_solape). La prueba de GET /disponibilidad firma
el token con su propio par RSA, como Identidad.
"""

import uuid
from datetime import timedelta
from decimal import Decimal

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from .autenticacion import leer_clave
from .models import (
    ESTADOS_QUE_OCUPAN,
    AsignaturaRef,
    BloqueDisponibilidad,
    EstadoBloque,
    EstadoReserva,
    Modalidad,
    Reserva,
    UsuarioRef,
)
from .por_tiempo import expirar_solicitudes

DISPONIBILIDAD = "/api/tutoring/v1/disponibilidad"


# ------------------------------------------------------------ token de acceso


@pytest.fixture(scope="module")
def clave_de_identidad():
    """Hace de la clave privada de Identidad: firma los tokens de las pruebas."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def clave_publica(clave_de_identidad, settings, tmp_path):
    """Deja la clave publica en tmp_path y Tutorias la lee de ahi."""
    ruta = tmp_path / "jwt_public.pem"
    ruta.write_bytes(
        clave_de_identidad.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    settings.JWT_CLAVE_PUBLICA = str(ruta)
    leer_clave.cache_clear()
    yield ruta
    leer_clave.cache_clear()


@pytest.fixture
def cabecera(clave_de_identidad):
    """Authorization: Bearer con un token de Identidad para ese usuario."""

    def para(usuario):
        ahora = timezone.now()
        reclamaciones = {
            "sub": str(usuario.usuario_id),
            "es_admin": False,
            "iat": int(ahora.timestamp()),
            "exp": int((ahora + timedelta(minutes=30)).timestamp()),
            "iss": "identity",
        }
        token = jwt.encode(reclamaciones, clave_de_identidad, algorithm="RS256")
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    return para


# ------------------------------------------------------------ datos


def persona(nombre, apellido="Demo"):
    """Un usuario con copia en Tutorias, creado directo en la base."""
    return UsuarioRef.objects.create(
        usuario_id=uuid.uuid4(), nombre=nombre, apellido=apellido
    )


@pytest.fixture
def asignatura(db):
    return AsignaturaRef.objects.create(
        asignatura_id=uuid.uuid4(), sigla="BDD1101", nombre="Base de Datos"
    )


@pytest.fixture
def tutora(db):
    """Valentina. La expiracion no mira los perfiles: no le hace falta uno."""
    return persona("Valentina", "Soto")


@pytest.fixture
def camila(db):
    return persona("Camila", "Rojas")


def bloque(tutor, inicio, minutos=60, **campos):
    """Bloque del tutor que empieza en inicio y dura esos minutos."""
    return BloqueDisponibilidad.objects.create(
        usuario=tutor,
        inicio_en=inicio,
        fin_en=inicio + timedelta(minutes=minutos),
        **campos,
    )


def reserva(
    en_bloque, solicitante, asignatura, estado=EstadoReserva.SOLICITADA, **campos
):
    """Reserva creada directo en la base, que cumple las reglas del modelo."""
    valores = {"monto": Decimal("5000")}
    if estado in ESTADOS_QUE_OCUPAN:
        # RN-07: confirmada, realizada o evaluada, tiene modalidad y lugar.
        valores.update(
            modalidad=Modalidad.EN_LINEA,
            lugar_o_enlace="https://meet.example.com/prueba",
            confirmada_en=timezone.now() - timedelta(days=1),
        )
    elif estado != EstadoReserva.SOLICITADA:
        valores["cerrada_en"] = timezone.now() - timedelta(days=1)
    valores.update(campos)
    return Reserva.objects.create(
        bloque=en_bloque,
        solicitante_usuario=solicitante,
        asignatura=asignatura,
        estado=estado,
        **valores,
    )


def como_esta(una_reserva):
    """El estado y cerrada_en de la reserva, leidos de la base."""
    una_reserva.refresh_from_db()
    return una_reserva.estado, una_reserva.cerrada_en


def como_esta_el_bloque(un_bloque):
    un_bloque.refresh_from_db()
    return un_bloque.estado, un_bloque.actualizado_en


# ------------------------------------------------------------ criterio 5 (RN-03)


@pytest.mark.django_db
def test_la_solicitud_de_un_bloque_que_ya_empezo_queda_expirada(
    tutora, camila, asignatura
):
    ahora = timezone.now()
    empezado = bloque(tutora, ahora - timedelta(hours=1))
    solicitud = reserva(empezado, camila, asignatura)
    bloque_antes = como_esta_el_bloque(empezado)

    cambiadas = expirar_solicitudes(ahora=ahora)

    assert cambiadas == 1
    assert como_esta(solicitud) == (EstadoReserva.EXPIRADA, ahora)
    # No es una cancelacion: nadie la cancelo.
    assert solicitud.cancelada_por_usuario_id is None
    # El bloque no cambia.
    assert como_esta_el_bloque(empezado) == bloque_antes


@pytest.mark.django_db
def test_la_solicitud_de_un_bloque_que_empieza_justo_ahora_tambien_expira(
    tutora, camila, asignatura
):
    ahora = timezone.now()
    solicitud = reserva(bloque(tutora, ahora), camila, asignatura)

    assert expirar_solicitudes(ahora=ahora) == 1
    assert como_esta(solicitud) == (EstadoReserva.EXPIRADA, ahora)


@pytest.mark.django_db
def test_lo_que_no_es_una_solicitud_de_un_bloque_que_empezo_no_cambia(
    tutora, camila, asignatura
):
    ahora = timezone.now()
    # Una solicitud de un bloque futuro.
    futura = reserva(bloque(tutora, ahora + timedelta(hours=1)), camila, asignatura)
    # En un bloque que ya empezo: la confirmada de Camila, la de Diego, que se
    # rechazo al confirmarla, y la de Fernanda, que la retiro antes.
    empezado = bloque(
        tutora, ahora - timedelta(hours=2), minutos=90, estado=EstadoBloque.OCUPADO
    )
    diego = persona("Diego", "Herrera")
    fernanda = persona("Fernanda", "Castro")
    otras = [
        reserva(empezado, camila, asignatura, EstadoReserva.CONFIRMADA),
        reserva(empezado, diego, asignatura, EstadoReserva.RECHAZADA),
        reserva(empezado, fernanda, asignatura, EstadoReserva.CANCELADA),
    ]
    antes = [como_esta(r) for r in otras]

    assert expirar_solicitudes(ahora=ahora) == 0
    assert como_esta(futura) == (EstadoReserva.SOLICITADA, None)
    assert [como_esta(r) for r in otras] == antes


@pytest.mark.django_db
def test_dos_veces_seguidas_la_segunda_no_cambia_nada(tutora, camila, asignatura):
    ahora = timezone.now()
    solicitud = reserva(bloque(tutora, ahora - timedelta(hours=1)), camila, asignatura)

    primera = expirar_solicitudes(ahora=ahora)
    segunda = expirar_solicitudes(ahora=ahora + timedelta(minutes=5))

    assert (primera, segunda) == (1, 0)
    # La segunda ya no la encuentra SOLICITADA: cerrada_en sigue siendo el
    # ahora de la primera.
    assert como_esta(solicitud) == (EstadoReserva.EXPIRADA, ahora)


@pytest.mark.django_db
def test_usa_el_ahora_que_recibe_y_no_la_hora_del_reloj(tutora, camila, asignatura):
    reloj = timezone.now()
    # Segun el reloj, uno ya empezo y el otro empieza manana.
    de_hace_una_hora = reserva(
        bloque(tutora, reloj - timedelta(hours=1)), camila, asignatura
    )
    manana = bloque(tutora, reloj + timedelta(days=1))
    de_manana = reserva(manana, camila, asignatura)

    # Hace dos horas, ninguno habia empezado.
    assert expirar_solicitudes(ahora=reloj - timedelta(hours=2)) == 0
    assert como_esta(de_hace_una_hora) == (EstadoReserva.SOLICITADA, None)

    # Un minuto despues del inicio del de manana, los dos ya empezaron.
    despues = manana.inicio_en + timedelta(minutes=1)
    assert expirar_solicitudes(ahora=despues) == 2
    assert como_esta(de_hace_una_hora) == (EstadoReserva.EXPIRADA, despues)
    assert como_esta(de_manana) == (EstadoReserva.EXPIRADA, despues)


@pytest.mark.django_db
def test_sin_ahora_usa_la_hora_del_reloj(tutora, camila, asignatura):
    ahora = timezone.now()
    empezada = reserva(bloque(tutora, ahora - timedelta(hours=1)), camila, asignatura)
    futura = reserva(bloque(tutora, ahora + timedelta(hours=1)), camila, asignatura)

    assert expirar_solicitudes() == 1

    estado, cerrada_en = como_esta(empezada)
    assert estado == EstadoReserva.EXPIRADA
    assert ahora <= cerrada_en <= timezone.now()
    assert como_esta(futura) == (EstadoReserva.SOLICITADA, None)


@pytest.mark.django_db
def test_en_la_disponibilidad_la_solicitud_expirada_ya_no_cuenta(
    client, cabecera, tutora, camila, asignatura
):
    """GET /disponibilidad (HU-15) muestra los bloques que todavia no terminan."""
    ahora = timezone.now()
    en_curso = bloque(tutora, ahora - timedelta(minutes=30))
    reserva(en_curso, camila, asignatura)

    def pendientes():
        respuesta = client.get(DISPONIBILIDAD, **cabecera(tutora))
        assert respuesta.status_code == 200
        return {b["id"]: b["solicitudes_pendientes"] for b in respuesta.json()}

    assert pendientes() == {str(en_curso.id): 1}

    assert expirar_solicitudes() == 1

    assert pendientes() == {str(en_curso.id): 0}


@pytest.mark.django_db
def test_es_un_solo_update_con_el_estado_en_la_tabla_que_se_actualiza(
    tutora, camila, asignatura
):
    """Lo que explica el docstring de expirar_solicitudes.

    Con bloque__inicio_en__lte, Django escribiria UPDATE "reserva" ... WHERE
    "reserva"."id" IN (SELECT ...), con el estado dentro de la subconsulta.
    """
    ahora = timezone.now()
    reserva(bloque(tutora, ahora - timedelta(hours=1)), camila, asignatura)

    with CaptureQueriesContext(connection) as consultas:
        cambiadas = expirar_solicitudes(ahora=ahora)

    assert cambiadas == 1
    assert len(consultas) == 1
    sql = consultas[0]["sql"]
    assert sql.startswith('UPDATE "reserva" ')
    assert '"reserva"."id" IN' not in sql
    assert '"reserva"."estado"' in sql
