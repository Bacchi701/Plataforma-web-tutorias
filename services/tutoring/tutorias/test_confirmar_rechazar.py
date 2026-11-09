"""Pruebas de HU-22: el tutor confirma o rechaza una solicitud.

Corren contra PostgreSQL, como test_reservas.py: las reglas que sostienen la
confirmacion (ux_reserva_bloque_ocupado y ck_reserva_confirmada_completa) y el
bloqueo con SELECT ... FOR UPDATE solo existen ahi. Firman los tokens con su
propio par RSA, como Identidad. Las solicitudes se crean directo en la base;
donde una prueba usa POST /reservas, Identidad la hace IdentidadFalsa, de
test_reservas.py. pedir_aviso se reemplaza en tutorias.reservas, donde se usa.
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
from django.db import IntegrityError, connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from . import llamadas, reservas
from .autenticacion import leer_clave
from .bloques import instante_json
from .models import (
    ESTADOS_QUE_OCUPAN,
    AsignaturaRef,
    BloqueDisponibilidad,
    EstadoBloque,
    EstadoReserva,
    Modalidad,
    PerfilTutor,
    Reserva,
    UsuarioRef,
)
from .reservas import guardar_confirmacion
from .test_reservas import IdentidadFalsa

URL = "/api/tutoring/v1/reservas"
TUTORES = "/api/tutoring/v1/tutores"
# Los bloques de las pruebas se cuentan en horas desde manana a mediodia (UTC).
MANANA = (timezone.now() + timedelta(days=1)).replace(
    hour=12, minute=0, second=0, microsecond=0
)
LUGAR = "Sede Alameda, biblioteca, sala de estudio 2"
ENLACE = "https://meet.google.com/abc-defg-hij"
# Segundos que espera la prueba de concurrencia a cada hilo.
ESPERA = 10


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
def identidad(monkeypatch, settings):
    """Identidad, para POST /reservas (GET /yo) y para el aviso (HU-16)."""
    settings.URL_IDENTIDAD = "http://identity:8000"
    falsa = IdentidadFalsa()
    monkeypatch.setattr(llamadas, "abrir", falsa.abrir)
    return falsa


@pytest.fixture
def aviso(monkeypatch):
    """pedir_aviso reemplazado donde se usa: en tutorias.reservas."""
    falso = mock.Mock(return_value=True)
    monkeypatch.setattr(reservas, "pedir_aviso", falso)
    return falso


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


def en_utc(horas):
    """MANANA + horas, como lo escribe la API: en UTC, con Z y sin fraccion."""
    return (MANANA + timedelta(hours=horas)).strftime("%Y-%m-%dT%H:%M:%SZ")


def confirmar(client, encabezado, reserva_id, modalidad="EN_LINEA", lugar=ENLACE):
    return client.post(
        f"{URL}/{reserva_id}/confirmar",
        {"modalidad": modalidad, "lugar_o_enlace": lugar},
        content_type="application/json",
        **encabezado,
    )


def rechazar(client, encabezado, reserva_id):
    """Sin cuerpo."""
    return client.post(f"{URL}/{reserva_id}/rechazar", **encabezado)


ACCIONES = {"confirmar": confirmar, "rechazar": rechazar}


def error(respuesta):
    return respuesta.status_code, respuesta.json()["codigo"]


def pedidos(aviso):
    """(destinatario, plantilla, id de la reserva) de cada aviso pedido, en orden."""
    return [
        (llamada.args[0], llamada.args[1], llamada.args[2].id)
        for llamada in aviso.call_args_list
    ]


# ------------------------------------------------------------ criterio 1 (CA4)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "modalidad, lugar",
    [("PRESENCIAL", LUGAR), ("EN_LINEA", ENLACE)],
    ids=["presencial", "en_linea"],
)
def test_el_tutor_confirma_y_el_bloque_queda_ocupado(
    client, cabecera, tutora, libre, asignatura, modalidad, lugar
):
    camila = persona("Camila", "Rojas")
    solicitud = reserva(
        libre, camila, asignatura, nota="Me cuesta la tercera forma normal."
    )
    antes = timezone.now()

    respuesta = confirmar(client, cabecera(tutora), solicitud.id, modalidad, lugar)

    assert respuesta.status_code == 200
    solicitud.refresh_from_db()
    # El mismo formato de HU-21, visto por el tutor.
    assert respuesta.json() == {
        "id": str(solicitud.id),
        "estado": "CONFIRMADA",
        "nota": "Me cuesta la tercera forma normal.",
        "modalidad": modalidad,
        "lugar_o_enlace": lugar,
        "monto": 5000,
        "estado_pago": None,
        "creada_en": instante_json(solicitud.creada_en),
        "confirmada_en": instante_json(solicitud.confirmada_en),
        "cerrada_en": None,
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
        "rol": "tutor",
    }
    assert (solicitud.estado, solicitud.modalidad, solicitud.lugar_o_enlace) == (
        EstadoReserva.CONFIRMADA,
        modalidad,
        lugar,
    )
    assert antes <= solicitud.confirmada_en <= timezone.now()
    assert solicitud.cerrada_en is None
    libre.refresh_from_db()
    assert libre.estado == EstadoBloque.OCUPADO
    # Ya no sale entre los horarios disponibles del perfil publico (HU-20).
    assert client.get(f"{TUTORES}/{tutora.usuario_id}").json()["bloques"] == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    "modalidad, enviado, guardado",
    [
        ("PRESENCIAL", "  Sala 301, edificio B  ", "Sala 301, edificio B"),
        ("PRESENCIAL", "x" * 300, "x" * 300),
        (
            "EN_LINEA",
            " http://meet.example.com/tutoria-bdd ",
            "http://meet.example.com/tutoria-bdd",
        ),
    ],
    ids=["sin_espacios_a_los_lados", "de_300", "enlace_http"],
)
def test_el_lugar_se_guarda_sin_espacios_a_los_lados_y_hasta_300(
    client, cabecera, tutora, libre, asignatura, modalidad, enviado, guardado
):
    solicitud = reserva(libre, persona("Camila", "Rojas"), asignatura)

    respuesta = confirmar(client, cabecera(tutora), solicitud.id, modalidad, enviado)

    assert respuesta.status_code == 200
    assert respuesta.json()["lugar_o_enlace"] == guardado
    solicitud.refresh_from_db()
    assert (solicitud.estado, solicitud.lugar_o_enlace) == (
        EstadoReserva.CONFIRMADA,
        guardado,
    )


# ------------------------------------------------------------ criterio 2 (RN-07)

SIN_MODALIDAD = "Indica la modalidad de la tutoría: PRESENCIAL o EN_LINEA."
SIN_LUGAR = "Indica el lugar de la tutoría presencial."
SIN_ENLACE = "Indica el enlace de la tutoría en línea."
NO_ES_ENLACE = (
    "El enlace de una tutoría en línea tiene que empezar con http:// o https://."
)
CONFIRMACIONES_INCOMPLETAS = {
    "sin_modalidad": ({"lugar_o_enlace": LUGAR}, "modalidad_invalida", SIN_MODALIDAD),
    "modalidad_inventada": (
        {"modalidad": "HIBRIDA", "lugar_o_enlace": LUGAR},
        "modalidad_invalida",
        SIN_MODALIDAD,
    ),
    "modalidad_en_minusculas": (
        {"modalidad": "presencial", "lugar_o_enlace": LUGAR},
        "modalidad_invalida",
        SIN_MODALIDAD,
    ),
    "sin_lugar": ({"modalidad": "PRESENCIAL"}, "lugar_o_enlace_invalido", SIN_LUGAR),
    "lugar_null": (
        {"modalidad": "PRESENCIAL", "lugar_o_enlace": None},
        "lugar_o_enlace_invalido",
        SIN_LUGAR,
    ),
    "solo_espacios": (
        {"modalidad": "PRESENCIAL", "lugar_o_enlace": "   "},
        "lugar_o_enlace_invalido",
        SIN_LUGAR,
    ),
    "en_linea_sin_enlace": (
        {"modalidad": "EN_LINEA", "lugar_o_enlace": ""},
        "lugar_o_enlace_invalido",
        SIN_ENLACE,
    ),
    "de_301": (
        {"modalidad": "PRESENCIAL", "lugar_o_enlace": "x" * 301},
        "lugar_o_enlace_invalido",
        "El lugar o el enlace puede tener hasta 300 caracteres.",
    ),
    "en_linea_con_un_texto": (
        {"modalidad": "EN_LINEA", "lugar_o_enlace": LUGAR},
        "lugar_o_enlace_invalido",
        NO_ES_ENLACE,
    ),
    "en_linea_sin_http": (
        {"modalidad": "EN_LINEA", "lugar_o_enlace": "meet.google.com/abc-defg-hij"},
        "lugar_o_enlace_invalido",
        NO_ES_ENLACE,
    ),
    "lugar_numero": (
        {"modalidad": "PRESENCIAL", "lugar_o_enlace": 301},
        "lugar_o_enlace_invalido",
        "El lugar o el enlace tiene que ser un texto.",
    ),
    "lugar_con_nulo": (
        {"modalidad": "PRESENCIAL", "lugar_o_enlace": "Sala\x00301"},
        "lugar_o_enlace_invalido",
        "El lugar o el enlace tiene caracteres que no se pueden guardar.",
    ),
}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "enviado, codigo, mensaje",
    list(CONFIRMACIONES_INCOMPLETAS.values()),
    ids=list(CONFIRMACIONES_INCOMPLETAS),
)
def test_una_confirmacion_incompleta_responde_400_sin_tocar_la_base(
    client, cabecera, tutora, libre, asignatura, enviado, codigo, mensaje
):
    solicitud = reserva(libre, persona("Camila", "Rojas"), asignatura)
    encabezado = cabecera(tutora)

    with CaptureQueriesContext(connection) as consultas:
        respuesta = client.post(
            f"{URL}/{solicitud.id}/confirmar",
            enviado,
            content_type="application/json",
            **encabezado,
        )

    assert error(respuesta) == (400, codigo)
    assert respuesta.json()["mensaje"] == mensaje
    # El cuerpo se revisa antes de tocar la base.
    assert len(consultas) == 0
    solicitud.refresh_from_db()
    assert (
        solicitud.estado,
        solicitud.modalidad,
        solicitud.lugar_o_enlace,
        solicitud.confirmada_en,
    ) == (EstadoReserva.SOLICITADA, None, None, None)
    libre.refresh_from_db()
    assert libre.estado == EstadoBloque.LIBRE


# ------------------------------------------------------------ criterio 3 (RN-03)


@pytest.mark.django_db
def test_confirmar_una_rechaza_las_demas_solicitudes_del_bloque(
    client, cabecera, tutora, libre, asignatura
):
    diego = persona("Diego", "Herrera")
    elegida = reserva(libre, persona("Camila", "Rojas"), asignatura)
    otras = [
        reserva(libre, diego, asignatura),
        reserva(libre, persona("Fernanda", "Castro"), asignatura),
    ]
    # Lo que no es una solicitud pendiente de ese bloque no cambia.
    expirada = reserva(
        libre, persona("Tomás", "Vidal"), asignatura, EstadoReserva.EXPIRADA
    )
    otro_bloque = bloque(tutora, 3, 4)
    en_otro_bloque = reserva(otro_bloque, diego, asignatura)
    antes = timezone.now()

    respuesta = confirmar(client, cabecera(tutora), elegida.id)

    assert respuesta.status_code == 200
    for otra in otras:
        otra.refresh_from_db()
        assert otra.estado == EstadoReserva.RECHAZADA
        assert antes <= otra.cerrada_en <= timezone.now()
        assert (otra.modalidad, otra.confirmada_en) == (None, None)
    cerrada_en = expirada.cerrada_en
    expirada.refresh_from_db()
    assert (expirada.estado, expirada.cerrada_en) == (
        EstadoReserva.EXPIRADA,
        cerrada_en,
    )
    en_otro_bloque.refresh_from_db()
    assert (en_otro_bloque.estado, en_otro_bloque.cerrada_en) == (
        EstadoReserva.SOLICITADA,
        None,
    )
    otro_bloque.refresh_from_db()
    assert otro_bloque.estado == EstadoBloque.LIBRE


# ------------------------------------------------------------ criterio 4


@pytest.mark.django_db(transaction=True)
def test_dos_confirmaciones_simultaneas_del_mismo_bloque_solo_una_gana(
    cabecera, aviso, tutora, libre, asignatura
):
    """Dos hilos, cada uno con su conexion, confirman a la vez dos solicitudes.

    Con transaction=True los datos quedan guardados de verdad, para que los
    vean las conexiones de los hilos, y los on_commit se ejecutan: por eso
    pedir_aviso va reemplazado (fixture aviso).
    """
    de_camila = reserva(libre, persona("Camila", "Rojas"), asignatura)
    de_diego = reserva(libre, persona("Diego", "Herrera"), asignatura)
    encabezado = cabecera(tutora)
    barrera = threading.Barrier(2, timeout=ESPERA)
    resultados = []

    def confirmar_en_un_hilo(reserva_id):
        try:
            cliente = Client()
            # Los dos esperan aqui, para que los POST de verdad se crucen.
            barrera.wait()
            resultados.append(confirmar(cliente, encabezado, reserva_id).status_code)
        except Exception as falla:
            resultados.append(falla)
        finally:
            connection.close()

    hilos = [
        threading.Thread(target=confirmar_en_un_hilo, args=(solicitud.id,))
        for solicitud in (de_camila, de_diego)
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=3 * ESPERA)

    assert not any(hilo.is_alive() for hilo in hilos)
    assert all(isinstance(resultado, int) for resultado in resultados), resultados
    assert sorted(resultados) == [200, 409]
    confirmadas = Reserva.objects.filter(bloque=libre, estado=EstadoReserva.CONFIRMADA)
    assert confirmadas.count() == 1
    ganadora = confirmadas.get()
    perdedora = Reserva.objects.exclude(id=ganadora.id).get(bloque=libre)
    assert perdedora.estado == EstadoReserva.RECHAZADA
    libre.refresh_from_db()
    assert libre.estado == EstadoBloque.OCUPADO
    # Solo la que gano pidio avisos: uno a cada estudiante.
    assert sorted(pedidos(aviso), key=str) == sorted(
        [
            (ganadora.solicitante_usuario_id, "RESERVA_CONFIRMADA", ganadora.id),
            (perdedora.solicitante_usuario_id, "RESERVA_RECHAZADA", perdedora.id),
        ],
        key=str,
    )


@pytest.mark.django_db
def test_si_la_base_ya_tiene_otra_confirmada_responde_409_bloque_ocupado(
    client, cabecera, tutora, libre, asignatura
):
    """El ultimo recurso del criterio 4: ux_reserva_bloque_ocupado.

    El bloque sigue LIBRE, pero la base ya tiene una reserva que lo ocupa.
    """
    reserva(libre, persona("Diego", "Herrera"), asignatura, EstadoReserva.CONFIRMADA)
    pendiente = reserva(libre, persona("Camila", "Rojas"), asignatura)

    respuesta = confirmar(client, cabecera(tutora), pendiente.id)

    assert error(respuesta) == (409, "bloque_ocupado")
    assert respuesta.json()["mensaje"] == (
        "Ese horario ya tiene otra tutoría confirmada."
    )
    pendiente.refresh_from_db()
    assert (pendiente.estado, pendiente.modalidad, pendiente.confirmada_en) == (
        EstadoReserva.SOLICITADA,
        None,
        None,
    )
    libre.refresh_from_db()
    assert libre.estado == EstadoBloque.LIBRE
    assert Reserva.objects.filter(estado=EstadoReserva.CONFIRMADA).count() == 1


@pytest.mark.django_db
def test_un_bloque_ocupado_responde_409_bloque_ocupado(
    client, cabecera, tutora, asignatura
):
    ocupado = bloque(tutora, 1, 2, estado=EstadoBloque.OCUPADO)
    reserva(ocupado, persona("Diego", "Herrera"), asignatura, EstadoReserva.CONFIRMADA)
    pendiente = reserva(ocupado, persona("Camila", "Rojas"), asignatura)

    respuesta = confirmar(client, cabecera(tutora), pendiente.id)

    assert error(respuesta) == (409, "bloque_ocupado")
    pendiente.refresh_from_db()
    assert (pendiente.estado, pendiente.cerrada_en) == (EstadoReserva.SOLICITADA, None)


@pytest.mark.django_db
def test_otro_rechazo_de_la_base_no_se_disfraza(libre, asignatura):
    """Solo ux_reserva_bloque_ocupado se traduce: otro IntegrityError se relanza."""
    solicitud = reserva(libre, persona("Camila", "Rojas"), asignatura)
    # Sin modalidad ni lugar: la base la rechaza (ck_reserva_confirmada_completa).
    solicitud.estado = EstadoReserva.CONFIRMADA

    with pytest.raises(IntegrityError):
        guardar_confirmacion(solicitud)

    solicitud.refresh_from_db()
    assert solicitud.estado == EstadoReserva.SOLICITADA


# ------------------------------------------------------------ criterio 5


@pytest.mark.django_db
def test_rechazar_deja_la_solicitud_rechazada_y_el_bloque_libre(
    client, cabecera, identidad, tutora, libre, asignatura
):
    solicitud = reserva(libre, persona("Camila", "Rojas"), asignatura)
    otra = reserva(libre, persona("Diego", "Herrera"), asignatura)
    antes = timezone.now()

    respuesta = rechazar(client, cabecera(tutora), solicitud.id)

    assert respuesta.status_code == 200
    solicitud.refresh_from_db()
    cuerpo = respuesta.json()
    assert (cuerpo["id"], cuerpo["estado"], cuerpo["rol"]) == (
        str(solicitud.id),
        "RECHAZADA",
        "tutor",
    )
    assert cuerpo["cerrada_en"] == instante_json(solicitud.cerrada_en)
    assert (cuerpo["modalidad"], cuerpo["lugar_o_enlace"], cuerpo["confirmada_en"]) == (
        None,
        None,
        None,
    )
    assert solicitud.estado == EstadoReserva.RECHAZADA
    assert antes <= solicitud.cerrada_en <= timezone.now()
    # Solo esa: la otra solicitud del bloque sigue pendiente.
    otra.refresh_from_db()
    assert otra.estado == EstadoReserva.SOLICITADA
    libre.refresh_from_db()
    assert libre.estado == EstadoBloque.LIBRE
    # El bloque sigue aceptando solicitudes nuevas (HU-21).
    fernanda = identidad.registrar(uuid.uuid4(), "Fernanda", "Castro")
    nueva = client.post(
        URL,
        {"bloque_id": str(libre.id), "asignatura_id": str(asignatura.asignatura_id)},
        content_type="application/json",
        **cabecera(fernanda),
    )
    assert nueva.status_code == 201
    pendientes = Reserva.objects.filter(bloque=libre, estado=EstadoReserva.SOLICITADA)
    assert pendientes.count() == 2


# ------------------------------------------------------------ criterio 6 (T-174)


@pytest.mark.django_db
@pytest.mark.parametrize("monto", [5000, 0], ids=["con_tarifa", "gratuita"])
def test_al_confirmar_el_estado_del_pago_sigue_nulo(
    client, cabecera, tutora, libre, asignatura, monto
):
    """T-174: pasa a PENDIENTE cuando Pagos crea el pago (HU-23), no al confirmar."""
    solicitud = reserva(
        libre, persona("Camila", "Rojas"), asignatura, monto=Decimal(monto)
    )

    respuesta = confirmar(client, cabecera(tutora), solicitud.id)

    assert respuesta.status_code == 200
    assert (respuesta.json()["monto"], respuesta.json()["estado_pago"]) == (monto, None)
    solicitud.refresh_from_db()
    assert (solicitud.estado, solicitud.estado_pago, solicitud.pago_actualizado_en) == (
        EstadoReserva.CONFIRMADA,
        None,
        None,
    )


# ------------------------------------------------------------ criterio 7 (HU-16)


@pytest.mark.django_db
def test_al_confirmar_avisa_al_estudiante_y_a_cada_rechazado(
    client,
    cabecera,
    aviso,
    django_capture_on_commit_callbacks,
    tutora,
    libre,
    asignatura,
):
    camila = persona("Camila", "Rojas")
    diego = persona("Diego", "Herrera")
    fernanda = persona("Fernanda", "Castro")
    elegida = reserva(libre, camila, asignatura)
    de_diego = reserva(libre, diego, asignatura)
    de_fernanda = reserva(libre, fernanda, asignatura)

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        respuesta = confirmar(client, cabecera(tutora), elegida.id)
        # Todavia no: los avisos salen cuando la transaccion se confirma.
        assert not aviso.called

    assert respuesta.status_code == 200
    assert len(callbacks) == 3
    # Primero el del estudiante elegido; despues uno por cada solicitud
    # rechazada, cada uno con su propio solicitante y su propia reserva.
    [confirmado, *rechazados] = pedidos(aviso)
    assert confirmado == (camila.usuario_id, "RESERVA_CONFIRMADA", elegida.id)
    assert sorted(rechazados, key=str) == sorted(
        [
            (diego.usuario_id, "RESERVA_RECHAZADA", de_diego.id),
            (fernanda.usuario_id, "RESERVA_RECHAZADA", de_fernanda.id),
        ],
        key=str,
    )
    # Cada aviso lleva su reserva ya con el estado nuevo.
    estados = {
        llamada.args[2].id: llamada.args[2].estado for llamada in aviso.call_args_list
    }
    assert estados == {
        elegida.id: EstadoReserva.CONFIRMADA,
        de_diego.id: EstadoReserva.RECHAZADA,
        de_fernanda.id: EstadoReserva.RECHAZADA,
    }


@pytest.mark.django_db
def test_los_avisos_van_a_cada_estudiante_y_nombran_al_tutor(
    client,
    cabecera,
    identidad,
    django_capture_on_commit_callbacks,
    tutora,
    libre,
    asignatura,
):
    """Con pedir_aviso de verdad: el cuerpo que recibe Identidad (HU-16)."""
    camila = persona("Camila", "Rojas")
    diego = persona("Diego", "Herrera")
    elegida = reserva(libre, camila, asignatura)
    de_diego = reserva(libre, diego, asignatura)

    with django_capture_on_commit_callbacks(execute=True):
        respuesta = confirmar(client, cabecera(tutora), elegida.id, "PRESENCIAL", LUGAR)

    assert respuesta.status_code == 200
    avisos = identidad.avisos()
    assert [(a["usuario_id"], a["plantilla"], a["referencia_id"]) for a in avisos] == [
        (str(camila.usuario_id), "RESERVA_CONFIRMADA", str(elegida.id)),
        (str(diego.usuario_id), "RESERVA_RECHAZADA", str(de_diego.id)),
    ]
    # Al estudiante, la otra parte es el tutor.
    for cuerpo in avisos:
        assert cuerpo["datos"]["otra_persona"] == {
            "nombre": "Valentina",
            "apellido": "Soto",
        }
    assert (avisos[0]["datos"]["modalidad"], avisos[0]["datos"]["lugar_o_enlace"]) == (
        "PRESENCIAL",
        LUGAR,
    )
    assert (avisos[1]["datos"]["modalidad"], avisos[1]["datos"]["lugar_o_enlace"]) == (
        None,
        None,
    )


@pytest.mark.django_db
def test_al_rechazar_avisa_al_estudiante(
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
        respuesta = rechazar(client, cabecera(tutora), solicitud.id)
        assert not aviso.called

    assert respuesta.status_code == 200
    assert len(callbacks) == 1
    assert pedidos(aviso) == [(camila.usuario_id, "RESERVA_RECHAZADA", solicitud.id)]


@pytest.mark.django_db
def test_si_la_operacion_falla_no_se_avisa(
    client,
    cabecera,
    aviso,
    django_capture_on_commit_callbacks,
    tutora,
    libre,
    asignatura,
):
    diego = persona("Diego", "Herrera")
    confirmada = reserva(
        bloque(tutora, 3, 4, estado=EstadoBloque.OCUPADO),
        diego,
        asignatura,
        EstadoReserva.CONFIRMADA,
    )
    # El ultimo recurso: el bloque libre ya tiene una confirmada en la base.
    reserva(libre, diego, asignatura, EstadoReserva.CONFIRMADA)
    pendiente = reserva(libre, persona("Camila", "Rojas"), asignatura)
    encabezado = cabecera(tutora)

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        respuestas = [
            confirmar(client, encabezado, confirmada.id),
            rechazar(client, encabezado, confirmada.id),
            confirmar(client, encabezado, pendiente.id),
            confirmar(client, cabecera(diego), pendiente.id),
            rechazar(client, cabecera(diego), pendiente.id),
            confirmar(client, encabezado, pendiente.id, "HIBRIDA"),
        ]

    assert [error(r) for r in respuestas] == [
        (409, "reserva_no_pendiente"),
        (409, "reserva_no_pendiente"),
        (409, "bloque_ocupado"),
        (404, "reserva_no_encontrada"),
        (404, "reserva_no_encontrada"),
        (400, "modalidad_invalida"),
    ]
    assert callbacks == []
    assert not aviso.called


# ------------------------------------------------------------ dueno y estado


@pytest.mark.django_db
@pytest.mark.parametrize("accion", list(ACCIONES.values()), ids=list(ACCIONES))
def test_solo_el_tutor_del_bloque_responde_la_solicitud(
    client, cabecera, tutora, libre, asignatura, accion
):
    camila = persona("Camila", "Rojas")
    solicitud = reserva(libre, camila, asignatura)
    matias = persona("Matías", "Fuentes")
    PerfilTutor.objects.create(usuario=matias, asignatura=asignatura, tarifa=3000)

    respuestas = [
        # El solicitante no responde su propia solicitud.
        accion(client, cabecera(camila), solicitud.id),
        # Otro tutor, tampoco.
        accion(client, cabecera(matias), solicitud.id),
        # Una reserva que no existe responde lo mismo.
        accion(client, cabecera(tutora), uuid.uuid4()),
    ]

    for respuesta in respuestas:
        assert error(respuesta) == (404, "reserva_no_encontrada")
        assert respuesta.json()["mensaje"] == "No encontramos esa tutoría."
    solicitud.refresh_from_db()
    assert (solicitud.estado, solicitud.cerrada_en) == (EstadoReserva.SOLICITADA, None)
    libre.refresh_from_db()
    assert libre.estado == EstadoBloque.LIBRE


@pytest.mark.django_db
@pytest.mark.parametrize("accion", list(ACCIONES.values()), ids=list(ACCIONES))
@pytest.mark.parametrize(
    "estado",
    [EstadoReserva.CONFIRMADA, EstadoReserva.RECHAZADA, EstadoReserva.CANCELADA],
    ids=["confirmada", "rechazada", "cancelada"],
)
def test_una_reserva_que_ya_no_esta_pendiente_responde_409(
    client, cabecera, tutora, asignatura, estado, accion
):
    ocupa = estado in ESTADOS_QUE_OCUPAN
    del_bloque = bloque(
        tutora, 1, 2, estado=EstadoBloque.OCUPADO if ocupa else EstadoBloque.LIBRE
    )
    respondida = reserva(del_bloque, persona("Camila", "Rojas"), asignatura, estado)
    antes = (respondida.estado, respondida.confirmada_en, respondida.cerrada_en)

    respuesta = accion(client, cabecera(tutora), respondida.id)

    assert error(respuesta) == (409, "reserva_no_pendiente")
    assert respuesta.json()["mensaje"] == "Esa solicitud ya no está pendiente."
    respondida.refresh_from_db()
    assert (respondida.estado, respondida.confirmada_en, respondida.cerrada_en) == antes
    del_bloque.refresh_from_db()
    assert del_bloque.estado == (EstadoBloque.OCUPADO if ocupa else EstadoBloque.LIBRE)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "desde, hasta", [(-30, 30), (-120, -60)], ids=["en_curso", "ya_termino"]
)
def test_confirmar_un_bloque_que_ya_empezo_responde_400(
    client, cabecera, tutora, asignatura, desde, hasta
):
    ahora = timezone.now()
    empezado = BloqueDisponibilidad.objects.create(
        usuario=tutora,
        inicio_en=ahora + timedelta(minutes=desde),
        fin_en=ahora + timedelta(minutes=hasta),
    )
    solicitud = reserva(empezado, persona("Camila", "Rojas"), asignatura)

    respuesta = confirmar(client, cabecera(tutora), solicitud.id)

    assert error(respuesta) == (400, "bloque_en_el_pasado")
    assert respuesta.json()["mensaje"] == (
        "Ese horario ya empezó: la tutoría ya no se puede confirmar."
    )
    solicitud.refresh_from_db()
    assert (solicitud.estado, solicitud.confirmada_en) == (
        EstadoReserva.SOLICITADA,
        None,
    )
    empezado.refresh_from_db()
    assert empezado.estado == EstadoBloque.LIBRE


@pytest.mark.django_db
def test_sin_token_responde_401(client, libre, asignatura):
    solicitud = reserva(libre, persona("Camila", "Rojas"), asignatura)

    respuestas = [
        confirmar(client, {}, solicitud.id),
        rechazar(client, {}, solicitud.id),
    ]

    assert [error(r) for r in respuestas] == [(401, "not_authenticated")] * 2
    solicitud.refresh_from_db()
    assert solicitud.estado == EstadoReserva.SOLICITADA
