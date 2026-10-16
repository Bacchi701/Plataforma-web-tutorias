from datetime import date

import pytest
from django.db import IntegrityError, connection, transaction

from .models import Asignatura, Carrera, Malla, MallaAsignatura


def consultar(sql):
    with connection.cursor() as cursor:
        cursor.execute(sql)
        return cursor.fetchall()


@pytest.fixture
def carrera():
    return Carrera.objects.create(
        codigo="PRUEBA-01", nombre="Carrera de prueba", escuela="Escuela de prueba"
    )


@pytest.mark.django_db
def test_catalog_db_tiene_las_tablas_del_modelo():
    tablas = {
        fila[0]
        for fila in consultar(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        )
    }

    assert tablas == {
        "carrera",
        "malla",
        "asignatura",
        "malla_asignatura",
        "prerrequisito",
        "sede",
        "importacion_catalogo",
        "importacion_error",
        "django_migrations",
    }


@pytest.mark.django_db
def test_la_busqueda_tiene_su_indice_trigram():
    assert consultar("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
    definicion = consultar(
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_asignatura_busqueda'"
    )[0][0]
    assert "gin_trgm_ops" in definicion


@pytest.mark.django_db
def test_una_carrera_tiene_una_sola_malla_vigente(carrera):
    Malla.objects.create(
        carrera=carrera, version="2024", vigente_desde=date(2024, 3, 1)
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        Malla.objects.create(
            carrera=carrera, version="2025", vigente_desde=date(2025, 3, 1)
        )


@pytest.mark.django_db
def test_el_semestre_va_de_1_a_12(carrera):
    malla = Malla.objects.create(
        carrera=carrera, version="2024", vigente_desde=date(2024, 3, 1)
    )
    asignatura = Asignatura.objects.create(sigla="PRU1101", nombre="Prueba")

    with pytest.raises(IntegrityError), transaction.atomic():
        MallaAsignatura.objects.create(malla=malla, asignatura=asignatura, semestre=13)
