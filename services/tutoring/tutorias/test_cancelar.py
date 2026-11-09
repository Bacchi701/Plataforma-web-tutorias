"""Pruebas de HU-28: retirar una solicitud o cancelar una tutoria.

Corren contra PostgreSQL, como test_confirmar_rechazar.py: el bloqueo con
SELECT ... FOR UPDATE y la regla ux_reserva_bloque_ocupado solo existen ahi.
Firman los tokens con su propio par RSA, como Identidad. Las solicitudes y las
reservas se crean directo en la base, y tambien los bloques que ya empezaron,
porque la API no los acepta. pedir_aviso se reemplaza en tutorias.reservas,
donde se usa; donde una prueba usa el pedir_aviso de verdad, Identidad la hace
IdentidadFalsa, de test_reservas.py.

Parte B (criterio 3): pedir_reembolso se reemplaza en tutorias.reservas en
todas las pruebas (fixture reembolso, autouse): ninguna llama a Pagos.
"""

import threading
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest import mock

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.db import connection
from django.test import Client
from django.utils import timezone

from . import llamadas, reservas
from .autenticacion import leer_clave
from .bloques import instante_json
from .internas import instante_preciso
from .models import (
    ESTADOS_QUE_OCUPAN,
    AsignaturaRef,
    BloqueDisponibilidad,
    EstadoBloque,
    EstadoPago,
    EstadoReserva,
    Modalidad,
    PerfilTutor,
    Reserva,
    UsuarioRef,
)
from .test_reservas import IdentidadFalsa

URL = "/api/tutoring/v1/reservas"
TUTORES = "/api/tutoring/v1/tutores"
# Los bloques futuros se cuentan en horas desde manana a mediodia (UTC).
MANANA = (timezone.now() + timedelta(days=1)).replace(
    hour=12, minute=0, second=0, microsecond=0
)
ENLACE = "https://meet.google.com/abc-defg-hij"
# Segundos que espera la prueba de concurrencia a cada hilo.
ESPERA = 10

YA_EMPEZO = "La tutoría ya empezó: ya no se puede cancelar ni retirar."
SOLO_RETIRA = (
    "Una solicitud pendiente solo la retira quien la pidió. Como tutor, puedes "
    "rechazarla."
)
NO_ENCONTRADA = "No encontramos esa tutoría."


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
            "sub": str(getattr(usuario, "usuario_id", usuario)),
            "es_admin": False,
            "iat": int(ahora.timestamp()),
            "exp": int((ahora + timedelta(minutes=30)).timestamp()),
            "iss": "identity",
        }
        token = jwt.encode(reclamaciones, clave_de_identidad, algorithm="RS256")
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    return para


# ------------------------------------------------------------ otros servicios


@pytest.fixture
def aviso(monkeypatch):
    """pedir_aviso reemplazado donde se usa: en tutorias.reservas."""
    falso = mock.Mock(return_value=True)
    monkeypatch.setattr(reservas, "pedir_aviso", falso)
    return falso


@pytest.fixture(autouse=True)
def reembolso(monkeypatch):
    """pedir_reembolso reemplazado donde se usa, en todas las pruebas (parte B).

    Al cancelar una reserva CONFIRMADA con monto, la vista pide el reembolso a
    Pagos despues del commit: sin este reemplazo, las pruebas que ejecutan los
    on_commit lo pedirian de verdad. Responde True, como con un 200 de Pagos.
    """
    falso = mock.Mock(return_value=True)
    monkeypatch.setattr(reservas, "pedir_reembolso", falso)
    return falso


@pytest.fixture
def identidad(monkeypatch, settings):
    """Identidad, para las pruebas con el pedir_aviso de verdad (HU-16)."""
    settings.URL_IDENTIDAD = "http://identity:8000"
    falsa = IdentidadFalsa()
    monkeypatch.setattr(llamadas, "abrir", falsa.abrir)
    return falsa


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
def tutora(asignatura):
    """Valentina, tutora activa de Base de Datos a $5.000."""
    valentina = persona("Valentina", "Soto")
    PerfilTutor.objects.create(usuario=valentina, asignatura=asignatura, tarifa=5000)
    return valentina


def bloque(tutor, desde, hasta, **campos):
    """Bloque desde MANANA + desde horas hasta MANANA + hasta horas."""
    return BloqueDisponibilidad.objects.create(
        usuario=tutor,
        inicio_en=MANANA + timedelta(hours=desde),
        fin_en=MANANA + timedelta(hours=hasta),
        **campos,
    )


def empezado(tutor, desde=-30, hasta=30):
    """Bloque LIBRE que ya empezo: desde y hasta, en minutos desde ahora.

    Por defecto, en curso. Va directo a la base: la API no lo acepta.
    """
    ahora = timezone.now()
    return BloqueDisponibilidad.objects.create(
        usuario=tutor,
        inicio_en=ahora + timedelta(minutes=desde),
        fin_en=ahora + timedelta(minutes=hasta),
    )


@pytest.fixture
def libre(tutora):
    """Un bloque LIBRE y futuro de la tutora: manana de 13:00 a 14:00 (UTC)."""
    return bloque(tutora, 1, 2)


