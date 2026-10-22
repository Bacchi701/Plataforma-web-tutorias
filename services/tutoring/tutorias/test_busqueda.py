"""Pruebas de la busqueda de tutores (HU-20, criterios 1 a 4).

Cada prueba arma sus datos con el modelo y consulta la API sin sesion, como lo
hace el frontend. El criterio 5 (500 usuarios, menos de 2 segundos) no se mide
aqui: su medicion formal es parte de HU-34.
"""

import socket
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from .models import (
    AsignaturaRef,
    BloqueDisponibilidad,
    EstadoBloque,
    EstadoReserva,
    Evaluacion,
    Modalidad,
    PerfilTutor,
    Reserva,
    UsuarioRef,
)

AHORA = timezone.now().replace(microsecond=0)
TUTORES = "/api/tutoring/v1/tutores"


# ------------------------------------------------------------- datos de prueba


def persona(nombre, activo=True, promedio="0.00", total=0):
    return UsuarioRef.objects.create(
        usuario_id=uuid.uuid4(),
        nombre=nombre,
        apellido="Demo",
        carrera_id=uuid.uuid4(),
        sede_id=uuid.uuid4(),
        activo=activo,
        reputacion_promedio=Decimal(promedio),
        reputacion_total=total,
    )


def nueva_asignatura(sigla, nombre):
    return AsignaturaRef.objects.create(
        asignatura_id=uuid.uuid4(), sigla=sigla, nombre=nombre
    )


def bloque(tutor, dias, estado=EstadoBloque.LIBRE):
    """Bloque de una hora a tantos dias de hoy (negativo: ya paso).

    Cada prueba usa un dia distinto por tutor: dos bloques vigentes del mismo
    tutor no se pueden solapar (ex_bloque_sin_solape).
    """
    inicio = AHORA + timedelta(days=dias)
    return BloqueDisponibilidad.objects.create(
        usuario=tutor,
        inicio_en=inicio,
        fin_en=inicio + timedelta(hours=1),
        estado=estado,
    )


def evaluacion(tutor, asignatura, estudiante, dias, calificacion=5, retirada=False):
    """Evaluacion de una reserva EVALUADA sobre un bloque pasado del tutor.

    La reserva cumple ck_reserva_confirmada_completa (modalidad, lugar y
    confirmada_en) y no tiene pago (estado_pago nulo, monto 0). El estudiante
    no es el tutor: lo exige el disparador trg_reserva_no_auto.
    """
    ocupado = bloque(tutor, dias, estado=EstadoBloque.OCUPADO)
    reserva = Reserva.objects.create(
        bloque=ocupado,
        solicitante_usuario=estudiante,
        asignatura=asignatura,
        estado=EstadoReserva.EVALUADA,
        modalidad=Modalidad.EN_LINEA,
        lugar_o_enlace="https://meet.example.com/prueba",
        confirmada_en=ocupado.inicio_en - timedelta(days=1),
        cerrada_en=ocupado.fin_en,
    )
    return Evaluacion.objects.create(
        reserva=reserva,
        calificacion=calificacion,
        comentario=f"Comentario de prueba {-dias}.",
        creada_en=ocupado.fin_en + timedelta(hours=1),
        retirada_en=AHORA if retirada else None,
        retirada_por_usuario_id=uuid.uuid4() if retirada else None,
    )


@pytest.fixture
def base_de_datos():
    return nueva_asignatura("BDD1101", "Base de Datos")


@pytest.fixture
def redes():
    return nueva_asignatura("RED1101", "Fundamentos de Redes")


@pytest.fixture
def estudiante():
    return persona("Estudiante")


# ------------------------------------------------------------------- consultas


def buscar(client, asignatura):
    return client.get(TUTORES, {"asignatura": str(asignatura.asignatura_id)})


def perfil_de(client, usuario_id):
    return client.get(f"{TUTORES}/{usuario_id}")


def nombres(cuerpo):
    return [tutor["nombre"] for tutor in cuerpo]


def fecha(texto):
    """Fecha de la respuesta: ISO 8601 y con zona horaria."""
    valor = datetime.fromisoformat(texto)
    assert valor.tzinfo is not None
    return valor


def codigo_de_error(respuesta):
    """Codigo del error, con o sin el formato unico.

    Con el formato unico (configuracion.errores, llega con HU-17) viene en el
    cuerpo como "codigo". Con el manejador de DRF, que usa Tutorias hasta
    entonces, el cuerpo trae solo "detail" y el codigo queda en el ErrorDetail.
    """
    cuerpo = respuesta.json()
    if "codigo" in cuerpo:
        return cuerpo["codigo"]
    return respuesta.data["detail"].code


