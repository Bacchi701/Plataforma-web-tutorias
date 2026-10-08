import uuid
from datetime import date

import pytest

from .models import Asignatura, Carrera, Malla, MallaAsignatura, Sede

BASE = "/api/catalog/v1"


@pytest.fixture
def carrera():
    carrera = Carrera.objects.create(
        codigo="ING-PRU", nombre="Ingeniería de Prueba", escuela="Escuela de prueba"
    )
    Carrera.objects.create(
        codigo="CERRADA", nombre="Carrera cerrada", escuela="Escuela", activa=False
    )
    antigua = Malla.objects.create(
        carrera=carrera,
        version="2020",
        vigente_desde=date(2020, 3, 1),
        vigente_hasta=date(2024, 2, 29),
    )
    vigente = Malla.objects.create(
        carrera=carrera, version="2024", vigente_desde=date(2024, 3, 1)
    )
    algoritmos = Asignatura.objects.create(
        sigla="PRO1101", nombre="Programación de Algoritmos", creditos=8
    )
    datos = Asignatura.objects.create(sigla="BDD1101", nombre="Base de Datos")
    web = Asignatura.objects.create(sigla="WEB2101", nombre="Desarrollo Web")
    MallaAsignatura.objects.create(malla=vigente, asignatura=algoritmos, semestre=1)
    MallaAsignatura.objects.create(malla=vigente, asignatura=datos, semestre=1)
    MallaAsignatura.objects.create(malla=vigente, asignatura=web, semestre=2)
    MallaAsignatura.objects.create(malla=antigua, asignatura=web, semestre=1)
    Sede.objects.create(codigo="SJ", nombre="San Joaquín", region="Metropolitana")
    return carrera


@pytest.mark.django_db
def test_carreras_lista_solo_las_activas(client, carrera):
    respuesta = client.get(f"{BASE}/carreras")

    assert respuesta.status_code == 200
    assert [c["codigo"] for c in respuesta.json()] == ["ING-PRU"]


@pytest.mark.django_db
def test_la_malla_vigente_viene_agrupada_por_semestre(client, carrera):
    respuesta = client.get(f"{BASE}/carreras/{carrera.id}/asignaturas")
    cuerpo = respuesta.json()

    assert respuesta.status_code == 200
    assert cuerpo["malla"]["version"] == "2024"
    assert [s["semestre"] for s in cuerpo["semestres"]] == [1, 2]
    primer_semestre = cuerpo["semestres"][0]["asignaturas"]
    assert [a["sigla"] for a in primer_semestre] == ["BDD1101", "PRO1101"]


@pytest.mark.django_db
def test_la_busqueda_acepta_texto_parcial_de_nombre_o_sigla(client, carrera):
    por_nombre = client.get(f"{BASE}/asignaturas", {"buscar": "datos"}).json()
    por_sigla = client.get(f"{BASE}/asignaturas", {"buscar": "web2"}).json()

    assert [a["sigla"] for a in por_nombre] == ["BDD1101"]
    assert [a["sigla"] for a in por_sigla] == ["WEB2101"]


@pytest.mark.django_db
def test_una_carrera_que_no_existe_responde_404_con_formato_uniforme(client, carrera):
    respuesta = client.get(f"{BASE}/carreras/{uuid.uuid4()}")

    assert respuesta.status_code == 404
    assert respuesta.json()["codigo"] == "not_found"
    assert respuesta.json()["mensaje"]


@pytest.mark.django_db
def test_sedes_lista_las_activas(client, carrera):
    sedes = client.get(f"{BASE}/sedes").json()

    assert [s["nombre"] for s in sedes] == ["San Joaquín"]


@pytest.mark.django_db
def test_busqueda_soporta_paginacion(client, carrera):
    respuesta = client.get(f"{BASE}/asignaturas", {"paginado": "1", "limite": "1"})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["total"] == 3
    assert cuerpo["limite"] == 1
    assert cuerpo["total_paginas"] == 3
    assert len(cuerpo["resultados"]) == 1


@pytest.mark.django_db
def test_areas_lista_las_disponibles(client, carrera):
    Asignatura.objects.filter(sigla="PRO1101").update(area="Informática")
    respuesta = client.get(f"{BASE}/areas")
    assert respuesta.status_code == 200
    assert "Informática" in respuesta.json()