def reserva(
    en_bloque, solicitante, asignatura, estado=EstadoReserva.SOLICITADA, **campos
):
    """Reserva creada directo en la base, que cumple las reglas del modelo.

    Por defecto, con el monto de la tarifa de la tutora ($5.000).
    """
    valores = {"monto": Decimal("5000")}
    if estado in ESTADOS_QUE_OCUPAN:
        # RN-07: confirmada, realizada o evaluada, tiene modalidad y lugar.
        valores.update(
            modalidad=Modalidad.EN_LINEA,
            lugar_o_enlace="https://meet.example.com/prueba",
            confirmada_en=timezone.now(),
        )
    elif estado != EstadoReserva.SOLICITADA:
        valores["cerrada_en"] = timezone.now() - timedelta(hours=1)
    valores.update(campos)
    return Reserva.objects.create(
        bloque=en_bloque,
        solicitante_usuario=solicitante,
        asignatura=asignatura,
        estado=estado,
        **valores,
    )


def ocupada(en_bloque, solicitante, asignatura, estado=EstadoReserva.CONFIRMADA):
    """Una reserva que ocupa el bloque, con el bloque OCUPADO, como lo deja HU-22."""
    en_bloque.estado = EstadoBloque.OCUPADO
    en_bloque.save(update_fields=["estado", "actualizado_en"])
    return reserva(en_bloque, solicitante, asignatura, estado)


def en_utc(horas):
    """MANANA + horas, como lo escribe la API: en UTC, con Z y sin fraccion."""
    return (MANANA + timedelta(hours=horas)).strftime("%Y-%m-%dT%H:%M:%SZ")


def cancelar(client, encabezado, reserva_id):
    """Sin cuerpo."""
    return client.post(f"{URL}/{reserva_id}/cancelar", **encabezado)


def confirmar(client, encabezado, reserva_id):
    return client.post(
        f"{URL}/{reserva_id}/confirmar",
        {"modalidad": "EN_LINEA", "lugar_o_enlace": ENLACE},
        content_type="application/json",
        **encabezado,
    )


def error(respuesta):
    return respuesta.status_code, respuesta.json()["codigo"]


def como_esta(una_reserva):
    """Lo que una cancelacion rechazada no puede cambiar, leido de la base."""
    una_reserva.refresh_from_db()
    return (
        una_reserva.estado,
        una_reserva.cerrada_en,
        una_reserva.cancelada_por_usuario_id,
        una_reserva.confirmada_en,
    )


def como_esta_el_bloque(un_bloque):
    """El estado del bloque y su ultimo cambio, leidos de la base."""
    un_bloque.refresh_from_db()
    return un_bloque.estado, un_bloque.actualizado_en


def pedidos(aviso):
    """(destinatario, plantilla, id de la reserva) de cada aviso pedido, en orden."""
    return [
        (llamada.args[0], llamada.args[1], llamada.args[2].id)
        for llamada in aviso.call_args_list
    ]


def lineas_del_log(caplog):
    """Los mensajes que dejo llamadas.py en el log."""
    return [
        registro.getMessage()
        for registro in caplog.records
        if registro.name == llamadas.logger.name
    ]


# ------------------------------------------------------------ criterio 1


@pytest.mark.django_db
def test_el_estudiante_retira_su_solicitud_y_el_bloque_sigue_libre(
    client, cabecera, tutora, libre, asignatura
):
    camila = persona("Camila", "Rojas")
    solicitud = reserva(
        libre, camila, asignatura, nota="Me cuesta la tercera forma normal."
    )
    de_diego = reserva(libre, persona("Diego", "Herrera"), asignatura)
    antes = timezone.now()

    respuesta = cancelar(client, cabecera(camila), solicitud.id)

    assert respuesta.status_code == 200
    solicitud.refresh_from_db()
    # El mismo formato de HU-21, visto por el estudiante.
    assert respuesta.json() == {
        "id": str(solicitud.id),
        "estado": "CANCELADA",
        "nota": "Me cuesta la tercera forma normal.",
        "modalidad": None,
        "lugar_o_enlace": None,
        "monto": 5000,
        "estado_pago": None,
        "creada_en": instante_json(solicitud.creada_en),
        "confirmada_en": None,
        "cerrada_en": instante_json(solicitud.cerrada_en),
        "bloque": {"id": str(libre.id), "inicio_en": en_utc(1), "fin_en": en_utc(2)},
        "asignatura": {
            "asignatura_id": str(asignatura.asignatura_id),
            "sigla": "BDD1101",
            "nombre": "Base de Datos",
        },
        "tutor": {
            "usuario_id": str(tutora.usuario_id),
            "nombre": "Valentina",
            "apellido": "Soto",
        },
        "solicitante": {
            "usuario_id": str(camila.usuario_id),
            "nombre": "Camila",
            "apellido": "Rojas",
        },
        "rol": "estudiante",
    }
    assert solicitud.estado == EstadoReserva.CANCELADA
    assert antes <= solicitud.cerrada_en <= timezone.now()
    assert solicitud.cancelada_por_usuario_id == camila.usuario_id
    # RN-04: el bloque nunca estuvo ocupado. Sigue LIBRE y en el perfil publico.
    libre.refresh_from_db()
    assert libre.estado == EstadoBloque.LIBRE
    publico = client.get(f"{TUTORES}/{tutora.usuario_id}").json()
    assert [b["id"] for b in publico["bloques"]] == [str(libre.id)]
    # La otra solicitud del bloque, de otro estudiante, no cambia.
    assert como_esta(de_diego) == (EstadoReserva.SOLICITADA, None, None, None)