def claves(valor):
    """Todas las claves de un JSON, a cualquier profundidad."""
    if isinstance(valor, dict):
        for clave, contenido in valor.items():
            yield clave
            yield from claves(contenido)
    elif isinstance(valor, list):
        for elemento in valor:
            yield from claves(elemento)


def cantidad_de_consultas(client, url, **parametros):
    with CaptureQueriesContext(connection) as consultas:
        respuesta = client.get(url, parametros)
    assert respuesta.status_code == 200
    return len(consultas)


@pytest.fixture
def sin_red(monkeypatch):
    """Hace fallar cualquier conexion de red que intente el codigo.

    La base de la prueba no pasa por aqui: psycopg conecta con libpq, no con
    el modulo socket de Python, y su conexion ya esta abierta.
    """

    def conectar(*args, **kwargs):
        raise AssertionError("La búsqueda intentó conectarse a otro servicio.")

    monkeypatch.setattr(socket.socket, "connect", conectar)
    monkeypatch.setattr(socket.socket, "connect_ex", conectar)


# ---------------------------------------------- GET /tutores?asignatura= (1 y 2)


@pytest.mark.django_db
def test_lista_los_tutores_con_perfil_activo_en_la_asignatura(
    client, base_de_datos, redes
):
    valentina = persona("Valentina", promedio="4.50", total=2)
    PerfilTutor.objects.create(
        usuario=valentina,
        asignatura=base_de_datos,
        tarifa=5000,
        descripcion="Modelo entidad-relación y SQL.",
    )
    # Tutorea otra asignatura: no aparece en esta busqueda.
    PerfilTutor.objects.create(usuario=persona("Fernanda"), asignatura=redes)

    respuesta = buscar(client, base_de_datos)

    assert respuesta.status_code == 200
    assert respuesta.json() == [
        {
            "usuario_id": str(valentina.usuario_id),
            "nombre": "Valentina",
            "apellido": "Demo",
            "carrera_id": str(valentina.carrera_id),
            "sede_id": str(valentina.sede_id),
            "asignatura": {
                "asignatura_id": str(base_de_datos.asignatura_id),
                "sigla": "BDD1101",
                "nombre": "Base de Datos",
            },
            "tarifa": 5000,
            "descripcion": "Modelo entidad-relación y SQL.",
            "reputacion": {"promedio": 4.5, "total": 2},
        }
    ]


@pytest.mark.django_db
def test_no_salen_la_cuenta_desactivada_ni_el_perfil_desactivado(client, base_de_datos):
    PerfilTutor.objects.create(usuario=persona("Activa"), asignatura=base_de_datos)
    # Las dos tienen mejor reputacion: si se colaran, saldrian primero.
    desactivada = persona("Desactivada", activo=False, promedio="5.00", total=9)
    PerfilTutor.objects.create(usuario=desactivada, asignatura=base_de_datos)
    con_perfil_inactivo = persona("Perfil inactivo", promedio="5.00", total=9)
    PerfilTutor.objects.create(
        usuario=con_perfil_inactivo, asignatura=base_de_datos, activo=False
    )

    respuesta = buscar(client, base_de_datos)

    assert respuesta.status_code == 200
    assert nombres(respuesta.json()) == ["Activa"]


@pytest.mark.django_db
def test_ordena_por_reputacion_y_despues_por_tarifa(client, base_de_datos):
    tutores = [
        ("Cuarta", "4.80", 5, 4000),
        ("Tercera", "4.80", 5, 3000),
        ("Primera", "5.00", 1, 9000),
        ("Segunda", "4.80", 10, 6000),
        ("Quinta", "0.00", 0, 0),
    ]
    for nombre, promedio, total, tarifa in tutores:
        PerfilTutor.objects.create(
            usuario=persona(nombre, promedio=promedio, total=total),
            asignatura=base_de_datos,
            tarifa=tarifa,
        )

    respuesta = buscar(client, base_de_datos)

    # Promedio y cantidad de mayor a menor; con la misma reputacion, la tarifa
    # mas baja primero. Segunda va antes que Tercera aunque cobra mas: la
    # cantidad pesa antes que la tarifa. Tercera va antes que Cuarta, que por
    # nombre iria primero: las separa la tarifa, no el desempate por nombre.
    assert nombres(respuesta.json()) == [
        "Primera",
        "Segunda",
        "Tercera",
        "Cuarta",
        "Quinta",
    ]


