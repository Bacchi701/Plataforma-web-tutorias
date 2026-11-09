"""Pruebas de las rutas internas de Tutorias que usa Pagos (internas.py, HU-23).

Corren contra PostgreSQL. Las reservas se crean directo en la base, como en
test_bloques.py, cumpliendo sus restricciones: RN-07 (una reserva que ocupa
el bloque tiene modalidad, lugar y confirmada_en), RN-05 (sin monto no hay
estado_pago) y que nadie reserva un bloque propio. No dependen de las rutas
de HU-21. Las rutas se llaman con el cliente de pruebas y la cabecera
X-Clave-Servicio, sin token.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from .models import (
    ESTADOS_QUE_OCUPAN,
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
# Los bloques de las pruebas se cuentan en horas desde manana a mediodia (UTC).
MANANA = (timezone.now() + timedelta(days=1)).replace(
    hour=12, minute=0, second=0, microsecond=0
)
# Un instante con microsegundos, como los que manda Pagos.
INSTANTE = datetime(2026, 11, 8, 15, 30, 0, 123456, tzinfo=UTC)
UN_MILISEGUNDO = timedelta(milliseconds=1)
SIETE_CAMPOS = {
    "id",
    "estado",
    "monto",
    "estado_pago",
    "pago_actualizado_en",
    "solicitante_usuario_id",
    "tutor_usuario_id",
}


@pytest.fixture(autouse=True)
def clave_servicio(settings):
    # En la integracion continua CLAVE_SERVICIO no existe: se fija aqui.
    settings.CLAVE_SERVICIO = CLAVE


def persona(nombre):
    return UsuarioRef.objects.create(
        usuario_id=uuid.uuid4(), nombre=nombre, apellido="Demo"
    )


@pytest.fixture
def asignatura(db):
    return AsignaturaRef.objects.create(
        asignatura_id=uuid.uuid4(), sigla="BDD1101", nombre="Base de Datos"
    )


@pytest.fixture
def tutora(db):
    return persona("Valentina")


@pytest.fixture
def camila(db):
    return persona("Camila")


@pytest.fixture
def nueva(tutora, camila, asignatura):
    """Crea reservas de Camila con Valentina, cada una en un bloque propio.

    Cada reserva va dos horas despues de la anterior, para que los bloques de
    la tutora no se solapen (RN-02).
    """
    creadas = []

    def crear(estado=EstadoReserva.CONFIRMADA, monto=5000, **campos):
        desde = MANANA + timedelta(hours=2 * len(creadas))
        ocupa = estado in ESTADOS_QUE_OCUPAN
        bloque = BloqueDisponibilidad.objects.create(
            usuario=tutora,
            inicio_en=desde,
            fin_en=desde + timedelta(hours=1),
            estado=EstadoBloque.OCUPADO if ocupa else EstadoBloque.LIBRE,
        )
        confirmacion = {}
        if ocupa or estado == EstadoReserva.CANCELADA:
            # Una tutoria cancelada ya habia sido confirmada.
            confirmacion = {
                "modalidad": Modalidad.EN_LINEA,
                "lugar_o_enlace": "https://meet.example.com/prueba",
                "confirmada_en": timezone.now(),
            }
        reserva = Reserva.objects.create(
            bloque=bloque,
            solicitante_usuario=camila,
            asignatura=asignatura,
            estado=estado,
            monto=monto,
            **confirmacion,
            **campos,
        )
        creadas.append(reserva)
        return reserva

    return crear


def preciso(instante):
    """El texto que manda Pagos: UTC, con microsegundos y con Z."""
    return instante.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def ver(client, reserva_id, **cabeceras):
    return client.get(f"{URL}/{reserva_id}", **cabeceras)


def avisar(client, reserva_id, cuerpo, **cabeceras):
    return client.patch(
        f"{URL}/{reserva_id}/estado-pago",
        cuerpo,
        content_type="application/json",
        **cabeceras,
    )


def aviso(estado_pago, instante):
    return {"estado_pago": estado_pago, "actualizado_en": preciso(instante)}


def llamar(client, metodo, reserva_id, **cabeceras):
    """GET de la reserva o PATCH de un aviso PENDIENTE valido."""
    if metodo == "GET":
        return ver(client, reserva_id, **cabeceras)
    return avisar(client, reserva_id, aviso("PENDIENTE", INSTANTE), **cabeceras)


def copia_del_pago(reserva):
    """(estado_pago, pago_actualizado_en) de la reserva, leidos de la base."""
    reserva.refresh_from_db()
    return reserva.estado_pago, reserva.pago_actualizado_en


# ------------------------------------------------------------ GET la reserva


@pytest.mark.django_db
def test_ver_reserva_responde_los_siete_campos(client, nueva, tutora, camila):
    reserva = nueva()

    respuesta = ver(client, reserva.id, **CON_CLAVE)

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos == {
        "id": str(reserva.id),
        "estado": "CONFIRMADA",
        "monto": 5000,
        "estado_pago": None,
        "pago_actualizado_en": None,
        "solicitante_usuario_id": str(camila.usuario_id),
        # El tutor es el dueno del bloque.
        "tutor_usuario_id": str(tutora.usuario_id),
    }
    # monto entero: 5000.0 seria igual a 5000, pero no es un int.
    assert isinstance(datos["monto"], int)
    assert set(datos) == SIETE_CAMPOS
    assert "email" not in respuesta.content.decode()


@pytest.mark.django_db
def test_ver_reserva_trae_pago_actualizado_en_con_microsegundos_y_z(client, nueva):
    reserva = nueva(estado_pago=EstadoPago.PAGADO, pago_actualizado_en=INSTANTE)

    datos = ver(client, reserva.id, **CON_CLAVE).json()

    assert datos["estado_pago"] == "PAGADO"
    assert datos["pago_actualizado_en"] == "2026-11-08T15:30:00.123456Z"


# ------------------------------------------------------------ la clave


SIN_CLAVE_VALIDA = {
    "sin_cabecera": {},
    "clave_equivocada": {"HTTP_X_CLAVE_SERVICIO": "clave-equivocada"},
    "con_tilde": {"HTTP_X_CLAVE_SERVICIO": "clave-con-é"},
    "cabecera_vacia": {"HTTP_X_CLAVE_SERVICIO": ""},
    "solo_authorization": {"HTTP_AUTHORIZATION": "Bearer token-cualquiera"},
}


@pytest.mark.django_db
@pytest.mark.parametrize("metodo", ["GET", "PATCH"])
@pytest.mark.parametrize(
    "cabeceras", list(SIN_CLAVE_VALIDA.values()), ids=list(SIN_CLAVE_VALIDA)
)
def test_sin_clave_valida_responde_404_ruta_no_encontrada(
    client, nueva, metodo, cabeceras
):
    reserva = nueva()

    respuesta = llamar(client, metodo, reserva.id, **cabeceras)

    assert respuesta.status_code == 404
    assert respuesta.json()["codigo"] == "ruta_no_encontrada"
    assert copia_del_pago(reserva) == (None, None)


@pytest.mark.django_db
@pytest.mark.parametrize("metodo", ["GET", "PATCH"])
def test_con_clave_servicio_vacia_en_settings_responde_404(
    client, nueva, settings, metodo
):
    settings.CLAVE_SERVICIO = ""
    reserva = nueva()

    con_la_de_antes = llamar(client, metodo, reserva.id, **CON_CLAVE)
    vacia = llamar(client, metodo, reserva.id, HTTP_X_CLAVE_SERVICIO="")

    assert con_la_de_antes.status_code == 404
    assert con_la_de_antes.json()["codigo"] == "ruta_no_encontrada"
    assert vacia.status_code == 404
    assert vacia.json()["codigo"] == "ruta_no_encontrada"
    assert copia_del_pago(reserva) == (None, None)


@pytest.mark.django_db
@pytest.mark.parametrize("metodo", ["GET", "PATCH"])
def test_con_la_clave_un_token_cualquiera_no_se_lee(client, nueva, metodo):
    # Si se leyera el token, la respuesta seria 401 (o 503 sin la clave publica).
    reserva = nueva()

    respuesta = llamar(
        client,
        metodo,
        reserva.id,
        HTTP_AUTHORIZATION="Bearer token-vencido-o-cualquiera",
        **CON_CLAVE,
    )

    assert respuesta.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("metodo", ["GET", "PATCH"])
def test_una_reserva_que_no_existe_responde_404_reserva_no_encontrada(client, metodo):
    respuesta = llamar(client, metodo, uuid.uuid4(), **CON_CLAVE)

    assert respuesta.status_code == 404
    assert respuesta.json() == {
        "codigo": "reserva_no_encontrada",
        "mensaje": "No existe una reserva con ese identificador.",
        "detalles": None,
    }


# ------------------------------------------------------------ PATCH (A-06)


@pytest.mark.django_db
def test_sin_aviso_previo_se_aplica_y_guarda_el_instante_que_mando_pagos(client, nueva):
    reserva = nueva()

    respuesta = avisar(client, reserva.id, aviso("PENDIENTE", INSTANTE), **CON_CLAVE)

    assert respuesta.status_code == 200
    assert respuesta.json() == {"aplicado": True, "estado_pago": "PENDIENTE"}
    # El mismo instante de Pagos, con sus microsegundos, no la hora de Tutorias.
    assert copia_del_pago(reserva) == ("PENDIENTE", INSTANTE)


@pytest.mark.django_db
def test_un_instante_con_desfase_se_guarda_en_utc(client, nueva):
    reserva = nueva()
    cuerpo = {
        "estado_pago": "PENDIENTE",
        "actualizado_en": "2026-11-08T12:30:00.123456-03:00",
    }

    respuesta = avisar(client, reserva.id, cuerpo, **CON_CLAVE)

    assert respuesta.status_code == 200
    assert copia_del_pago(reserva) == ("PENDIENTE", INSTANTE)


@pytest.mark.django_db
def test_un_aviso_posterior_se_aplica(client, nueva):
    reserva = nueva(estado_pago=EstadoPago.PENDIENTE, pago_actualizado_en=INSTANTE)
    despues = INSTANTE + timedelta(seconds=1)

    respuesta = avisar(client, reserva.id, aviso("PAGADO", despues), **CON_CLAVE)

    assert respuesta.json() == {"aplicado": True, "estado_pago": "PAGADO"}
    assert copia_del_pago(reserva) == ("PAGADO", despues)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "instante",
    [INSTANTE, INSTANTE - timedelta(microseconds=1)],
    ids=["igual", "anterior"],
)
def test_un_aviso_igual_o_anterior_no_cambia_nada(client, nueva, instante):
    reserva = nueva(estado_pago=EstadoPago.PAGADO, pago_actualizado_en=INSTANTE)

    respuesta = avisar(client, reserva.id, aviso("FALLIDO", instante), **CON_CLAVE)

    assert respuesta.status_code == 200
    assert respuesta.json() == {"aplicado": False, "estado_pago": "PAGADO"}
    assert copia_del_pago(reserva) == ("PAGADO", INSTANTE)


@pytest.mark.django_db
@pytest.mark.parametrize("orden", ["en_orden", "al_reves"])
def test_dos_avisos_a_un_milisegundo_quedan_con_el_mas_nuevo(client, nueva, orden):
    reserva = nueva()
    primero = aviso("PENDIENTE", INSTANTE)
    segundo = aviso("PAGADO", INSTANTE + UN_MILISEGUNDO)
    avisos = [primero, segundo] if orden == "en_orden" else [segundo, primero]

    respuestas = [avisar(client, reserva.id, a, **CON_CLAVE).json() for a in avisos]

    if orden == "en_orden":
        assert [r["aplicado"] for r in respuestas] == [True, True]
    else:
        # El PENDIENTE llega despues del PAGADO: se descarta (A-06).
        assert respuestas[1] == {"aplicado": False, "estado_pago": "PAGADO"}
    assert copia_del_pago(reserva) == ("PAGADO", INSTANTE + UN_MILISEGUNDO)


@pytest.mark.django_db
def test_una_reserva_sin_monto_responde_409_sin_pago(client, nueva):
    reserva = nueva(monto=0)

    respuesta = avisar(client, reserva.id, aviso("PENDIENTE", INSTANTE), **CON_CLAVE)

    assert respuesta.status_code == 409
    assert respuesta.json() == {
        "codigo": "sin_pago",
        "mensaje": "La reserva no tiene monto: no lleva pago (RN-05).",
        "detalles": None,
    }
    assert copia_del_pago(reserva) == (None, None)


@pytest.mark.django_db
def test_sin_monto_responde_sin_pago_aunque_este_cancelada(client, nueva):
    # El chequeo del monto va antes que el de la reserva cancelada.
    reserva = nueva(estado=EstadoReserva.CANCELADA, monto=0)

    respuesta = avisar(client, reserva.id, aviso("PAGADO", INSTANTE), **CON_CLAVE)

    assert respuesta.status_code == 409
    assert respuesta.json()["codigo"] == "sin_pago"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "cambios",
    [
        {},
        {"estado_pago": None},
        {"estado_pago": "PAGADA"},
        {"estado_pago": "pagado"},
        {"estado_pago": 1},
        {"estado_pago": ["PAGADO"]},
    ],
    ids=["falta", "nulo", "otro_texto", "minusculas", "numero", "lista"],
)
def test_un_estado_pago_invalido_responde_400(client, nueva, cambios):
    reserva = nueva(estado_pago=EstadoPago.PENDIENTE, pago_actualizado_en=INSTANTE)
    despues = preciso(INSTANTE + timedelta(seconds=1))

    respuesta = avisar(
        client, reserva.id, {"actualizado_en": despues, **cambios}, **CON_CLAVE
    )

    assert respuesta.status_code == 400
    assert respuesta.json()["codigo"] == "estado_pago_invalido"
    assert copia_del_pago(reserva) == ("PENDIENTE", INSTANTE)


@pytest.mark.django_db
def test_el_cuerpo_se_valida_antes_de_buscar_la_reserva(client):
    # Con una reserva que no existe responde 400, no 404.
    respuesta = avisar(
        client,
        uuid.uuid4(),
        {"estado_pago": "PAGADO", "actualizado_en": "ayer"},
        **CON_CLAVE,
    )

    assert respuesta.status_code == 400
    assert respuesta.json()["codigo"] == "actualizado_en_invalido"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "cambios",
    [
        {},
        {"actualizado_en": None},
        {"actualizado_en": 1731080000},
        {"actualizado_en": "ayer"},
        {"actualizado_en": "2026-13-45T10:00:00Z"},
        {"actualizado_en": "2026-11-08T15:30:00.123456"},
    ],
    ids=["falta", "nulo", "numero", "texto", "fecha_imposible", "sin_zona"],
)
def test_un_actualizado_en_invalido_responde_400(client, nueva, cambios):
    reserva = nueva()

    respuesta = avisar(
        client, reserva.id, {"estado_pago": "PENDIENTE", **cambios}, **CON_CLAVE
    )

    assert respuesta.status_code == 400
    assert respuesta.json()["codigo"] == "actualizado_en_invalido"
    assert copia_del_pago(reserva) == (None, None)


# ------------------------------------------------- la reserva cancelada


@pytest.mark.django_db
def test_un_pagado_sobre_una_reserva_cancelada_responde_409_reserva_cancelada(
    client, nueva
):
    # La carrera entre pagar y cancelar: Pagos reembolsa el pago solo.
    reserva = nueva(
        estado=EstadoReserva.CANCELADA,
        estado_pago=EstadoPago.PENDIENTE,
        pago_actualizado_en=INSTANTE,
    )
    despues = INSTANTE + timedelta(seconds=1)

    respuesta = avisar(client, reserva.id, aviso("PAGADO", despues), **CON_CLAVE)

    assert respuesta.status_code == 409
    assert respuesta.json() == {
        "codigo": "reserva_cancelada",
        "mensaje": "La reserva está cancelada: el pago se reembolsa.",
        "detalles": None,
    }
    assert copia_del_pago(reserva) == ("PENDIENTE", INSTANTE)


@pytest.mark.django_db
@pytest.mark.parametrize("estado_pago", ["REEMBOLSADO", "PENDIENTE", "FALLIDO"])
def test_los_demas_avisos_sobre_una_reserva_cancelada_se_aplican(
    client, nueva, estado_pago
):
    reserva = nueva(
        estado=EstadoReserva.CANCELADA,
        estado_pago=EstadoPago.PAGADO,
        pago_actualizado_en=INSTANTE,
    )
    despues = INSTANTE + timedelta(seconds=1)

    respuesta = avisar(client, reserva.id, aviso(estado_pago, despues), **CON_CLAVE)

    assert respuesta.json() == {"aplicado": True, "estado_pago": estado_pago}
    assert copia_del_pago(reserva) == (estado_pago, despues)


@pytest.mark.django_db
def test_sobre_una_reserva_cancelada_un_aviso_anterior_tampoco_se_aplica(client, nueva):
    reserva = nueva(
        estado=EstadoReserva.CANCELADA,
        estado_pago=EstadoPago.REEMBOLSADO,
        pago_actualizado_en=INSTANTE,
    )

    respuesta = avisar(
        client,
        reserva.id,
        aviso("REEMBOLSADO", INSTANTE - UN_MILISEGUNDO),
        **CON_CLAVE,
    )

    assert respuesta.json() == {"aplicado": False, "estado_pago": "REEMBOLSADO"}
    assert copia_del_pago(reserva) == ("REEMBOLSADO", INSTANTE)