@pytest.mark.django_db
def test_el_cuerpo_se_ignora(client, cabecera, tutora, libre, asignatura):
    camila = persona("Camila", "Rojas")
    solicitud = reserva(libre, camila, asignatura)

    respuesta = client.post(
        f"{URL}/{solicitud.id}/cancelar",
        {"estado": "CONFIRMADA", "cancelada_por_usuario_id": str(tutora.usuario_id)},
        content_type="application/json",
        **cabecera(camila),
    )

    assert respuesta.status_code == 200
    solicitud.refresh_from_db()
    assert (solicitud.estado, solicitud.cancelada_por_usuario_id) == (
        EstadoReserva.CANCELADA,
        camila.usuario_id,
    )


# ------------------------------------------------------------ criterio 2 (CA9)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "quien", ["estudiante", "tutor"], ids=["por_el_estudiante", "por_el_tutor"]
)
def test_cancelar_una_confirmada_deja_el_bloque_libre(
    client, cabecera, tutora, libre, asignatura, quien
):
    camila = persona("Camila", "Rojas")
    tutoria = ocupada(libre, camila, asignatura)
    confirmacion = (tutoria.modalidad, tutoria.lugar_o_enlace, tutoria.confirmada_en)
    cancela = camila if quien == "estudiante" else tutora
    antes = timezone.now()

    respuesta = cancelar(client, cabecera(cancela), tutoria.id)

    assert respuesta.status_code == 200
    tutoria.refresh_from_db()
    cuerpo = respuesta.json()
    assert (cuerpo["id"], cuerpo["estado"], cuerpo["rol"]) == (
        str(tutoria.id),
        "CANCELADA",
        quien,
    )
    assert cuerpo["cerrada_en"] == instante_json(tutoria.cerrada_en)
    assert tutoria.estado == EstadoReserva.CANCELADA
    assert antes <= tutoria.cerrada_en <= timezone.now()
    # Queda registrado quien cancelo.
    assert tutoria.cancelada_por_usuario_id == cancela.usuario_id
    # Lo que fijo el tutor al confirmar no cambia.
    despues = (tutoria.modalidad, tutoria.lugar_o_enlace, tutoria.confirmada_en)
    assert despues == confirmacion
    libre.refresh_from_db()
    assert libre.estado == EstadoBloque.LIBRE
    # El horario vuelve a salir entre los disponibles del perfil publico...
    publico = client.get(f"{TUTORES}/{tutora.usuario_id}").json()
    assert [b["id"] for b in publico["bloques"]] == [str(libre.id)]
    # ... y otra solicitud del mismo bloque se puede confirmar: la reserva
    # CANCELADA ya no ocupa el bloque (ux_reserva_bloque_ocupado).
    nueva = reserva(libre, persona("Diego", "Herrera"), asignatura)
    assert confirmar(client, cabecera(tutora), nueva.id).status_code == 200
    nueva.refresh_from_db()
    libre.refresh_from_db()
    assert (nueva.estado, libre.estado) == (
        EstadoReserva.CONFIRMADA,
        EstadoBloque.OCUPADO,
    )
    tutoria.refresh_from_db()
    assert tutoria.estado == EstadoReserva.CANCELADA


# ------------------------------------------------------------ criterio 4

CASOS_YA_EMPEZADOS = {
    "retira_el_estudiante": (EstadoReserva.SOLICITADA, "estudiante"),
    "cancela_el_estudiante": (EstadoReserva.CONFIRMADA, "estudiante"),
    "cancela_el_tutor": (EstadoReserva.CONFIRMADA, "tutor"),
}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "desde, hasta", [(-30, 30), (-120, -60)], ids=["en_curso", "ya_termino"]
)
@pytest.mark.parametrize(
    "estado, quien", list(CASOS_YA_EMPEZADOS.values()), ids=list(CASOS_YA_EMPEZADOS)
)
def test_con_el_bloque_ya_empezado_responde_400(
    client, cabecera, tutora, asignatura, estado, quien, desde, hasta
):
    """Tambien una solicitud que el programador todavia no expira."""
    camila = persona("Camila", "Rojas")
    del_bloque = empezado(tutora, desde, hasta)
    if estado == EstadoReserva.CONFIRMADA:
        una_reserva = ocupada(del_bloque, camila, asignatura)
    else:
        una_reserva = reserva(del_bloque, camila, asignatura)
    antes = como_esta(una_reserva)
    bloque_antes = como_esta_el_bloque(del_bloque)
    pide = camila if quien == "estudiante" else tutora

    respuesta = cancelar(client, cabecera(pide), una_reserva.id)

    assert error(respuesta) == (400, "bloque_en_el_pasado")
    assert respuesta.json()["mensaje"] == YA_EMPEZO
    # Nada cambia: ni la reserva ni el bloque.
    assert como_esta(una_reserva) == antes
    assert como_esta_el_bloque(del_bloque) == bloque_antes


