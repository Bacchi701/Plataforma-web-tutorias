"""Pruebas de HU-21: solicitar una tutoria y consultar las reservas.

Corren contra PostgreSQL, como test_bloques.py: las reglas de la reserva
(ux_reserva_solicitud_unica y el disparador trg_reserva_no_auto) solo existen
ahi. Firman los tokens con su propio par RSA, como Identidad. Identidad no
esta: IdentidadFalsa reemplaza llamadas.abrir y responde como ella (GET /yo y,
para el aviso de HU-16, POST /internal/avisos). D2 (HU-22) importa esa clase.
"""

import io
import json
import logging
import urllib.error
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest import mock

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.db import IntegrityError, connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from . import llamadas, reservas
from .autenticacion import leer_clave
from .bloques import Rechazo
from .llamadas import pedir_aviso
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
from .reservas import guardar_solicitud

URL = "/api/tutoring/v1/reservas"
TUTORES = "/api/tutoring/v1/tutores"
# Los bloques de las pruebas se cuentan en horas desde manana a mediodia (UTC).
MANANA = (timezone.now() + timedelta(days=1)).replace(
    hour=12, minute=0, second=0, microsecond=0
)
CARRERA = uuid.uuid4()
SEDE = uuid.uuid4()
# Identificadores bien formados, para las pruebas que no llegan a la base.
UN_BLOQUE = str(uuid.uuid4())
UNA_ASIGNATURA = str(uuid.uuid4())


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


# ------------------------------------------------------------ Identidad


class Respuesta(io.BytesIO):
    """Lo que entrega llamadas.abrir() con un 2xx: se usa con with y trae status."""

    def __init__(self, cuerpo, status=200):
        if not isinstance(cuerpo, bytes):
            cuerpo = json.dumps(cuerpo).encode()
        super().__init__(cuerpo)
        self.status = status


def error_http(codigo, cuerpo):
    """Lo que lanza llamadas.abrir() con un 4xx o un 5xx."""
    if not isinstance(cuerpo, bytes):
        cuerpo = json.dumps(cuerpo).encode()
    return urllib.error.HTTPError(
        "http://identity:8000", codigo, "error", {}, io.BytesIO(cuerpo)
    )


class IdentidadFalsa:
    """Hace de Identidad: reemplaza llamadas.abrir (ver el fixture identidad).

    - GET /yo responde la cuenta registrada para el sub del token, como
      cuentas/vistas.py; aqui no hace falta verificar la firma. Si la cuenta
      no esta registrada o esta desactivada, 401 cuenta_inactiva.
    - POST /internal/avisos (HU-16) responde lo que fije la prueba en
      respuesta_aviso: por defecto, 204 sin cuerpo. Si es una excepcion, la
      lanza, como urllib.
    - Si la prueba la marca como caida, no conecta (URLError).
    - Anota cada peticion en pedidas, para contar las llamadas.

    D2 (HU-22) importa esta clase: no depende de los fixtures de este archivo.
    """

    def __init__(self):
        self.cuentas = {}  # usuario_id -> cuerpo de GET /yo
        self.desactivadas = set()
        self.caida = False
        self.respuesta_aviso = None
        self.pedidas = []  # cada urllib.request.Request, en orden

    def registrar(
        self,
        usuario_id,
        nombre="Camila",
        apellido="Rojas",
        nivel=2,
        carrera_id=CARRERA,
        sede_id=SEDE,
    ):
        """Una cuenta activa en Identidad. Devuelve su usuario_id."""
        self.cuentas[usuario_id] = {
            "id": str(usuario_id),
            "email": f"{nombre.lower()}.demo@duocuc.cl",
            "nombre": nombre,
            "apellido": apellido,
            "carrera_id": str(carrera_id) if carrera_id else None,
            "nivel": nivel,
            "sede_id": str(sede_id) if sede_id else None,
            "es_admin": False,
        }
        return usuario_id

    def a_yo(self):
        """La cabecera Authorization de cada GET /yo, en orden."""
        return [
            peticion.get_header("Authorization")
            for peticion in self.pedidas
            if peticion.full_url.endswith("/api/identity/v1/yo")
        ]

    def avisos(self):
        """El cuerpo de cada POST /internal/avisos, en orden."""
        return [
            json.loads(peticion.data)
            for peticion in self.pedidas
            if peticion.full_url.endswith("/api/identity/v1/internal/avisos")
        ]

    def abrir(self, peticion):
        self.pedidas.append(peticion)
        if self.caida:
            raise urllib.error.URLError(ConnectionRefusedError(111, "refused"))
        if peticion.full_url.endswith("/api/identity/v1/internal/avisos"):
            return self.aviso()
        if peticion.full_url.endswith("/api/identity/v1/yo"):
            return self.yo(peticion.get_header("Authorization"))
        # pytest.fail no hereda de Exception: pedir_aviso no la esconde.
        pytest.fail(f"Identidad no tiene {peticion.get_method()} {peticion.full_url}")

    def yo(self, autorizacion):
        token = autorizacion.split()[1]
        usuario_id = uuid.UUID(
            jwt.decode(token, options={"verify_signature": False})["sub"]
        )
        if usuario_id in self.desactivadas or usuario_id not in self.cuentas:
            raise error_http(
                401,
                {
                    "codigo": "cuenta_inactiva",
                    "mensaje": "La cuenta no existe o está desactivada.",
                    "detalles": None,
                },
            )
        return Respuesta(self.cuentas[usuario_id])

    def aviso(self):
        if self.respuesta_aviso is None:
            return Respuesta(b"", status=204)
        if isinstance(self.respuesta_aviso, BaseException):
            raise self.respuesta_aviso
        return self.respuesta_aviso