@pytest.mark.django_db
def test_una_asignatura_sin_tutores_responde_una_lista_vacia(client, base_de_datos):
    respuesta = buscar(client, base_de_datos)

    assert respuesta.status_code == 200
    assert respuesta.json() == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("consulta", "codigo"),
    [
        ({}, "asignatura_requerida"),
        ({"asignatura": ""}, "asignatura_requerida"),
        ({"asignatura": "base-de-datos"}, "asignatura_invalida"),
    ],
)
def test_sin_asignatura_o_con_un_valor_que_no_es_uuid_responde_400(
    client, consulta, codigo
):
    respuesta = client.get(TUTORES, consulta)

    assert respuesta.status_code == 400
    assert codigo_de_error(respuesta) == codigo


# ------------------------------------------------------ GET /tutores/<id> (3)


@pytest.mark.django_db
def test_el_perfil_publico_trae_reputacion_asignaturas_bloques_y_evaluaciones(
    client, base_de_datos, redes, estudiante
):
    tutora = persona("Valentina", promedio="4.00", total=2)
    PerfilTutor.objects.create(
        usuario=tutora, asignatura=redes, tarifa=0, descripcion="Subredes."
    )
    PerfilTutor.objects.create(usuario=tutora, asignatura=base_de_datos, tarifa=5000)
    matematica = nueva_asignatura("MAT1101", "Matemática Aplicada")
    PerfilTutor.objects.create(usuario=tutora, asignatura=matematica, activo=False)

    despues = bloque(tutora, 3)
    antes = bloque(tutora, 1)
    bloque(tutora, -2)  # libre, pero ya paso
    bloque(tutora, 2, estado=EstadoBloque.OCUPADO)
    bloque(tutora, 4, estado=EstadoBloque.ELIMINADO)
    bloque(persona("Otro tutor"), 1)

    vieja = evaluacion(tutora, base_de_datos, estudiante, dias=-10, calificacion=3)
    nueva = evaluacion(tutora, redes, estudiante, dias=-5, calificacion=5)
    evaluacion(
        tutora, base_de_datos, estudiante, dias=-7, calificacion=1, retirada=True
    )
    evaluacion(persona("Otra tutora"), redes, estudiante, dias=-3)

    respuesta = perfil_de(client, tutora.usuario_id)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert set(cuerpo) == {
        "usuario_id",
        "nombre",
        "apellido",
        "carrera_id",
        "sede_id",
        "reputacion",
        "asignaturas",
        "bloques",
        "evaluaciones",
    }
    assert cuerpo["usuario_id"] == str(tutora.usuario_id)
    assert cuerpo["nombre"] == "Valentina"
    assert cuerpo["apellido"] == "Demo"
    assert cuerpo["carrera_id"] == str(tutora.carrera_id)
    assert cuerpo["sede_id"] == str(tutora.sede_id)
    assert cuerpo["reputacion"] == {"promedio": 4.0, "total": 2}

    # Solo los perfiles activos, por sigla.
    assert cuerpo["asignaturas"] == [
        {
            "asignatura_id": str(base_de_datos.asignatura_id),
            "sigla": "BDD1101",
            "nombre": "Base de Datos",
            "tarifa": 5000,
            "descripcion": None,
        },
        {
            "asignatura_id": str(redes.asignatura_id),
            "sigla": "RED1101",
            "nombre": "Fundamentos de Redes",
            "tarifa": 0,
            "descripcion": "Subredes.",
        },
    ]

    # Solo los LIBRES que empiezan en el futuro, del mas proximo al mas lejano:
    # no salen el pasado, el OCUPADO, el ELIMINADO ni el de otro tutor.
    bloques = cuerpo["bloques"]
    assert [b["id"] for b in bloques] == [str(antes.id), str(despues.id)]
    assert set(bloques[0]) == {"id", "inicio_en", "fin_en"}
    assert fecha(bloques[0]["inicio_en"]) == antes.inicio_en
    assert fecha(bloques[0]["fin_en"]) == antes.fin_en

    # Solo las visibles, de la mas nueva a la mas antigua: no salen la
    # retirada por el administrador ni la de otra tutora.
    evaluaciones = cuerpo["evaluaciones"]
    assert [e["calificacion"] for e in evaluaciones] == [5, 3]
    assert set(evaluaciones[0]) == {
        "calificacion",
        "comentario",
        "creada_en",
        "asignatura",
    }
    assert evaluaciones[0]["comentario"] == nueva.comentario
    assert fecha(evaluaciones[0]["creada_en"]) == nueva.creada_en
    assert evaluaciones[0]["asignatura"] == {
        "sigla": "RED1101",
        "nombre": "Fundamentos de Redes",
    }
    assert fecha(evaluaciones[1]["creada_en"]) == vieja.creada_en