NO_CANCELABLES = {
    EstadoReserva.RECHAZADA: "Esta reserva ya no se puede cancelar: está rechazada.",
    EstadoReserva.EXPIRADA: "Esta reserva ya no se puede cancelar: está expirada.",
    EstadoReserva.CANCELADA: "Esta reserva ya no se puede cancelar: está cancelada.",
    EstadoReserva.REALIZADA: "Esta reserva ya no se puede cancelar: está realizada.",
    EstadoReserva.EVALUADA: "Esta reserva ya no se puede cancelar: está evaluada.",
}


@pytest.mark.django_db
@pytest.mark.parametrize("quien", ["estudiante", "tutor"])
@pytest.mark.parametrize(
    "estado, mensaje",
    list(NO_CANCELABLES.items()),
    ids=[estado.lower() for estado in NO_CANCELABLES],
)
def test_una_reserva_en_un_estado_terminal_responde_409(
    client, cabecera, tutora, asignatura, estado, mensaje, quien
):
    """El estado se revisa antes que la hora: 409 aunque el bloque ya termino."""
    camila = persona("Camila", "Rojas")
    del_bloque = empezado(tutora, -120, -60)
    if estado in ESTADOS_QUE_OCUPAN:
        una_reserva = ocupada(del_bloque, camila, asignatura, estado)
    else:
        una_reserva = reserva(del_bloque, camila, asignatura, estado)
    antes = como_esta(una_reserva)
    bloque_antes = como_esta_el_bloque(del_bloque)
    pide = camila if quien == "estudiante" else tutora

    respuesta = cancelar(client, cabecera(pide), una_reserva.id)

    assert error(respuesta) == (409, "reserva_no_cancelable")
    assert respuesta.json()["mensaje"] == mensaje
    # Nada cambia: ni la reserva ni el bloque.
    assert como_esta(una_reserva) == antes
    assert como_esta_el_bloque(del_bloque) == bloque_antes


@pytest.mark.django_db
def test_cancelar_dos_veces_responde_409(client, cabecera, tutora, libre, asignatura):
    camila = persona("Camila", "Rojas")
    tutoria = ocupada(libre, camila, asignatura)
    encabezado = cabecera(camila)

    primera = cancelar(client, encabezado, tutoria.id)
    despues_de_la_primera = como_esta(tutoria)
    segunda = cancelar(client, encabezado, tutoria.id)

    assert primera.status_code == 200
    assert error(segunda) == (409, "reserva_no_cancelable")
    assert segunda.json()["mensaje"] == NO_CANCELABLES[EstadoReserva.CANCELADA]
    assert como_esta(tutoria) == despues_de_la_primera


@pytest.mark.django_db
@pytest.mark.parametrize(
    "ya_empezo", [False, True], ids=["bloque_futuro", "bloque_que_ya_empezo"]
)
def test_el_tutor_no_retira_una_solicitud(
    client, cabecera, tutora, libre, asignatura, ya_empezo
):
    """RN-04: retirar es del estudiante; el tutor la rechaza (HU-22).

    Se revisa antes que la hora: tambien 409 si el bloque ya empezo.
    """
    del_bloque = empezado(tutora) if ya_empezo else libre
    solicitud = reserva(del_bloque, persona("Camila", "Rojas"), asignatura)
    bloque_antes = como_esta_el_bloque(del_bloque)

    respuesta = cancelar(client, cabecera(tutora), solicitud.id)

    assert error(respuesta) == (409, "reserva_no_cancelable")
    assert respuesta.json()["mensaje"] == SOLO_RETIRA
    assert como_esta(solicitud) == (EstadoReserva.SOLICITADA, None, None, None)
    assert como_esta_el_bloque(del_bloque) == bloque_antes


# ------------------------------------------------------------ quien puede


@pytest.mark.django_db
def test_otro_usuario_o_una_reserva_que_no_existe_responde_404(
    client, cabecera, tutora, libre, asignatura
):
    camila = persona("Camila", "Rojas")
    tutoria = ocupada(libre, camila, asignatura)
    antes = como_esta(tutoria)
    bloque_antes = como_esta_el_bloque(libre)
    matias = persona("Matías", "Fuentes")
    PerfilTutor.objects.create(usuario=matias, asignatura=asignatura, tarifa=3000)

    respuestas = [
        # Otro estudiante.
        cancelar(client, cabecera(persona("Diego", "Herrera")), tutoria.id),
        # Otro tutor.
        cancelar(client, cabecera(matias), tutoria.id),
        # Alguien que todavia no tiene copia en Tutorias.
        cancelar(client, cabecera(uuid.uuid4()), tutoria.id),
        # Una reserva que no existe responde lo mismo.
        cancelar(client, cabecera(camila), uuid.uuid4()),
    ]

    for respuesta in respuestas:
        assert error(respuesta) == (404, "reserva_no_encontrada")
        assert respuesta.json()["mensaje"] == NO_ENCONTRADA
    assert como_esta(tutoria) == antes
    assert como_esta_el_bloque(libre) == bloque_antes
    assert bloque_antes[0] == EstadoBloque.OCUPADO


@pytest.mark.django_db
def test_sin_token_responde_401(client, libre, asignatura):
    solicitud = reserva(libre, persona("Camila", "Rojas"), asignatura)

    respuesta = cancelar(client, {}, solicitud.id)

    assert error(respuesta) == (401, "not_authenticated")
    assert como_esta(solicitud) == (EstadoReserva.SOLICITADA, None, None, None)


# ------------------------------------------------------------ el aviso (HU-16)