@pytest.fixture
def identidad(monkeypatch, settings):
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


def persona(nombre, apellido="Demo", activo=True):
    """Un usuario con copia en Tutorias, creado directo en la base."""
    return UsuarioRef.objects.create(
        usuario_id=uuid.uuid4(), nombre=nombre, apellido=apellido, activo=activo
    )


def estudiante(identidad, nombre="Camila", apellido="Rojas"):
    """Una cuenta activa en Identidad, todavia sin copia en Tutorias."""
    return identidad.registrar(uuid.uuid4(), nombre, apellido)


@pytest.fixture
def asignatura(db):
    return AsignaturaRef.objects.create(
        asignatura_id=uuid.uuid4(), sigla="BDD1101", nombre="Base de Datos"
    )


@pytest.fixture
def otra_asignatura(db):
    return AsignaturaRef.objects.create(
        asignatura_id=uuid.uuid4(), sigla="PRO1101", nombre="Programación de Algoritmos"
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
    """Reserva creada directo en la base, que cumple las reglas del modelo."""
    if estado in ESTADOS_QUE_OCUPAN:
        # RN-07: confirmada, realizada o evaluada, tiene modalidad y lugar.
        campos = {
            "modalidad": Modalidad.EN_LINEA,
            "lugar_o_enlace": "https://meet.example.com/prueba",
            "confirmada_en": timezone.now(),
            **campos,
        }
    return Reserva.objects.create(
        bloque=en_bloque,
        solicitante_usuario=solicitante,
        asignatura=asignatura,
        estado=estado,
        **campos,
    )


def en_utc(horas):
    """MANANA + horas, como lo escribe la API: en UTC, con Z y sin fraccion."""
    return (MANANA + timedelta(hours=horas)).strftime("%Y-%m-%dT%H:%M:%SZ")


def solicitar(client, encabezado, bloque_id, asignatura_id, **otros):
    return client.post(
        URL,
        {"bloque_id": str(bloque_id), "asignatura_id": str(asignatura_id), **otros},
        content_type="application/json",
        **encabezado,
    )


def error(respuesta):
    return respuesta.status_code, respuesta.json()["codigo"]


def claves(valor):
    """Todas las claves de un JSON, a cualquier profundidad."""
    if isinstance(valor, dict):
        for clave, contenido in valor.items():
            yield clave
            yield from claves(contenido)
    elif isinstance(valor, list):
        for elemento in valor:
            yield from claves(elemento)


def lineas_del_log(caplog):
    """Los mensajes que dejo llamadas.py en el log."""
    return [
        registro.getMessage()
        for registro in caplog.records
        if registro.name == llamadas.logger.name
    ]


# ------------------------------------------------------------ criterio 1 (RN-03)


@pytest.mark.django_db
def test_solicitar_un_bloque_libre_crea_una_reserva_solicitada(
    client, cabecera, identidad, tutora, libre, asignatura
):
    camila = estudiante(identidad, "Camila", "Rojas")

    respuesta = solicitar(
        client,
        cabecera(camila),
        libre.id,
        asignatura.asignatura_id,
        nota="  Me cuesta la tercera forma normal.  ",
    )

    assert respuesta.status_code == 201
    creada = Reserva.objects.get()
    cuerpo = respuesta.json()
    assert cuerpo == {
        "id": str(creada.id),
        "estado": "SOLICITADA",
        "nota": "Me cuesta la tercera forma normal.",
        "modalidad": None,
        "lugar_o_enlace": None,
        "monto": 5000,
        "estado_pago": None,
        "creada_en": cuerpo["creada_en"],
        "confirmada_en": None,
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
            "usuario_id": str(camila),
            "nombre": "Camila",
            "apellido": "Rojas",
        },
        "rol": "estudiante",
    }
    assert cuerpo["creada_en"].endswith("Z")
    assert (creada.estado, creada.solicitante_usuario_id, creada.bloque_id) == (
        EstadoReserva.SOLICITADA,
        camila,
        libre.id,
    )
    assert creada.nota == "Me cuesta la tercera forma normal."
    # RN-03: el bloque sigue LIBRE y sigue en el perfil publico del tutor.
    libre.refresh_from_db()
    assert libre.estado == EstadoBloque.LIBRE
    publico = client.get(f"{TUTORES}/{tutora.usuario_id}").json()
    assert [b["id"] for b in publico["bloques"]] == [str(libre.id)]


@pytest.mark.django_db
def test_otro_estudiante_puede_solicitar_el_mismo_bloque(
    client, cabecera, identidad, libre, asignatura
):
    camila = estudiante(identidad, "Camila", "Rojas")
    diego = estudiante(identidad, "Diego", "Herrera")

    primera = solicitar(client, cabecera(camila), libre.id, asignatura.asignatura_id)
    segunda = solicitar(client, cabecera(diego), libre.id, asignatura.asignatura_id)

    assert (primera.status_code, segunda.status_code) == (201, 201)
    pendientes = Reserva.objects.filter(bloque=libre, estado=EstadoReserva.SOLICITADA)
    assert {r.solicitante_usuario_id for r in pendientes} == {camila, diego}
    libre.refresh_from_db()
    assert libre.estado == EstadoBloque.LIBRE