@pytest.mark.django_db
def test_el_perfil_muestra_hasta_20_bloques_y_10_evaluaciones(
    client, base_de_datos, estudiante
):
    tutora = persona("Tutora")
    PerfilTutor.objects.create(usuario=tutora, asignatura=base_de_datos)
    bloques = [bloque(tutora, dia) for dia in range(1, 22)]
    evaluaciones = [
        evaluacion(tutora, base_de_datos, estudiante, dias=-dia) for dia in range(1, 12)
    ]

    cuerpo = perfil_de(client, tutora.usuario_id).json()

    # Quedan fuera el bloque mas lejano y la evaluacion mas antigua.
    assert [b["id"] for b in cuerpo["bloques"]] == [str(b.id) for b in bloques[:20]]
    assert [fecha(e["creada_en"]) for e in cuerpo["evaluaciones"]] == [
        e.creada_en for e in evaluaciones[:10]
    ]


@pytest.mark.django_db
def test_el_perfil_responde_404_si_no_es_un_tutor_activo(client, base_de_datos):
    desactivada = persona("Desactivada", activo=False)
    PerfilTutor.objects.create(usuario=desactivada, asignatura=base_de_datos)
    sin_perfil_activo = persona("Sin perfil activo")
    PerfilTutor.objects.create(
        usuario=sin_perfil_activo, asignatura=base_de_datos, activo=False
    )
    sin_perfiles = persona("Sin perfiles")

    casos = {
        "no existe": uuid.uuid4(),
        "desactivada (RN-08)": desactivada.usuario_id,
        "sin perfiles activos": sin_perfil_activo.usuario_id,
        "sin perfiles": sin_perfiles.usuario_id,
    }
    for caso, usuario_id in casos.items():
        respuesta = perfil_de(client, usuario_id)
        assert respuesta.status_code == 404, caso
        assert codigo_de_error(respuesta) == "not_found", caso


# ------------------------------------------------------- solo tutoring_db (4)


@pytest.mark.django_db
def test_no_llama_a_otros_servicios_ni_devuelve_el_correo(
    client, sin_red, base_de_datos, estudiante
):
    tutora = persona("Valentina", promedio="5.00", total=1)
    PerfilTutor.objects.create(usuario=tutora, asignatura=base_de_datos, tarifa=5000)
    bloque(tutora, 1)
    evaluacion(tutora, base_de_datos, estudiante, dias=-3)

    for respuesta in (
        buscar(client, base_de_datos),
        perfil_de(client, tutora.usuario_id),
    ):
        assert respuesta.status_code == 200
        todas = list(claves(respuesta.json()))
        assert "usuario_id" in todas
        assert [c for c in todas if "email" in c or "correo" in c] == []


@pytest.mark.django_db
def test_la_busqueda_no_hace_una_consulta_por_tutor(client, base_de_datos):
    consulta = {"asignatura": str(base_de_datos.asignatura_id)}
    PerfilTutor.objects.create(usuario=persona("Uno"), asignatura=base_de_datos)
    con_uno = cantidad_de_consultas(client, TUTORES, **consulta)

    for nombre in ("Dos", "Tres", "Cuatro"):
        PerfilTutor.objects.create(usuario=persona(nombre), asignatura=base_de_datos)
    con_cuatro = cantidad_de_consultas(client, TUTORES, **consulta)

    assert con_cuatro == con_uno


@pytest.mark.django_db
def test_el_perfil_no_hace_una_consulta_por_fila(
    client, base_de_datos, redes, estudiante
):
    tutora = persona("Tutora")
    url = f"{TUTORES}/{tutora.usuario_id}"
    PerfilTutor.objects.create(usuario=tutora, asignatura=base_de_datos)
    bloque(tutora, 1)
    evaluacion(tutora, base_de_datos, estudiante, dias=-1)
    con_una_fila = cantidad_de_consultas(client, url)

    # Dos perfiles, tres bloques y tres evaluaciones: las mismas consultas.
    PerfilTutor.objects.create(usuario=tutora, asignatura=redes)
    for dia in (2, 3):
        bloque(tutora, dia)
    for dia in (-2, -3):
        evaluacion(tutora, redes, estudiante, dias=dia)
    con_varias_filas = cantidad_de_consultas(client, url)

    assert con_varias_filas == con_una_fila