@pytest.mark.django_db
def test_retirar_avisa_al_tutor(
    client,
    cabecera,
    aviso,
    django_capture_on_commit_callbacks,
    tutora,
    libre,
    asignatura,
):
    camila = persona("Camila", "Rojas")
    solicitud = reserva(libre, camila, asignatura)

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        respuesta = cancelar(client, cabecera(camila), solicitud.id)

    assert respuesta.status_code == 200
    assert len(callbacks) == 1
    assert pedidos(aviso) == [(tutora.usuario_id, "RESERVA_CANCELADA", solicitud.id)]
    # El aviso lleva la reserva ya cancelada.
    assert aviso.call_args.args[2].estado == EstadoReserva.CANCELADA


@pytest.mark.django_db
@pytest.mark.parametrize(
    "quien", ["estudiante", "tutor"], ids=["cancela_el_estudiante", "cancela_el_tutor"]
)
def test_cancelar_una_confirmada_avisa_a_la_otra_parte(
    client,
    cabecera,
    aviso,
    django_capture_on_commit_callbacks,
    tutora,
    libre,
    asignatura,
    quien,
):
    camila = persona("Camila", "Rojas")
    tutoria = ocupada(libre, camila, asignatura)
    cancela, avisado = (camila, tutora) if quien == "estudiante" else (tutora, camila)

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        respuesta = cancelar(client, cabecera(cancela), tutoria.id)

    assert respuesta.status_code == 200
    # El reembolso (parte B: la tutoria tiene monto) y el aviso.
    assert len(callbacks) == 2
    assert pedidos(aviso) == [(avisado.usuario_id, "RESERVA_CANCELADA", tutoria.id)]
    assert aviso.call_args.args[2].estado == EstadoReserva.CANCELADA


@pytest.mark.django_db
def test_el_aviso_sale_despues_del_commit(
    client,
    cabecera,
    aviso,
    django_capture_on_commit_callbacks,
    tutora,
    libre,
    asignatura,
):
    camila = persona("Camila", "Rojas")
    solicitud = reserva(libre, camila, asignatura)

    with django_capture_on_commit_callbacks() as callbacks:
        respuesta = cancelar(client, cabecera(camila), solicitud.id)

    assert respuesta.status_code == 200
    # Durante la peticion no se llamo: quedo pedido para despues del commit.
    assert not aviso.called
    assert len(callbacks) == 1
    callbacks[0]()
    assert pedidos(aviso) == [(tutora.usuario_id, "RESERVA_CANCELADA", solicitud.id)]


@pytest.mark.django_db
def test_si_la_cancelacion_falla_no_se_avisa(
    client,
    cabecera,
    aviso,
    django_capture_on_commit_callbacks,
    tutora,
    libre,
    asignatura,
):
    camila = persona("Camila", "Rojas")
    pendiente = reserva(libre, camila, asignatura)
    rechazada = reserva(
        bloque(tutora, 3, 4), camila, asignatura, EstadoReserva.RECHAZADA
    )
    en_curso = reserva(empezado(tutora), camila, asignatura)

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        respuestas = [
            cancelar(client, cabecera(camila), en_curso.id),
            cancelar(client, cabecera(persona("Diego", "Herrera")), pendiente.id),
            cancelar(client, cabecera(camila), rechazada.id),
            cancelar(client, cabecera(tutora), pendiente.id),
        ]

    assert [error(r) for r in respuestas] == [
        (400, "bloque_en_el_pasado"),
        (404, "reserva_no_encontrada"),
        (409, "reserva_no_cancelable"),
        (409, "reserva_no_cancelable"),
    ]
    assert callbacks == []
    assert not aviso.called


CASOS_DEL_AVISO = {
    "retira_el_estudiante": (EstadoReserva.SOLICITADA, "estudiante"),
    "cancela_el_estudiante": (EstadoReserva.CONFIRMADA, "estudiante"),
    "cancela_el_tutor": (EstadoReserva.CONFIRMADA, "tutor"),
}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "estado, quien", list(CASOS_DEL_AVISO.values()), ids=list(CASOS_DEL_AVISO)
)
def test_el_aviso_va_a_la_otra_parte_y_nombra_a_quien_cancelo(
    client,
    cabecera,
    identidad,
    django_capture_on_commit_callbacks,
    tutora,
    libre,
    asignatura,
    estado,
    quien,
):
    """Con pedir_aviso de verdad: el cuerpo que recibe Identidad (HU-16)."""
    camila = persona("Camila", "Rojas")
    if estado == EstadoReserva.CONFIRMADA:
        una_reserva = ocupada(libre, camila, asignatura)
    else:
        una_reserva = reserva(libre, camila, asignatura)
    cancela, avisado = (camila, tutora) if quien == "estudiante" else (tutora, camila)

    with django_capture_on_commit_callbacks(execute=True):
        respuesta = cancelar(client, cabecera(cancela), una_reserva.id)

    assert respuesta.status_code == 200
    [cuerpo] = identidad.avisos()
    assert (cuerpo["usuario_id"], cuerpo["plantilla"], cuerpo["referencia_id"]) == (
        str(avisado.usuario_id),
        "RESERVA_CANCELADA",
        str(una_reserva.id),
    )
    # Para quien recibe el aviso, la otra persona es quien cancelo.
    assert cuerpo["datos"]["otra_persona"] == {
        "nombre": cancela.nombre,
        "apellido": cancela.apellido,
    }
    assert (cuerpo["datos"]["inicio_en"], cuerpo["datos"]["fin_en"]) == (
        en_utc(1),
        en_utc(2),
    )