@pytest.mark.django_db
@pytest.mark.parametrize(
    "otros, guardada",
    [
        ({}, None),
        ({"nota": None}, None),
        ({"nota": ""}, None),
        ({"nota": "   "}, None),
        ({"nota": "x" * 500}, "x" * 500),
        ({"nota": "  " + "x" * 500 + "  "}, "x" * 500),
    ],
    ids=["sin_nota", "null", "vacia", "en_blanco", "de_500", "de_500_con_espacios"],
)
def test_la_nota_es_opcional_y_en_blanco_queda_en_null(
    client, cabecera, identidad, libre, asignatura, otros, guardada
):
    camila = estudiante(identidad)

    respuesta = solicitar(
        client, cabecera(camila), libre.id, asignatura.asignatura_id, **otros
    )

    assert respuesta.status_code == 201
    assert respuesta.json()["nota"] == guardada
    assert Reserva.objects.get().nota == guardada


# ------------------------------------------------------------ criterio 2 (RN-03)


@pytest.mark.django_db
def test_el_tutor_no_solicita_su_propio_bloque(
    client, cabecera, identidad, tutora, libre, asignatura
):
    identidad.registrar(tutora.usuario_id, "Valentina", "Soto")

    respuesta = solicitar(client, cabecera(tutora), libre.id, asignatura.asignatura_id)

    assert error(respuesta) == (400, "bloque_propio")
    assert respuesta.json()["mensaje"] == (
        "No puedes solicitar una tutoría en tu propio bloque."
    )
    assert not Reserva.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "desde, hasta", [(-30, 30), (-120, -60)], ids=["en_curso", "ya_termino"]
)
def test_un_bloque_que_ya_empezo_no_se_solicita(
    client, cabecera, identidad, tutora, asignatura, desde, hasta
):
    ahora = timezone.now()
    empezado = BloqueDisponibilidad.objects.create(
        usuario=tutora,
        inicio_en=ahora + timedelta(minutes=desde),
        fin_en=ahora + timedelta(minutes=hasta),
    )
    camila = estudiante(identidad)

    respuesta = solicitar(
        client, cabecera(camila), empezado.id, asignatura.asignatura_id
    )

    assert error(respuesta) == (400, "bloque_en_el_pasado")
    assert not Reserva.objects.exists()


@pytest.mark.django_db
def test_un_bloque_con_tutoria_confirmada_responde_409(
    client, cabecera, identidad, tutora, asignatura
):
    ocupado = bloque(tutora, 1, 2, estado=EstadoBloque.OCUPADO)
    reserva(ocupado, persona("Diego", "Herrera"), asignatura, EstadoReserva.CONFIRMADA)
    camila = estudiante(identidad)

    respuesta = solicitar(
        client, cabecera(camila), ocupado.id, asignatura.asignatura_id
    )

    assert error(respuesta) == (409, "bloque_no_disponible")
    assert respuesta.json()["mensaje"] == (
        "Ese horario ya tiene una tutoría confirmada. Elige otro."
    )
    assert Reserva.objects.count() == 1


@pytest.mark.django_db
def test_un_bloque_eliminado_o_que_no_existe_responde_404(
    client, cabecera, identidad, tutora, asignatura
):
    eliminado = bloque(tutora, 1, 2, estado=EstadoBloque.ELIMINADO)
    encabezado = cabecera(estudiante(identidad))

    respuestas = [
        solicitar(client, encabezado, id_bloque, asignatura.asignatura_id)
        for id_bloque in (eliminado.id, uuid.uuid4())
    ]

    assert [error(r) for r in respuestas] == [(404, "bloque_no_encontrado")] * 2
    assert not Reserva.objects.exists()


# ------------------------------------------------------------ criterio 3


@pytest.mark.django_db
def test_una_segunda_solicitud_pendiente_al_mismo_bloque_responde_409(
    client, cabecera, identidad, libre, asignatura
):
    """La rechaza la base (ux_reserva_solicitud_unica) y aqui se traduce."""
    encabezado = cabecera(estudiante(identidad))

    primera = solicitar(client, encabezado, libre.id, asignatura.asignatura_id)
    segunda = solicitar(
        client, encabezado, libre.id, asignatura.asignatura_id, nota="Otra vez."
    )

    assert primera.status_code == 201
    assert error(segunda) == (409, "solicitud_duplicada")
    assert segunda.json()["mensaje"] == (
        "Ya tienes una solicitud pendiente para ese horario."
    )
    assert Reserva.objects.count() == 1
    assert Reserva.objects.get().nota is None


@pytest.mark.django_db
def test_si_la_primera_fue_rechazada_la_segunda_se_acepta(
    client, cabecera, identidad, libre, asignatura
):
    camila = estudiante(identidad)
    copia = UsuarioRef.objects.create(
        usuario_id=camila, nombre="Camila", apellido="Rojas"
    )
    rechazada = reserva(
        libre, copia, asignatura, EstadoReserva.RECHAZADA, cerrada_en=timezone.now()
    )

    respuesta = solicitar(client, cabecera(camila), libre.id, asignatura.asignatura_id)

    assert respuesta.status_code == 201
    assert respuesta.json()["id"] != str(rechazada.id)
    estados = Reserva.objects.filter(bloque=libre, solicitante_usuario=copia)
    assert sorted(r.estado for r in estados) == ["RECHAZADA", "SOLICITADA"]


