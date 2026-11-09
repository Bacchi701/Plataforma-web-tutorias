"""Pruebas de HU-33, parte 1: las rutas de administracion de Tutorias.

GET /admin/reservas y DELETE /admin/evaluaciones/<id> responden solo a un
token con es_admin (AD-09). Como test_bloques.py, no usan las claves de keys/:
generan su propio par RSA y firman los tokens con la privada, como Identidad.
Los datos van directo en la base: estas rutas no llaman a otros servicios, y
conftest.py hace fallar cualquier intento.
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from . import administracion
from .autenticacion import leer_clave
from .models import (
    AsignaturaRef,
    BloqueDisponibilidad,
    EstadoBloque,
    EstadoPago,
    EstadoReserva,
    Evaluacion,
    Modalidad,
    PerfilTutor,
    Reserva,
    UsuarioRef,
)

RESERVAS = "/api/tutoring/v1/admin/reservas"
EVALUACIONES = "/api/tutoring/v1/admin/evaluaciones"
TUTORES = "/api/tutoring/v1/tutores"
# La cuenta de ejemplo del administrador. No tiene fila en usuario_ref.
ID_ADMIN = uuid.UUID("10000000-0000-4000-8000-000000000008")
NOTA = "Me cuesta la tercera forma normal."
LUGAR = "https://meet.example.com/tutoria-admin"
NO_ES_ADMINISTRADOR = {
    "codigo": "no_es_administrador",
    "mensaje": "Esta sección es solo para administradores.",
    "detalles": None,
}


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


def firmar(clave, usuario_id, es_admin):
    """Token con las reclamaciones que pone Identidad (cuentas/tokens.py)."""
    ahora = timezone.now()
    reclamaciones = {
        "sub": str(usuario_id),
        "es_admin": es_admin,
        "iat": int(ahora.timestamp()),
        "exp": int((ahora + timedelta(minutes=30)).timestamp()),
        "iss": "identity",
    }
    return jwt.encode(reclamaciones, clave, algorithm="RS256")


@pytest.fixture
def cabecera(clave_de_identidad):
    """Authorization: Bearer con un token de Identidad, con o sin es_admin."""

    def para(usuario_id, es_admin=False):
        token = firmar(clave_de_identidad, usuario_id, es_admin)
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    return para


@pytest.fixture
def admin(cabecera):
    """La cabecera del administrador de ejemplo: un token con es_admin."""
    return cabecera(ID_ADMIN, es_admin=True)


# ------------------------------------------------------------ datos de prueba


def utc(texto):
    """Un instante escrito como lo devuelve la API: 2026-09-21T21:00:00Z."""
    return datetime.fromisoformat(texto)


def persona(nombre, apellido, **campos):
    return UsuarioRef.objects.create(
        usuario_id=uuid.uuid4(), nombre=nombre, apellido=apellido, **campos
    )


def asignatura(sigla, nombre):
    return AsignaturaRef.objects.create(
        asignatura_id=uuid.uuid4(), sigla=sigla, nombre=nombre
    )


def bloque_de(tutor, inicio, estado=EstadoBloque.OCUPADO):
    """Bloque de una hora del tutor desde inicio, ya pasado.

    Dos bloques vigentes del mismo tutor no se pueden solapar
    (ex_bloque_sin_solape): cada reserva usa una hora distinta.
    """
    return BloqueDisponibilidad.objects.create(
        usuario=tutor,
        inicio_en=utc(inicio),
        fin_en=utc(inicio) + timedelta(hours=1),
        estado=estado,
    )


def evaluada(tutor, solicitante, materia, inicio, calificacion):
    """Reserva EVALUADA sobre un bloque pasado del tutor, con su evaluacion.

    Cumple ck_reserva_confirmada_completa: modalidad, lugar y confirmada_en.
    """
    bloque = bloque_de(tutor, inicio)
    reserva = Reserva.objects.create(
        bloque=bloque,
        solicitante_usuario=solicitante,
        asignatura=materia,
        estado=EstadoReserva.EVALUADA,
        modalidad=Modalidad.EN_LINEA,
        lugar_o_enlace=LUGAR,
        confirmada_en=bloque.inicio_en - timedelta(days=2),
        cerrada_en=bloque.fin_en + timedelta(days=1),
    )
    Evaluacion.objects.create(reserva=reserva, calificacion=calificacion)
    return reserva


@pytest.fixture
def datos(db):
    """Valentina, tutora con perfil activo, y cuatro reservas sobre sus bloques.

    - Base de Datos con Camila y Programacion con Diego: EVALUADAS, cada una
      con su evaluacion visible, de 5 y de 1. Por eso su reputacion es 3.00
      con 2. Cumplen ck_reserva_confirmada_completa (modalidad, lugar y
      confirmada_en).
    - Una CANCELADA por Camila y una SOLICITADA de Diego.

    Los bloques son de septiembre y octubre de 2026, ya pasados, y no se
    solapan. Camila y Diego no son la tutora (trg_reserva_no_auto). Sin el
    perfil activo de Valentina, GET /tutores/<id> responderia 404.
    """
    valentina = persona(
        "Valentina", "Soto", reputacion_promedio=Decimal("3.00"), reputacion_total=2
    )
    camila = persona("Camila", "Rojas")
    diego = persona("Diego", "Herrera")
    bdd = asignatura("BDD1101", "Base de Datos")
    pro = asignatura("PRO1101", "Programación de Algoritmos")
    PerfilTutor.objects.create(usuario=valentina, asignatura=bdd, tarifa=5000)

    base_de_datos = Reserva.objects.create(
        bloque=bloque_de(valentina, "2026-09-21T21:00:00Z"),
        solicitante_usuario=camila,
        asignatura=bdd,
        estado=EstadoReserva.EVALUADA,
        nota=NOTA,
        modalidad=Modalidad.EN_LINEA,
        lugar_o_enlace=LUGAR,
        monto=5000,
        estado_pago=EstadoPago.PAGADO,
        creada_en=utc("2026-09-18T14:00:00Z"),
        confirmada_en=utc("2026-09-18T20:00:00Z"),
        cerrada_en=utc("2026-09-22T13:00:00Z"),
    )
    nota_5 = Evaluacion.objects.create(
        reserva=base_de_datos,
        calificacion=5,
        comentario="Explicó la normalización con ejemplos claros.",
        creada_en=utc("2026-09-22T13:00:00Z"),
    )
    programacion = Reserva.objects.create(
        bloque=bloque_de(valentina, "2026-09-23T20:00:00Z"),
        solicitante_usuario=diego,
        asignatura=pro,
        estado=EstadoReserva.EVALUADA,
        nota=NOTA,
        modalidad=Modalidad.EN_LINEA,
        lugar_o_enlace=LUGAR,
        creada_en=utc("2026-09-21T23:00:00Z"),
        confirmada_en=utc("2026-09-22T12:00:00Z"),
        cerrada_en=utc("2026-09-24T12:00:00Z"),
    )
    nota_1 = Evaluacion.objects.create(
        reserva=programacion,
        calificacion=1,
        comentario="Comentario fuera de las normas de la comunidad.",
        creada_en=utc("2026-09-24T12:00:00Z"),
    )
    cancelada = Reserva.objects.create(
        bloque=bloque_de(valentina, "2026-09-28T18:00:00Z", EstadoBloque.LIBRE),
        solicitante_usuario=camila,
        asignatura=bdd,
        estado=EstadoReserva.CANCELADA,
        nota=NOTA,
        modalidad=Modalidad.EN_LINEA,
        lugar_o_enlace=LUGAR,
        monto=5000,
        estado_pago=EstadoPago.REEMBOLSADO,
        cancelada_por_usuario=camila,
        creada_en=utc("2026-09-25T14:00:00Z"),
        confirmada_en=utc("2026-09-25T18:00:00Z"),
        cerrada_en=utc("2026-09-27T10:00:00Z"),
    )
    solicitada = Reserva.objects.create(
        bloque=bloque_de(valentina, "2026-10-05T20:00:00Z", EstadoBloque.LIBRE),
        solicitante_usuario=diego,
        asignatura=bdd,
        estado=EstadoReserva.SOLICITADA,
        nota=NOTA,
        monto=5000,
        creada_en=utc("2026-09-29T18:00:00Z"),
    )
    return SimpleNamespace(
        valentina=valentina,
        camila=camila,
        diego=diego,
        bdd=bdd,
        base_de_datos=base_de_datos,
        programacion=programacion,
        cancelada=cancelada,
        solicitada=solicitada,
        nota_5=nota_5,
        nota_1=nota_1,
    )


# ------------------------------------------------------------ ayudantes


def retirar(client, cabecera_http, evaluacion_id):
    return client.delete(f"{EVALUACIONES}/{evaluacion_id}", **cabecera_http)


def reputacion(tutor):
    """(promedio, total) del tutor, leidos de usuario_ref."""
    tutor.refresh_from_db()
    return tutor.reputacion_promedio, tutor.reputacion_total


def perfil_publico(client, tutor):
    respuesta = client.get(f"{TUTORES}/{tutor.usuario_id}")
    assert respuesta.status_code == 200
    return respuesta.json()


def retiro(evaluacion):
    """(retirada_en, retirada_por_usuario_id) de la evaluacion, leidos de la base."""
    evaluacion.refresh_from_db()
    return evaluacion.retirada_en, evaluacion.retirada_por_usuario_id


def claves(valor):
    """Todas las claves de un JSON, a cualquier profundidad."""
    if isinstance(valor, dict):
        for clave, contenido in valor.items():
            yield clave
            yield from claves(contenido)
    elif isinstance(valor, list):
        for elemento in valor:
            yield from claves(elemento)


# ------------------------------------------------------------ criterio 1


@pytest.mark.django_db
def test_sin_token_las_dos_rutas_responden_401(client, datos):
    respuestas = [
        client.get(RESERVAS),
        client.delete(f"{EVALUACIONES}/{datos.nota_1.id}"),
    ]

    assert [r.status_code for r in respuestas] == [401, 401]
    assert [r.json()["codigo"] for r in respuestas] == ["not_authenticated"] * 2
    assert retiro(datos.nota_1) == (None, None)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "es_admin", [False, "true", 1], ids=["false", "texto-true", "numero-1"]
)
def test_un_token_sin_es_admin_responde_403_en_las_dos_rutas(
    client, cabecera, datos, es_admin
):
    """Criterio 1 (AD-09): la marca es la del token y solo vale un true de JSON."""
    de_camila = cabecera(datos.camila.usuario_id, es_admin=es_admin)

    respuestas = [
        client.get(RESERVAS, **de_camila),
        retirar(client, de_camila, datos.nota_1.id),
    ]

    assert [r.status_code for r in respuestas] == [403, 403]
    assert [r.json() for r in respuestas] == [NO_ES_ADMINISTRADOR] * 2
    assert retiro(datos.nota_1) == (None, None)
    assert reputacion(datos.valentina) == (Decimal("3.00"), 2)


# ------------------------------------------------------------ criterio 3


@pytest.mark.django_db
def test_trae_las_reservas_de_la_mas_nueva_a_la_mas_antigua(client, admin, datos):
    """Estado, tutor, solicitante, asignatura y fechas en UTC con Z."""
    respuesta = client.get(RESERVAS, **admin)

    assert respuesta.status_code == 200
    lista = respuesta.json()
    assert [r["id"] for r in lista] == [
        str(datos.solicitada.id),
        str(datos.cancelada.id),
        str(datos.programacion.id),
        str(datos.base_de_datos.id),
    ]
    assert [r["estado"] for r in lista] == [
        "SOLICITADA",
        "CANCELADA",
        "EVALUADA",
        "EVALUADA",
    ]
    assert lista[3] == {
        "id": str(datos.base_de_datos.id),
        "estado": "EVALUADA",
        "asignatura": {
            "asignatura_id": str(datos.bdd.asignatura_id),
            "sigla": "BDD1101",
            "nombre": "Base de Datos",
        },
        "tutor": {
            "usuario_id": str(datos.valentina.usuario_id),
            "nombre": "Valentina",
            "apellido": "Soto",
        },
        "solicitante": {
            "usuario_id": str(datos.camila.usuario_id),
            "nombre": "Camila",
            "apellido": "Rojas",
        },
        "bloque": {
            "id": str(datos.base_de_datos.bloque_id),
            "inicio_en": "2026-09-21T21:00:00Z",
            "fin_en": "2026-09-21T22:00:00Z",
        },
        "monto": 5000,
        "estado_pago": "PAGADO",
        "creada_en": "2026-09-18T14:00:00Z",
        "confirmada_en": "2026-09-18T20:00:00Z",
        "cerrada_en": "2026-09-22T13:00:00Z",
        "cancelada_por_usuario_id": None,
        "evaluacion": {
            "id": str(datos.nota_5.id),
            "calificacion": 5,
            "comentario": "Explicó la normalización con ejemplos claros.",
            "creada_en": "2026-09-22T13:00:00Z",
            "retirada_en": None,
        },
    }
    solicitada, cancelada = lista[0], lista[1]
    assert solicitada["solicitante"]["nombre"] == "Diego"
    assert solicitada["confirmada_en"] is None
    assert solicitada["cerrada_en"] is None
    assert solicitada["estado_pago"] is None
    assert solicitada["evaluacion"] is None
    assert cancelada["cancelada_por_usuario_id"] == str(datos.camila.usuario_id)
    assert cancelada["cerrada_en"] == "2026-09-27T10:00:00Z"
    assert cancelada["evaluacion"] is None


@pytest.mark.django_db
def test_estado_filtra_y_cada_evaluada_trae_su_evaluacion(client, admin, datos):
    """Una reserva EVALUADA trae su evaluacion, con id y retirada_en."""
    Evaluacion.objects.filter(pk=datos.nota_1.pk).update(
        retirada_en=utc("2026-09-25T09:00:00Z"), retirada_por_usuario_id=ID_ADMIN
    )

    evaluadas = client.get(RESERVAS, {"estado": "EVALUADA"}, **admin)
    canceladas = client.get(RESERVAS, {"estado": "CANCELADA"}, **admin)
    expiradas = client.get(RESERVAS, {"estado": "EXPIRADA"}, **admin)

    assert [r.status_code for r in (evaluadas, canceladas, expiradas)] == [200] * 3
    assert [r["id"] for r in evaluadas.json()] == [
        str(datos.programacion.id),
        str(datos.base_de_datos.id),
    ]
    assert [r["evaluacion"]["id"] for r in evaluadas.json()] == [
        str(datos.nota_1.id),
        str(datos.nota_5.id),
    ]
    assert [r["evaluacion"]["retirada_en"] for r in evaluadas.json()] == [
        "2026-09-25T09:00:00Z",
        None,
    ]
    assert [r["id"] for r in canceladas.json()] == [str(datos.cancelada.id)]
    assert expiradas.json() == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    "estado",
    ["evaluada", "PAGADO", "", "EVALUADA "],
    ids=["minusculas", "de_pago", "vacio", "con_espacio"],
)
def test_un_estado_invalido_responde_400(client, admin, estado):
    respuesta = client.get(RESERVAS, {"estado": estado}, **admin)

    assert respuesta.status_code == 400
    cuerpo = respuesta.json()
    assert cuerpo["codigo"] == "estado_invalido"
    assert cuerpo["detalles"] is None
    # El mensaje nombra los siete estados.
    assert [e for e in EstadoReserva.values if e not in cuerpo["mensaje"]] == []


@pytest.mark.django_db
def test_ninguna_respuesta_trae_correo_nota_ni_lugar(client, admin, datos):
    """RNF-07: el correo no esta en esta base; la nota y el lugar no se exponen."""
    for parametros in ({}, {"estado": "EVALUADA"}, {"estado": "CANCELADA"}):
        respuesta = client.get(RESERVAS, parametros, **admin)

        assert respuesta.status_code == 200
        assert respuesta.json() != []
        nombres = set(claves(respuesta.json()))
        assert nombres.isdisjoint({"email", "correo", "nota", "lugar_o_enlace"})
        assert NOTA.encode() not in respuesta.content
        assert LUGAR.encode() not in respuesta.content


@pytest.mark.django_db
def test_trae_hasta_el_tope_las_mas_nuevas(client, admin, datos, monkeypatch):
    """Hasta 100. Con el tope en 2, salen las dos mas nuevas."""
    assert administracion.MAXIMO_RESERVAS == 100
    monkeypatch.setattr(administracion, "MAXIMO_RESERVAS", 2)

    respuesta = client.get(RESERVAS, **admin)

    assert respuesta.status_code == 200
    assert [r["id"] for r in respuesta.json()] == [
        str(datos.solicitada.id),
        str(datos.cancelada.id),
    ]


def consultas_de_la_lista(client, admin):
    """(consultas a la base, reservas en la respuesta) de GET /admin/reservas."""
    with CaptureQueriesContext(connection) as consultas:
        respuesta = client.get(RESERVAS, **admin)
    assert respuesta.status_code == 200
    return len(consultas), len(respuesta.json())


@pytest.mark.django_db
def test_con_1_y_con_3_reservas_hace_las_mismas_consultas(client, admin):
    """Una sola consulta con select_related, sin una consulta por reserva."""
    tutora = persona("Valentina", "Soto")
    bdd = asignatura("BDD1101", "Base de Datos")
    evaluada(tutora, persona("Camila", "Rojas"), bdd, "2026-09-21T21:00:00Z", 5)
    consultas_con_una, con_una = consultas_de_la_lista(client, admin)

    evaluada(tutora, persona("Diego", "Herrera"), bdd, "2026-09-23T20:00:00Z", 1)
    Reserva.objects.create(
        bloque=bloque_de(tutora, "2026-10-05T20:00:00Z", EstadoBloque.LIBRE),
        solicitante_usuario=persona("Fernanda", "Castro"),
        asignatura=bdd,
    )
    consultas_con_tres, con_tres = consultas_de_la_lista(client, admin)

    assert (con_una, con_tres) == (1, 3)
    assert consultas_con_tres == consultas_con_una


# ------------------------------------------------------------ criterio 4


@pytest.mark.django_db
def test_retirar_la_de_1_deja_la_reputacion_en_5_y_la_saca_del_perfil(
    client, admin, datos
):
    """CA7: deja de contar para la reputacion; la reserva sigue EVALUADA."""
    assert reputacion(datos.valentina) == (Decimal("3.00"), 2)
    antes = perfil_publico(client, datos.valentina)
    assert [e["calificacion"] for e in antes["evaluaciones"]] == [1, 5]
    desde = timezone.now()

    respuesta = retirar(client, admin, datos.nota_1.id)

    assert respuesta.status_code == 204
    assert respuesta.content == b""
    assert reputacion(datos.valentina) == (Decimal("5.00"), 1)
    retirada_en, retirada_por = retiro(datos.nota_1)
    assert desde <= retirada_en <= timezone.now()
    assert retirada_por == ID_ADMIN
    # No se borra: la fila sigue, con su nota.
    assert Evaluacion.objects.get(pk=datos.nota_1.pk).calificacion == 1
    datos.programacion.refresh_from_db()
    assert datos.programacion.estado == EstadoReserva.EVALUADA
    assert datos.programacion.cerrada_en == utc("2026-09-24T12:00:00Z")
    assert retiro(datos.nota_5) == (None, None)

    despues = perfil_publico(client, datos.valentina)
    assert despues["reputacion"] == {"promedio": 5.0, "total": 1}
    assert [e["calificacion"] for e in despues["evaluaciones"]] == [5]


@pytest.mark.django_db
def test_retirarla_otra_vez_responde_409_y_no_cambia_el_retiro(
    client, cabecera, admin, datos
):
    assert retirar(client, admin, datos.nota_1.id).status_code == 204
    primer_retiro = retiro(datos.nota_1)
    otro_admin = cabecera(uuid.uuid4(), es_admin=True)

    respuesta = retirar(client, otro_admin, datos.nota_1.id)

    assert respuesta.status_code == 409
    assert respuesta.json() == {
        "codigo": "evaluacion_ya_retirada",
        "mensaje": "Esa evaluación ya estaba retirada.",
        "detalles": None,
    }
    assert retiro(datos.nota_1) == primer_retiro
    assert reputacion(datos.valentina) == (Decimal("5.00"), 1)


@pytest.mark.django_db
def test_una_evaluacion_que_no_existe_responde_404(client, admin, datos):
    # El id de una reserva tampoco es el de una evaluacion.
    for desconocido in (uuid.uuid4(), datos.base_de_datos.id):
        respuesta = retirar(client, admin, desconocido)

        assert respuesta.status_code == 404
        assert respuesta.json() == {
            "codigo": "evaluacion_no_encontrada",
            "mensaje": "No existe una evaluación con ese identificador.",
            "detalles": None,
        }
    assert not Evaluacion.objects.filter(retirada_en__isnull=False).exists()
    assert reputacion(datos.valentina) == (Decimal("3.00"), 2)


@pytest.mark.django_db
def test_retirar_la_unica_visible_deja_la_reputacion_en_cero(client, admin, datos):
    assert retirar(client, admin, datos.nota_1.id).status_code == 204
    assert reputacion(datos.valentina) == (Decimal("5.00"), 1)

    respuesta = retirar(client, admin, datos.nota_5.id)

    assert respuesta.status_code == 204
    assert reputacion(datos.valentina) == (Decimal("0.00"), 0)
    perfil = perfil_publico(client, datos.valentina)
    assert perfil["reputacion"] == {"promedio": 0.0, "total": 0}
    assert perfil["evaluaciones"] == []
    for reserva in (datos.base_de_datos, datos.programacion):
        reserva.refresh_from_db()
        assert reserva.estado == EstadoReserva.EVALUADA


@pytest.mark.django_db
def test_un_administrador_sin_fila_en_usuario_ref_puede_retirar(client, admin, datos):
    """retirada_por_usuario_id es una referencia logica, sin clave foranea."""
    assert not UsuarioRef.objects.filter(pk=ID_ADMIN).exists()

    respuesta = retirar(client, admin, datos.nota_5.id)

    assert respuesta.status_code == 204
    assert retiro(datos.nota_5)[1] == ID_ADMIN
    assert not UsuarioRef.objects.filter(pk=ID_ADMIN).exists()
    assert reputacion(datos.valentina) == (Decimal("1.00"), 1)