@pytest.mark.django_db
def test_si_el_aviso_no_sale_la_cancelacion_queda_igual(
    client,
    cabecera,
    identidad,
    django_capture_on_commit_callbacks,
    caplog,
    tutora,
    libre,
    asignatura,
):
    tutoria = ocupada(libre, persona("Camila", "Rojas"), asignatura)
    identidad.caida = True

    with django_capture_on_commit_callbacks(execute=True):
        respuesta = cancelar(client, cabecera(tutora), tutoria.id)

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "CANCELADA"
    tutoria.refresh_from_db()
    libre.refresh_from_db()
    assert (tutoria.estado, libre.estado) == (
        EstadoReserva.CANCELADA,
        EstadoBloque.LIBRE,
    )
    esperada = f"No salió el aviso RESERVA_CANCELADA de la reserva {tutoria.id}"
    assert any(linea.startswith(esperada) for linea in lineas_del_log(caplog))


# ------------------------------------------------------------ concurrencia


@pytest.mark.django_db(transaction=True)
def test_cancelar_y_confirmar_a_la_vez_la_misma_solicitud(
    cabecera, aviso, tutora, libre, asignatura
):
    """El estudiante retira su solicitud mientras el tutor la confirma.

    Dos hilos, cada uno con su conexion. Con transaction=True los datos quedan
    guardados de verdad, para que los vean las conexiones de los hilos, y los
    on_commit se ejecutan: por eso pedir_aviso va reemplazado (fixture aviso).
    Da lo mismo cual llegue primero: si gana la confirmacion, el estudiante
    cancela una reserva CONFIRMADA; si gana la cancelacion, la confirmacion
    responde 409. Al final la reserva queda CANCELADA y el bloque LIBRE.
    """
    camila = persona("Camila", "Rojas")
    solicitud = reserva(libre, camila, asignatura)
    del_estudiante = cabecera(camila)
    del_tutor = cabecera(tutora)
    barrera = threading.Barrier(2, timeout=ESPERA)
    resultados = []

    def en_un_hilo(nombre, accion, encabezado):
        try:
            cliente = Client()
            # Los dos esperan aqui, para que los POST de verdad se crucen.
            barrera.wait()
            resultados.append((nombre, accion(cliente, encabezado, solicitud.id)))
        except Exception as falla:
            resultados.append((nombre, falla))
        finally:
            connection.close()

    acciones = [
        ("cancelar", cancelar, del_estudiante),
        ("confirmar", confirmar, del_tutor),
    ]
    hilos = [threading.Thread(target=en_un_hilo, args=a) for a in acciones]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=3 * ESPERA)

    assert not any(hilo.is_alive() for hilo in hilos)
    respuestas = dict(resultados)
    assert sorted(respuestas) == ["cancelar", "confirmar"], resultados
    assert not any(isinstance(r, Exception) for r in respuestas.values()), resultados
    cancelacion, confirmacion = respuestas["cancelar"], respuestas["confirmar"]
    assert cancelacion.status_code == 200
    assert cancelacion.json()["estado"] == "CANCELADA"
    assert confirmacion.status_code in (200, 409)
    solicitud.refresh_from_db()
    assert solicitud.estado == EstadoReserva.CANCELADA
    assert solicitud.cancelada_por_usuario_id == camila.usuario_id
    libre.refresh_from_db()
    assert libre.estado == EstadoBloque.LIBRE
    confirmadas = Reserva.objects.filter(bloque=libre, estado=EstadoReserva.CONFIRMADA)
    assert not confirmadas.exists()
    if confirmacion.status_code == 200:
        # Gano la confirmacion: despues, el estudiante cancelo la CONFIRMADA.
        assert solicitud.confirmada_en is not None
        esperados = [
            (camila.usuario_id, "RESERVA_CONFIRMADA", solicitud.id),
            (tutora.usuario_id, "RESERVA_CANCELADA", solicitud.id),
        ]
    else:
        # Gano la cancelacion: la confirmacion ya no la encontro pendiente.
        assert confirmacion.json()["codigo"] == "reserva_no_pendiente"
        assert solicitud.confirmada_en is None
        esperados = [(tutora.usuario_id, "RESERVA_CANCELADA", solicitud.id)]
    assert sorted(pedidos(aviso), key=str) == sorted(esperados, key=str)


# ------------------------------------------------------------ el reembolso (parte B)

CLAVE = "clave-de-prueba"
ESTADO_PAGO = "/api/tutoring/v1/internal/reservas/{}/estado-pago"


def con_pago(
    en_bloque,
    solicitante,
    asignatura,
    estado_pago,
    monto=Decimal("5000"),
    estado=EstadoReserva.CONFIRMADA,
):
    """Una reserva que ocupa el bloque, con su monto y la copia del pago.

    Como la deja HU-23: con estado_pago, pago_actualizado_en lleva la hora del
    ultimo aviso de Pagos, hace cinco minutos. Sin monto no hay estado_pago
    (ck_reserva_pago_con_monto).
    """
    en_bloque.estado = EstadoBloque.OCUPADO
    en_bloque.save(update_fields=["estado", "actualizado_en"])
    avisado = None if estado_pago is None else timezone.now() - timedelta(minutes=5)
    return reserva(
        en_bloque,
        solicitante,
        asignatura,
        estado,
        monto=monto,
        estado_pago=estado_pago,
        pago_actualizado_en=avisado,
    )