@pytest.mark.django_db
def test_si_la_base_rechaza_la_reserva_del_propio_bloque_responde_400(
    tutora, libre, asignatura
):
    """El disparador trg_reserva_no_auto (ck_reserva_no_auto) es la ultima defensa."""
    with pytest.raises(Rechazo) as rechazo:
        guardar_solicitud(
            Reserva(bloque=libre, solicitante_usuario=tutora, asignatura=asignatura)
        )

    assert rechazo.value.status_code == 400
    assert rechazo.value.detail.code == "bloque_propio"
    assert not Reserva.objects.exists()


@pytest.mark.django_db
def test_otro_rechazo_de_la_base_no_se_disfraza(libre, asignatura):
    """Solo esas dos reglas se traducen: otro IntegrityError se relanza."""
    camila = persona("Camila", "Rojas")

    with pytest.raises(IntegrityError):
        guardar_solicitud(
            Reserva(
                bloque=libre,
                solicitante_usuario=camila,
                asignatura=asignatura,
                monto=-1,
            )
        )


# ------------------------------------------------------------ criterio 4 (AD-07)


@pytest.mark.django_db
def test_el_primer_contacto_crea_la_copia_con_una_llamada_a_identidad(
    client, cabecera, identidad, libre, asignatura
):
    camila = estudiante(identidad, "Camila", "Rojas")
    encabezado = cabecera(camila)
    assert not UsuarioRef.objects.filter(usuario_id=camila).exists()

    respuesta = solicitar(client, encabezado, libre.id, asignatura.asignatura_id)

    assert respuesta.status_code == 201
    copia = UsuarioRef.objects.get(usuario_id=camila)
    assert (copia.nombre, copia.apellido, copia.carrera_id, copia.sede_id) == (
        "Camila",
        "Rojas",
        CARRERA,
        SEDE,
    )
    assert copia.activo is True
    # Una sola llamada, a GET /yo, con el mismo token de la peticion.
    assert len(identidad.pedidas) == 1
    assert identidad.a_yo() == [encabezado["HTTP_AUTHORIZATION"]]


@pytest.mark.django_db
def test_si_ya_tenia_copia_queda_al_dia(client, cabecera, identidad, libre, asignatura):
    camila = estudiante(identidad, "Camila", "Rojas")
    UsuarioRef.objects.create(usuario_id=camila, nombre="Cami", apellido="R.")

    respuesta = solicitar(client, cabecera(camila), libre.id, asignatura.asignatura_id)

    assert respuesta.status_code == 201
    copia = UsuarioRef.objects.get(usuario_id=camila)
    assert (copia.nombre, copia.apellido, copia.carrera_id, copia.sede_id) == (
        "Camila",
        "Rojas",
        CARRERA,
        SEDE,
    )
    assert respuesta.json()["solicitante"] == {
        "usuario_id": str(camila),
        "nombre": "Camila",
        "apellido": "Rojas",
    }


@pytest.mark.django_db
def test_con_identidad_caida_responde_503_sin_reserva_ni_copia(
    client, cabecera, identidad, libre, asignatura
):
    camila = estudiante(identidad)
    identidad.caida = True

    respuesta = solicitar(client, cabecera(camila), libre.id, asignatura.asignatura_id)

    assert error(respuesta) == (503, "servicio_no_disponible")
    assert "servicio de Identidad" in respuesta.json()["mensaje"]
    assert not Reserva.objects.exists()
    assert not UsuarioRef.objects.filter(usuario_id=camila).exists()


@pytest.mark.django_db
def test_si_identidad_no_reconoce_la_cuenta_responde_403_sin_reserva(
    client, cabecera, identidad, libre, asignatura
):
    desactivada = estudiante(identidad, "Josefa", "Morales")
    UsuarioRef.objects.create(
        usuario_id=desactivada, nombre="Josefa", apellido="Morales"
    )
    identidad.desactivadas.add(desactivada)
    sin_cuenta = uuid.uuid4()

    respuestas = [
        solicitar(client, cabecera(quien), libre.id, asignatura.asignatura_id)
        for quien in (desactivada, sin_cuenta)
    ]

    assert [error(r) for r in respuestas] == [(403, "cuenta_inactiva")] * 2
    assert not Reserva.objects.exists()
    # RN-08: la copia que ya existia queda desactivada.
    assert UsuarioRef.objects.get(usuario_id=desactivada).activo is False
    assert not UsuarioRef.objects.filter(usuario_id=sin_cuenta).exists()


# ------------------------------------------------------------ criterio 5 (A-04)


@pytest.mark.django_db
def test_el_monto_es_la_tarifa_al_solicitar_y_queda_congelado(
    client, cabecera, identidad, tutora, libre, asignatura
):
    camila = estudiante(identidad)
    encabezado = cabecera(camila)

    respuesta = solicitar(client, encabezado, libre.id, asignatura.asignatura_id)
    PerfilTutor.objects.filter(usuario=tutora).update(tarifa=8000)
    detalle = client.get(f"{URL}/{respuesta.json()['id']}", **encabezado)

    assert (respuesta.json()["monto"], detalle.json()["monto"]) == (5000, 5000)
    creada = Reserva.objects.get()
    assert (creada.monto, creada.asignatura_id, creada.estado_pago) == (
        Decimal("5000"),
        asignatura.asignatura_id,
        None,
    )


