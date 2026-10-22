"""Pruebas de las reglas que sostiene la base de datos (HU-08).

Cada prueba intenta guardar algo que el anexo A prohibe y comprueba que
PostgreSQL lo rechaza, sin ayuda del codigo de la aplicacion.
"""

import uuid
from datetime import timedelta

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from .models import (
    AsignaturaRef,
    BloqueDisponibilidad,
    EstadoBloque,
    EstadoReserva,
    Modalidad,
    PerfilTutor,
    Reserva,
    UsuarioRef,
)

MANANA = timezone.now().replace(microsecond=0) + timedelta(days=1)


def persona(nombre):
    return UsuarioRef.objects.create(
        usuario_id=uuid.uuid4(), nombre=nombre, apellido="Demo"
    )


def bloque(tutor, desde_hora, hasta_hora, **campos):
    return BloqueDisponibilidad.objects.create(
        usuario=tutor,
        inicio_en=MANANA + timedelta(hours=desde_hora),
        fin_en=MANANA + timedelta(hours=hasta_hora),
        **campos,
    )


@pytest.fixture
def tutor():
    return persona("Tutora")


@pytest.fixture
def estudiante():
    return persona("Estudiante")


@pytest.fixture
def asignatura():
    return AsignaturaRef.objects.create(
        asignatura_id=uuid.uuid4(), sigla="PRU1101", nombre="Prueba"
    )


@pytest.mark.django_db
def test_tutoring_db_tiene_las_siete_tablas_y_btree_gist():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        )
        tablas = {fila[0] for fila in cursor.fetchall()}
        cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'btree_gist'")
        extension = cursor.fetchone()

    assert tablas == {
        "usuario_ref",
        "asignatura_ref",
        "perfil_tutor",
        "bloque_disponibilidad",
        "reserva",
        "evaluacion",
        "ejecucion_tarea",
        "django_migrations",
    }
    assert extension is not None


@pytest.mark.django_db
def test_dos_bloques_del_mismo_tutor_no_se_solapan(tutor):
    bloque(tutor, 10, 11)

    # atomic() deja viva la transaccion de la prueba despues del rechazo.
    with pytest.raises(IntegrityError), transaction.atomic():
        bloque(tutor, 10.5, 12)


@pytest.mark.django_db
def test_un_bloque_eliminado_no_impide_publicar_otro(tutor):
    bloque(tutor, 10, 11, estado=EstadoBloque.ELIMINADO)

    nuevo = bloque(tutor, 10, 11)

    assert nuevo.pk is not None


@pytest.mark.django_db
def test_nadie_reserva_su_propio_bloque(tutor, asignatura):
    propio = bloque(tutor, 10, 11)

    with pytest.raises(IntegrityError), transaction.atomic():
        Reserva.objects.create(
            bloque=propio, solicitante_usuario=tutor, asignatura=asignatura
        )


@pytest.mark.django_db
def test_un_bloque_admite_una_sola_reserva_confirmada(tutor, estudiante, asignatura):
    ocupado = bloque(tutor, 10, 11)
    confirmada = {
        "estado": EstadoReserva.CONFIRMADA,
        "modalidad": Modalidad.EN_LINEA,
        "lugar_o_enlace": "https://meet.example.com/prueba",
        "confirmada_en": timezone.now(),
    }
    Reserva.objects.create(
        bloque=ocupado,
        solicitante_usuario=estudiante,
        asignatura=asignatura,
        **confirmada,
    )
    otro = persona("Otro estudiante")

    with pytest.raises(IntegrityError), transaction.atomic():
        Reserva.objects.create(
            bloque=ocupado,
            solicitante_usuario=otro,
            asignatura=asignatura,
            **confirmada,
        )


@pytest.mark.django_db
def test_no_se_confirma_sin_modalidad_ni_lugar(tutor, estudiante, asignatura):
    with pytest.raises(IntegrityError), transaction.atomic():
        Reserva.objects.create(
            bloque=bloque(tutor, 10, 11),
            solicitante_usuario=estudiante,
            asignatura=asignatura,
            estado=EstadoReserva.CONFIRMADA,
            confirmada_en=timezone.now(),
        )


@pytest.mark.django_db
def test_no_se_declara_dos_veces_la_misma_asignatura(tutor, asignatura):
    PerfilTutor.objects.create(usuario=tutor, asignatura=asignatura, tarifa=3000)

    with pytest.raises(IntegrityError), transaction.atomic():
        PerfilTutor.objects.create(usuario=tutor, asignatura=asignatura, tarifa=0)


@pytest.mark.django_db
def test_la_tarifa_no_es_negativa(tutor, asignatura):
    with pytest.raises(IntegrityError), transaction.atomic():
        PerfilTutor.objects.create(usuario=tutor, asignatura=asignatura, tarifa=-1)