def hace_lo_de_pagos(cliente):
    """El reembolso de Pagos (pagos/internas.py), visto desde Tutorias.

    Pagos deja el pago REEMBOLSADO y, antes de responder, se lo informa a
    Tutorias con PATCH /internal/reservas/<id>/estado-pago (HU-23), con la
    clave de servicio y el instante del cambio. Despues responde 200, y
    pedir_reembolso devuelve True.
    """

    def reembolsar(reserva_id):
        respuesta = cliente.patch(
            ESTADO_PAGO.format(reserva_id),
            {
                "estado_pago": "REEMBOLSADO",
                "actualizado_en": instante_preciso(timezone.now()),
            },
            content_type="application/json",
            HTTP_X_CLAVE_SERVICIO=CLAVE,
        )
        assert respuesta.json() == {"aplicado": True, "estado_pago": "REEMBOLSADO"}
        return True

    return reembolsar


CON_MONTO = {
    "pagado_cancela_el_estudiante": (EstadoPago.PAGADO, "estudiante"),
    "pendiente_cancela_el_estudiante": (EstadoPago.PENDIENTE, "estudiante"),
    "fallido_cancela_el_estudiante": (EstadoPago.FALLIDO, "estudiante"),
    "sin_pago_cancela_el_estudiante": (None, "estudiante"),
    "pagado_cancela_el_tutor": (EstadoPago.PAGADO, "tutor"),
}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "estado_pago, quien", list(CON_MONTO.values()), ids=list(CON_MONTO)
)
def test_cancelar_una_confirmada_con_monto_pide_el_reembolso(
    client,
    cabecera,
    aviso,
    reembolso,
    django_capture_on_commit_callbacks,
    tutora,
    libre,
    asignatura,
    estado_pago,
    quien,
):
    """Criterio 3 (CA9), aunque la copia no diga PAGADO.

    estado_pago es una copia que puede venir atrasada: Pagos es la unica
    fuente del estado del pago (T-174) y decide si hay algo que reembolsar.
    """
    camila = persona("Camila", "Rojas")
    tutoria = con_pago(libre, camila, asignatura, estado_pago)
    cancela = camila if quien == "estudiante" else tutora

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        respuesta = cancelar(client, cabecera(cancela), tutoria.id)

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "CANCELADA"
    reembolso.assert_called_once_with(tutoria.id)
    # El reembolso y el aviso.
    assert len(callbacks) == 2
    assert aviso.call_count == 1


@pytest.mark.django_db
def test_el_reembolso_se_pide_despues_del_commit_y_antes_del_aviso(
    client,
    cabecera,
    aviso,
    reembolso,
    django_capture_on_commit_callbacks,
    tutora,
    libre,
    asignatura,
):
    camila = persona("Camila", "Rojas")
    tutoria = con_pago(libre, camila, asignatura, EstadoPago.PAGADO)

    with django_capture_on_commit_callbacks() as callbacks:
        respuesta = cancelar(client, cabecera(camila), tutoria.id)

    assert respuesta.status_code == 200
    # Durante la peticion no se llamo a Pagos: quedo pedido para despues del
    # commit, sin ningun bloqueo tomado.
    assert not reembolso.called
    assert not aviso.called
    assert len(callbacks) == 2
    # Primero el reembolso...
    callbacks[0]()
    reembolso.assert_called_once_with(tutoria.id)
    assert not aviso.called
    # ... y despues el aviso.
    callbacks[1]()
    assert pedidos(aviso) == [(tutora.usuario_id, "RESERVA_CANCELADA", tutoria.id)]


@pytest.mark.django_db
@pytest.mark.parametrize("caso", ["ya_reembolsada", "gratuita", "retira_una_solicitud"])
def test_sin_nada_que_reembolsar_no_se_le_pide_a_pagos(
    client,
    cabecera,
    aviso,
    reembolso,
    django_capture_on_commit_callbacks,
    tutora,
    libre,
    asignatura,
    caso,
):
    camila = persona("Camila", "Rojas")
    if caso == "ya_reembolsada":
        una_reserva = con_pago(libre, camila, asignatura, EstadoPago.REEMBOLSADO)
    elif caso == "gratuita":
        # Sin tarifa no hay pago (RN-05): estado_pago queda nulo, como lo pide
        # ck_reserva_pago_con_monto.
        una_reserva = con_pago(libre, camila, asignatura, None, monto=Decimal("0"))
    else:
        # Una solicitud no se paga.
        una_reserva = reserva(libre, camila, asignatura)

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        respuesta = cancelar(client, cabecera(camila), una_reserva.id)

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "CANCELADA"
    assert not reembolso.called
    # Solo el aviso.
    assert len(callbacks) == 1
    assert aviso.call_count == 1