@pytest.mark.django_db
def test_con_tarifa_0_el_monto_es_0_y_sin_estado_de_pago(
    client, cabecera, identidad, tutora, libre, otra_asignatura
):
    PerfilTutor.objects.create(usuario=tutora, asignatura=otra_asignatura, tarifa=0)
    camila = estudiante(identidad)

    respuesta = solicitar(
        client, cabecera(camila), libre.id, otra_asignatura.asignatura_id
    )

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert (cuerpo["monto"], cuerpo["estado_pago"]) == (0, None)
    assert cuerpo["asignatura"]["sigla"] == "PRO1101"
    creada = Reserva.objects.get()
    assert (creada.monto, creada.estado_pago, creada.asignatura_id) == (
        Decimal("0"),
        None,
        otra_asignatura.asignatura_id,
    )


# ------------------------------------------------------------ asignatura del tutor


def que_no_ofrece(tutora, otra_asignatura):
    return otra_asignatura.asignatura_id


def con_el_perfil_desactivado(tutora, otra_asignatura):
    PerfilTutor.objects.create(
        usuario=tutora, asignatura=otra_asignatura, tarifa=0, activo=False
    )
    return otra_asignatura.asignatura_id


def con_la_tutora_desactivada(tutora, otra_asignatura):
    PerfilTutor.objects.create(usuario=tutora, asignatura=otra_asignatura, tarifa=0)
    UsuarioRef.objects.filter(pk=tutora.pk).update(activo=False)
    return otra_asignatura.asignatura_id


def que_no_esta_en_tutorias(tutora, otra_asignatura):
    return uuid.uuid4()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "caso",
    [
        que_no_ofrece,
        con_el_perfil_desactivado,
        con_la_tutora_desactivada,
        que_no_esta_en_tutorias,
    ],
    ids=lambda caso: caso.__name__,
)
def test_una_asignatura_que_el_tutor_no_ofrece_responde_400(
    client, cabecera, identidad, tutora, libre, otra_asignatura, caso
):
    asignatura_id = caso(tutora, otra_asignatura)
    camila = estudiante(identidad)

    respuesta = solicitar(client, cabecera(camila), libre.id, asignatura_id)

    assert error(respuesta) == (400, "asignatura_no_ofrecida")
    assert respuesta.json()["mensaje"] == "El tutor no ofrece esa asignatura."
    assert not Reserva.objects.exists()


# ------------------------------------------------------------ el cuerpo y la sesion


@pytest.mark.django_db
@pytest.mark.parametrize(
    "cuerpo, codigo",
    [
        ({"asignatura_id": UNA_ASIGNATURA}, "bloque_invalido"),
        ({"bloque_id": "abc", "asignatura_id": UNA_ASIGNATURA}, "bloque_invalido"),
        ({"bloque_id": 7, "asignatura_id": UNA_ASIGNATURA}, "bloque_invalido"),
        ({"bloque_id": UN_BLOQUE}, "asignatura_invalida"),
        ({"bloque_id": UN_BLOQUE, "asignatura_id": "abc"}, "asignatura_invalida"),
        (
            {
                "bloque_id": UN_BLOQUE,
                "asignatura_id": UNA_ASIGNATURA,
                "nota": "x" * 501,
            },
            "nota_invalida",
        ),
        (
            {"bloque_id": UN_BLOQUE, "asignatura_id": UNA_ASIGNATURA, "nota": 5},
            "nota_invalida",
        ),
        (
            {"bloque_id": UN_BLOQUE, "asignatura_id": UNA_ASIGNATURA, "nota": "a\x00b"},
            "nota_invalida",
        ),
        (
            {"bloque_id": UN_BLOQUE, "asignatura_id": UNA_ASIGNATURA, "nota": "\ud800"},
            "nota_invalida",
        ),
        ({"bloque_id": "abc", "asignatura_id": "abc", "nota": 5}, "bloque_invalido"),
    ],
    ids=[
        "sin_bloque",
        "bloque_que_no_es_uuid",
        "bloque_numero",
        "sin_asignatura",
        "asignatura_que_no_es_uuid",
        "nota_de_501",
        "nota_numero",
        "nota_con_nulo",
        "nota_con_sustituto",
        "todo_mal_primero_el_bloque",
    ],
)
def test_valida_el_cuerpo_antes_de_llamar_a_identidad(
    client, cabecera, identidad, cuerpo, codigo
):
    camila = estudiante(identidad)

    respuesta = client.post(
        URL, cuerpo, content_type="application/json", **cabecera(camila)
    )

    assert error(respuesta) == (400, codigo)
    assert identidad.pedidas == []
    assert not UsuarioRef.objects.exists()


@pytest.mark.django_db
def test_sin_token_responde_401_sin_llamar_a_identidad(
    client, identidad, libre, asignatura
):
    respuestas = [
        client.post(
            URL,
            {
                "bloque_id": str(libre.id),
                "asignatura_id": str(asignatura.asignatura_id),
            },
            content_type="application/json",
        ),
        client.get(f"{URL}?rol=estudiante"),
        client.get(f"{URL}/{uuid.uuid4()}"),
    ]

    assert [error(r) for r in respuestas] == [(401, "not_authenticated")] * 3
    assert identidad.pedidas == []
    assert not Reserva.objects.exists()


# ------------------------------------------------------------ criterio 6 (HU-16)


@pytest.mark.django_db
def test_al_guardar_la_solicitud_pide_el_aviso_al_tutor(
    client,
    cabecera,
    identidad,
    aviso,
    django_capture_on_commit_callbacks,
    tutora,
    libre,
    asignatura,
):
    camila = estudiante(identidad)

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        respuesta = solicitar(
            client, cabecera(camila), libre.id, asignatura.asignatura_id
        )
        # Todavia no: el aviso sale cuando la transaccion se confirma.
        assert not aviso.called

    assert respuesta.status_code == 201
    assert len(callbacks) == 1
    aviso.assert_called_once_with(
        tutora.usuario_id, "SOLICITUD_RECIBIDA", Reserva.objects.get()
    )


@pytest.mark.django_db
def test_si_la_solicitud_falla_no_se_pide_el_aviso(
    client,
    cabecera,
    identidad,
    aviso,
    django_capture_on_commit_callbacks,
    tutora,
    libre,
    asignatura,
):
    camila = estudiante(identidad)
    copia = UsuarioRef.objects.create(
        usuario_id=camila, nombre="Camila", apellido="Rojas"
    )
    reserva(libre, copia, asignatura)
    identidad.registrar(tutora.usuario_id, "Valentina", "Soto")

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        duplicada = solicitar(
            client, cabecera(camila), libre.id, asignatura.asignatura_id
        )
        propia = solicitar(client, cabecera(tutora), libre.id, asignatura.asignatura_id)

    assert error(duplicada) == (409, "solicitud_duplicada")
    assert error(propia) == (400, "bloque_propio")
    assert callbacks == []
    assert not aviso.called


# ------------------------------------------------------------ pedir_aviso


@pytest.mark.django_db
def test_pedir_aviso_hace_un_post_a_identidad_con_la_clave_y_el_cuerpo(
    identidad, settings, caplog, tutora, libre, asignatura
):
    settings.CLAVE_SERVICIO = "clave-de-prueba"
    solicitud = reserva(
        libre,
        persona("Camila", "Rojas"),
        asignatura,
        nota="Me cuesta la tercera forma normal.",
        monto=Decimal("5000"),
    )

    resultado = pedir_aviso(tutora.usuario_id, "SOLICITUD_RECIBIDA", solicitud)

    assert resultado is True
    [peticion] = identidad.pedidas
    assert peticion.full_url == "http://identity:8000/api/identity/v1/internal/avisos"
    assert peticion.get_method() == "POST"
    # urllib guarda las cabeceras con str.capitalize().
    assert peticion.get_header("X-clave-servicio") == "clave-de-prueba"
    assert peticion.get_header("Authorization") is None
    assert peticion.get_header("Content-type") == "application/json"
    assert json.loads(peticion.data) == {
        "usuario_id": str(tutora.usuario_id),
        "plantilla": "SOLICITUD_RECIBIDA",
        "referencia_id": str(solicitud.id),
        "datos": {
            "asignatura": {"sigla": "BDD1101", "nombre": "Base de Datos"},
            "inicio_en": en_utc(1),
            "fin_en": en_utc(2),
            # Al tutor, la otra parte es quien solicito.
            "otra_persona": {"nombre": "Camila", "apellido": "Rojas"},
            "nota": "Me cuesta la tercera forma normal.",
            "modalidad": None,
            "lugar_o_enlace": None,
        },
    }
    assert lineas_del_log(caplog) == []


@pytest.mark.django_db
def test_al_solicitante_el_aviso_le_nombra_al_tutor(identidad, tutora, asignatura):
    """Lo que usaran HU-22 y HU-28: otra_persona es el tutor."""
    camila = persona("Camila", "Rojas")
    confirmada = reserva(
        bloque(tutora, 1, 2, estado=EstadoBloque.OCUPADO),
        camila,
        asignatura,
        EstadoReserva.CONFIRMADA,
    )

    assert pedir_aviso(camila.usuario_id, "RESERVA_CONFIRMADA", confirmada) is True

    [cuerpo] = identidad.avisos()
    assert (cuerpo["usuario_id"], cuerpo["plantilla"]) == (
        str(camila.usuario_id),
        "RESERVA_CONFIRMADA",
    )
    assert cuerpo["datos"]["otra_persona"] == {
        "nombre": "Valentina",
        "apellido": "Soto",
    }
    assert (cuerpo["datos"]["modalidad"], cuerpo["datos"]["lugar_o_enlace"]) == (
        "EN_LINEA",
        "https://meet.example.com/prueba",
    )


@pytest.mark.django_db
@pytest.mark.parametrize("estado", [200, 201, 202])
def test_con_un_2xx_el_aviso_no_deja_nada_en_el_log(
    identidad, caplog, tutora, libre, asignatura, estado
):
    solicitud = reserva(libre, persona("Camila", "Rojas"), asignatura)
    identidad.respuesta_aviso = Respuesta({}, status=estado)

    assert pedir_aviso(tutora.usuario_id, "SOLICITUD_RECIBIDA", solicitud) is True
    assert lineas_del_log(caplog) == []