@pytest.mark.django_db
def test_si_la_cancelacion_falla_no_se_pide_el_reembolso(
    client,
    cabecera,
    aviso,
    reembolso,
    django_capture_on_commit_callbacks,
    tutora,
    libre,
    asignatura,
):
    """Todas pagadas: si la cancelacion pasara, se pediria el reembolso."""
    camila = persona("Camila", "Rojas")
    en_curso = con_pago(empezado(tutora), camila, asignatura, EstadoPago.PAGADO)
    futura = con_pago(libre, camila, asignatura, EstadoPago.PAGADO)
    realizada = con_pago(
        empezado(tutora, -120, -60),
        camila,
        asignatura,
        EstadoPago.PAGADO,
        estado=EstadoReserva.REALIZADA,
    )
    # Ya cancelada y con el reembolso pendiente: cancelarla otra vez no lo
    # reintenta.
    cancelada = reserva(
        bloque(tutora, 3, 4),
        camila,
        asignatura,
        EstadoReserva.CANCELADA,
        estado_pago=EstadoPago.PAGADO,
        pago_actualizado_en=timezone.now() - timedelta(hours=2),
    )

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        respuestas = [
            cancelar(client, cabecera(camila), en_curso.id),
            cancelar(client, cabecera(persona("Diego", "Herrera")), futura.id),
            cancelar(client, cabecera(camila), realizada.id),
            cancelar(client, cabecera(camila), cancelada.id),
        ]

    assert [error(r) for r in respuestas] == [
        (400, "bloque_en_el_pasado"),
        (404, "reserva_no_encontrada"),
        (409, "reserva_no_cancelable"),
        (409, "reserva_no_cancelable"),
    ]
    assert callbacks == []
    assert not reembolso.called
    assert not aviso.called


@pytest.mark.django_db
def test_si_el_reembolso_queda_pendiente_la_cancelacion_queda_igual(
    client,
    cabecera,
    aviso,
    reembolso,
    django_capture_on_commit_callbacks,
    tutora,
    libre,
    asignatura,
):
    """pedir_reembolso devuelve False: Pagos no respondio. No se reintenta."""
    camila = persona("Camila", "Rojas")
    tutoria = con_pago(libre, camila, asignatura, EstadoPago.PAGADO)
    reembolso.return_value = False

    with django_capture_on_commit_callbacks(execute=True):
        respuesta = cancelar(client, cabecera(camila), tutoria.id)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert (cuerpo["estado"], cuerpo["estado_pago"]) == ("CANCELADA", "PAGADO")
    reembolso.assert_called_once_with(tutoria.id)
    tutoria.refresh_from_db()
    libre.refresh_from_db()
    assert (tutoria.estado, tutoria.estado_pago, libre.estado) == (
        EstadoReserva.CANCELADA,
        EstadoPago.PAGADO,
        EstadoBloque.LIBRE,
    )
    # El aviso sale igual.
    assert pedidos(aviso) == [(tutora.usuario_id, "RESERVA_CANCELADA", tutoria.id)]


@pytest.mark.django_db
def test_el_camino_completo_deja_el_pago_reembolsado(
    client,
    cabecera,
    settings,
    aviso,
    reembolso,
    django_capture_on_commit_callbacks,
    tutora,
    libre,
    asignatura,
):
    """Criterio 3: la reserva cancelada queda con estado_pago REEMBOLSADO.

    El reemplazo de pedir_reembolso hace lo que hace Pagos, con la ruta
    interna de HU-23. En la integracion continua CLAVE_SERVICIO esta vacia y
    esa ruta responde 404: la clave se fija aqui, y el PATCH la manda.
    """
    settings.CLAVE_SERVICIO = CLAVE
    camila = persona("Camila", "Rojas")
    tutoria = con_pago(libre, camila, asignatura, EstadoPago.PAGADO)
    reembolso.side_effect = hace_lo_de_pagos(client)

    with django_capture_on_commit_callbacks(execute=True):
        respuesta = cancelar(client, cabecera(camila), tutoria.id)

    assert respuesta.status_code == 200
    reembolso.assert_called_once_with(tutoria.id)
    tutoria.refresh_from_db()
    assert (tutoria.estado, tutoria.estado_pago) == (
        EstadoReserva.CANCELADA,
        EstadoPago.REEMBOLSADO,
    )


@pytest.mark.django_db(transaction=True)
def test_la_respuesta_ya_trae_el_pago_reembolsado(
    client, cabecera, settings, aviso, reembolso, tutora, libre, asignatura
):
    """Como en el sistema levantado: Pagos informa REEMBOLSADO antes de responder.

    Con transaction=True los on_commit se ejecutan de verdad, dentro de la
    peticion, al cerrar su transaccion. La vista lee la reserva despues, con el
    aviso de Pagos ya aplicado: es lo que muestra la pantalla (HU-30).
    """
    settings.CLAVE_SERVICIO = CLAVE
    camila = persona("Camila", "Rojas")
    tutoria = con_pago(libre, camila, asignatura, EstadoPago.PAGADO)
    # Otro cliente: el PATCH llega mientras la cancelacion sigue en curso.
    reembolso.side_effect = hace_lo_de_pagos(Client())

    respuesta = cancelar(client, cabecera(camila), tutoria.id)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert (cuerpo["estado"], cuerpo["estado_pago"]) == ("CANCELADA", "REEMBOLSADO")
    reembolso.assert_called_once_with(tutoria.id)
    assert aviso.call_count == 1