PAGINA_404 = b"<!DOCTYPE html><title>Not Found</title>"
FALLAS_DEL_AVISO = {
    # Hoy Identidad no tiene la ruta: llega con HU-16.
    "ruta_que_no_existe": lambda: error_http(404, PAGINA_404),
    "error_500": lambda: error_http(500, b"<h1>Server Error (500)</h1>"),
    "no_contesta_a_tiempo": lambda: TimeoutError("timed out"),
    "no_conecta": lambda: urllib.error.URLError(ConnectionRefusedError(111, "refused")),
}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "falla", list(FALLAS_DEL_AVISO.values()), ids=list(FALLAS_DEL_AVISO)
)
def test_si_el_aviso_no_sale_no_lanza_nada_y_deja_una_linea_en_el_log(
    identidad, caplog, tutora, libre, asignatura, falla
):
    solicitud = reserva(libre, persona("Camila", "Rojas"), asignatura)
    identidad.respuesta_aviso = falla()

    assert pedir_aviso(tutora.usuario_id, "SOLICITUD_RECIBIDA", solicitud) is False

    lineas = lineas_del_log(caplog)
    assert any(
        "No salió el aviso SOLICITUD_RECIBIDA" in linea and str(solicitud.id) in linea
        for linea in lineas
    ), lineas
    assert {
        registro.levelno
        for registro in caplog.records
        if registro.name == llamadas.logger.name
    } == {logging.WARNING}


# ------------------------------------------------------------ GET /reservas


@pytest.mark.django_db
def test_con_rol_estudiante_ve_las_suyas_y_con_rol_tutor_las_de_sus_bloques(
    client, cabecera, identidad, tutora, asignatura
):
    camila = persona("Camila", "Rojas")
    diego = persona("Diego", "Herrera")
    matias = persona("Matías", "Fuentes")
    PerfilTutor.objects.create(usuario=matias, asignatura=asignatura, tarifa=3000)
    de_valentina = bloque(tutora, 1, 2)
    de_matias = bloque(matias, 1, 2, estado=EstadoBloque.OCUPADO)
    ahora = timezone.now()
    camila_a_valentina = reserva(
        de_valentina, camila, asignatura, creada_en=ahora - timedelta(days=3)
    )
    diego_a_valentina = reserva(
        de_valentina, diego, asignatura, creada_en=ahora - timedelta(days=1)
    )
    camila_a_matias = reserva(
        de_matias,
        camila,
        asignatura,
        EstadoReserva.CONFIRMADA,
        creada_en=ahora - timedelta(days=2),
        monto=Decimal("3000"),
    )

    def lista(quien, rol):
        respuesta = client.get(f"{URL}?rol={rol}", **cabecera(quien))
        assert respuesta.status_code == 200
        return [(r["id"], r["rol"]) for r in respuesta.json()]

    # De la mas nueva a la mas antigua.
    assert lista(camila, "estudiante") == [
        (str(camila_a_matias.id), "estudiante"),
        (str(camila_a_valentina.id), "estudiante"),
    ]
    assert lista(tutora, "tutor") == [
        (str(diego_a_valentina.id), "tutor"),
        (str(camila_a_valentina.id), "tutor"),
    ]
    assert lista(matias, "tutor") == [(str(camila_a_matias.id), "tutor")]
    assert lista(tutora, "estudiante") == []
    assert lista(camila, "tutor") == []
    assert identidad.pedidas == []


@pytest.mark.django_db
def test_estado_deja_solo_las_reservas_en_ese_estado(
    client, cabecera, tutora, asignatura
):
    camila = persona("Camila", "Rojas")
    pendiente = reserva(bloque(tutora, 1, 2), camila, asignatura)
    confirmada = reserva(
        bloque(tutora, 3, 4, estado=EstadoBloque.OCUPADO),
        camila,
        asignatura,
        EstadoReserva.CONFIRMADA,
    )

    def ids(quien, consulta):
        respuesta = client.get(f"{URL}{consulta}", **cabecera(quien))
        assert respuesta.status_code == 200
        return [r["id"] for r in respuesta.json()]

    assert ids(camila, "?rol=estudiante&estado=CONFIRMADA") == [str(confirmada.id)]
    assert ids(tutora, "?rol=tutor&estado=SOLICITADA") == [str(pendiente.id)]
    assert ids(tutora, "?rol=tutor&estado=EVALUADA") == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    "consulta, codigo",
    [
        ("", "rol_invalido"),
        ("?rol=", "rol_invalido"),
        ("?rol=admin", "rol_invalido"),
        ("?estado=SOLICITADA", "rol_invalido"),
        ("?rol=estudiante&estado=PENDIENTE", "estado_invalido"),
        ("?rol=estudiante&estado=solicitada", "estado_invalido"),
        ("?rol=tutor&estado=", "estado_invalido"),
    ],
    ids=[
        "sin_rol",
        "rol_vacio",
        "otro_rol",
        "solo_estado",
        "estado_que_no_existe",
        "estado_en_minusculas",
        "estado_vacio",
    ],
)
def test_la_lista_pide_un_rol_y_un_estado_validos(
    client, cabecera, identidad, consulta, codigo
):
    respuesta = client.get(f"{URL}{consulta}", **cabecera(uuid.uuid4()))

    assert error(respuesta) == (400, codigo)
    assert identidad.pedidas == []


@pytest.mark.django_db
def test_la_lista_trae_hasta_100_las_mas_nuevas_primero(
    client, cabecera, tutora, asignatura
):
    camila = persona("Camila", "Rojas")
    usado = bloque(tutora, 1, 2)
    desde = timezone.now() - timedelta(days=30)
    Reserva.objects.bulk_create(
        Reserva(
            bloque=usado,
            solicitante_usuario=camila,
            asignatura=asignatura,
            estado=EstadoReserva.RECHAZADA,
            creada_en=desde + timedelta(hours=hora),
        )
        for hora in range(101)
    )

    respuesta = client.get(f"{URL}?rol=estudiante", **cabecera(camila))

    lista = respuesta.json()
    assert len(lista) == 100
    fechas = [r["creada_en"] for r in lista]
    assert fechas == sorted(fechas, reverse=True)
    la_mas_antigua = Reserva.objects.order_by("creada_en").first()
    assert str(la_mas_antigua.id) not in {r["id"] for r in lista}


def consultas_de_la_lista(client, encabezado, rol):
    with CaptureQueriesContext(connection) as consultas:
        respuesta = client.get(f"{URL}?rol={rol}", **encabezado)
    assert respuesta.status_code == 200
    return len(consultas), len(respuesta.json())


@pytest.mark.django_db
@pytest.mark.parametrize("rol", ["estudiante", "tutor"])
def test_la_lista_no_hace_una_consulta_por_reserva(
    client, cabecera, identidad, tutora, asignatura, rol
):
    camila = persona("Camila", "Rojas")
    encabezado = cabecera(camila if rol == "estudiante" else tutora)
    reserva(bloque(tutora, 1, 2), camila, asignatura)
    consultas_con_una, cantidad = consultas_de_la_lista(client, encabezado, rol)
    assert cantidad == 1

    for desde in (3, 5):
        reserva(bloque(tutora, desde, desde + 1), camila, asignatura)
    consultas_con_tres, cantidad = consultas_de_la_lista(client, encabezado, rol)

    assert cantidad == 3
    assert consultas_con_tres == consultas_con_una
    assert identidad.pedidas == []


# ------------------------------------------------------------ GET /reservas/<id>


@pytest.mark.django_db
def test_el_detalle_es_solo_para_el_solicitante_y_el_tutor(
    client, cabecera, identidad, tutora, asignatura
):
    camila = persona("Camila", "Rojas")
    diego = persona("Diego", "Herrera")
    solicitud = reserva(bloque(tutora, 1, 2), camila, asignatura, nota="Repaso de SQL.")
    url = f"{URL}/{solicitud.id}"

    como_estudiante = client.get(url, **cabecera(camila))
    como_tutora = client.get(url, **cabecera(tutora))
    ajena = client.get(url, **cabecera(diego))
    inexistente = client.get(f"{URL}/{uuid.uuid4()}", **cabecera(camila))

    assert (como_estudiante.status_code, como_estudiante.json()["rol"]) == (
        200,
        "estudiante",
    )
    assert como_estudiante.json()["id"] == str(solicitud.id)
    assert (como_tutora.status_code, como_tutora.json()["rol"]) == (200, "tutor")
    assert como_tutora.json() == {**como_estudiante.json(), "rol": "tutor"}
    # Ajena o inexistente: la misma respuesta, sin revelar que existe.
    for respuesta in (ajena, inexistente):
        assert error(respuesta) == (404, "reserva_no_encontrada")
        assert respuesta.json()["mensaje"] == "No encontramos esa tutoría."
    assert identidad.pedidas == []


@pytest.mark.django_db
def test_una_reserva_confirmada_trae_la_modalidad_el_lugar_y_el_pago(
    client, cabecera, tutora, asignatura
):
    camila = persona("Camila", "Rojas")
    confirmada = reserva(
        bloque(tutora, 1, 2, estado=EstadoBloque.OCUPADO),
        camila,
        asignatura,
        EstadoReserva.CONFIRMADA,
        monto=Decimal("5000"),
        estado_pago=EstadoPago.PENDIENTE,
        confirmada_en=MANANA - timedelta(hours=20),
    )

    cuerpo = client.get(f"{URL}/{confirmada.id}", **cabecera(camila)).json()

    assert cuerpo == {
        "id": str(confirmada.id),
        "estado": "CONFIRMADA",
        "nota": None,
        "modalidad": "EN_LINEA",
        "lugar_o_enlace": "https://meet.example.com/prueba",
        "monto": 5000,
        "estado_pago": "PENDIENTE",
        "creada_en": cuerpo["creada_en"],
        "confirmada_en": en_utc(-20),
        "cerrada_en": None,
        "bloque": {
            "id": str(confirmada.bloque_id),
            "inicio_en": en_utc(1),
            "fin_en": en_utc(2),
        },
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


@pytest.mark.django_db
def test_ninguna_respuesta_trae_el_correo(
    client, cabecera, identidad, tutora, libre, asignatura
):
    """RNF-07: Identidad manda el correo en GET /yo, pero Tutorias no lo guarda."""
    encabezado = cabecera(estudiante(identidad))

    creada = solicitar(client, encabezado, libre.id, asignatura.asignatura_id)
    respuestas = [
        creada,
        client.get(f"{URL}?rol=estudiante", **encabezado),
        client.get(f"{URL}?rol=tutor", **cabecera(tutora)),
        client.get(f"{URL}/{creada.json()['id']}", **cabecera(tutora)),
    ]

    for respuesta in respuestas:
        assert respuesta.status_code in (200, 201)
        todas = list(claves(respuesta.json()))
        assert "usuario_id" in todas
        assert [c for c in todas if "email" in c or "correo" in c] == []
    # Solo la solicitud llamo a Identidad; las consultas, no.
    assert len(identidad.pedidas) == 1
