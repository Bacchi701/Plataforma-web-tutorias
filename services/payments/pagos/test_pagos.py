"""Pruebas de la API publica de Pagos (vistas.py, HU-23, criterios 1 a 5).

Corren contra PostgreSQL. Tutorias no esta: TutoriasFalsa reemplaza
llamadas.abrir con monkeypatch. Guarda las reservas que fija cada prueba, con
el formato de la ruta interna (tutorias/internas.py), responde el GET interno,
anota cada PATCH y responde lo que fije la prueba. Los tokens se firman con un
par RSA propio, como en test_autenticacion.py. Los avisos a Tutorias corren
despues del commit: las pruebas los ejecutan con
django_capture_on_commit_callbacks(execute=True).
"""

import io
import json
import urllib.error
import urllib.parse
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.db import IntegrityError
from django.utils import timezone

from . import llamadas
from .autenticacion import leer_clave
from .models import EstadoPago, IntentoPago, Pago, ResultadoIntento, TipoIntento
from .vistas import avisar_a_tutorias, guardar_nuevo

URL = "/api/payments/v1/pagos"
CLAVE = "clave-de-prueba"
INTERNA = "/api/tutoring/v1/internal/reservas/"
# Quien pide la tutoria, la tutora y otro estudiante.
CAMILA = uuid.uuid4()
VALENTINA = uuid.uuid4()
DIEGO = uuid.uuid4()
RECHAZADO = "Pago rechazado en la simulación."
AUTOMATICO = "Reembolso automático: la reserva se canceló mientras se pagaba."
CAMPOS_DEL_PAGO = {
    "id",
    "reserva_id",
    "monto",
    "estado",
    "proveedor",
    "creado_en",
    "actualizado_en",
    "intentos",
}


# ------------------------------------------------------------ Tutorias falsa


def como_bytes(cuerpo):
    return cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo).encode()


class Respuesta(io.BytesIO):
    """Lo que entrega abrir() con un 2xx: se usa con with y trae status."""

    def __init__(self, cuerpo, status=200):
        super().__init__(como_bytes(cuerpo))
        self.status = status


def error_http(codigo, cuerpo):
    """Lo que lanza abrir() con un 4xx o un 5xx."""
    return urllib.error.HTTPError(
        "http://tutoring:8000", codigo, "error", {}, io.BytesIO(como_bytes(cuerpo))
    )


@dataclass
class Aviso:
    """Un PATCH que recibio TutoriasFalsa."""

    reserva_id: str
    cuerpo: dict
    cabeceras: dict


class TutoriasFalsa:
    """Hace de Tutorias en las dos rutas internas que usa Pagos."""

    def __init__(self):
        self.reservas = {}
        self.consultas = []
        self.avisos = []
        # al_aviso(cuerpo) fija la respuesta al PATCH: una Respuesta, una
        # excepcion o None (200 aplicado true).
        self.al_aviso = None
        self.caida = False

    def fijar(self, estado="CONFIRMADA", monto=5000):
        """Una reserva de Camila con Valentina, como la da la ruta interna."""
        reserva_id = uuid.uuid4()
        self.reservas[str(reserva_id)] = {
            "id": str(reserva_id),
            "estado": estado,
            "monto": monto,
            "estado_pago": None,
            "pago_actualizado_en": None,
            "solicitante_usuario_id": str(CAMILA),
            "tutor_usuario_id": str(VALENTINA),
        }
        return reserva_id

    def abrir(self, peticion):
        if self.caida:
            raise urllib.error.URLError(ConnectionRefusedError(111, "refused"))
        metodo = peticion.get_method()
        ruta = urllib.parse.urlsplit(peticion.full_url).path
        reserva_id, _, resto = ruta.removeprefix(INTERNA).partition("/")
        if not ruta.startswith(INTERNA) or (metodo, resto) not in {
            ("GET", ""),
            ("PATCH", "estado-pago"),
        }:
            # pytest.fail no hereda de Exception: informar_estado no la esconde.
            pytest.fail(f"TutoriasFalsa no tiene {metodo} {ruta}")
        if metodo == "GET":
            self.consultas.append(peticion)
            if reserva_id not in self.reservas:
                raise error_http(
                    404,
                    {
                        "codigo": "reserva_no_encontrada",
                        "mensaje": "No existe una reserva con ese identificador.",
                        "detalles": None,
                    },
                )
            return Respuesta(self.reservas[reserva_id])
        cuerpo = json.loads(peticion.data)
        self.avisos.append(Aviso(reserva_id, cuerpo, dict(peticion.header_items())))
        respuesta = self.al_aviso(cuerpo) if self.al_aviso else None
        if respuesta is None:
            aplicado = {"aplicado": True, "estado_pago": cuerpo["estado_pago"]}
            respuesta = Respuesta(aplicado)
        if isinstance(respuesta, BaseException):
            raise respuesta
        return respuesta

    def estados_avisados(self):
        return [aviso.cuerpo["estado_pago"] for aviso in self.avisos]


@pytest.fixture(autouse=True)
def tutorias(monkeypatch, settings):
    # En la integracion continua CLAVE_SERVICIO no existe: se fija aqui.
    settings.URL_TUTORIAS = "http://tutoring:8000"
    settings.CLAVE_SERVICIO = CLAVE
    falsa = TutoriasFalsa()
    monkeypatch.setattr(llamadas, "abrir", falsa.abrir)
    return falsa


def cancelada_al_pagar(cuerpo):
    """Tutorias no aplica el PAGADO: la reserva se cancelo mientras se pagaba."""
    if cuerpo["estado_pago"] != "PAGADO":
        return None
    return error_http(
        409,
        {
            "codigo": "reserva_cancelada",
            "mensaje": "La reserva está cancelada: el pago se reembolsa.",
            "detalles": None,
        },
    )


# ------------------------------------------------------------ tokens


@pytest.fixture(scope="module")
def clave_de_identidad():
    """Hace de la clave privada de Identidad: firma los tokens de las pruebas."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def clave_publica(clave_de_identidad, settings, tmp_path):
    """Deja la clave publica en tmp_path y Pagos la lee de ahi."""
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


def firmar(clave, usuario_id):
    """Token con las reclamaciones que pone Identidad (cuentas/tokens.py)."""
    ahora = timezone.now()
    reclamaciones = {
        "sub": str(usuario_id),
        "es_admin": False,
        "iat": int(ahora.timestamp()),
        "exp": int((ahora + timedelta(minutes=30)).timestamp()),
        "iss": "identity",
    }
    return jwt.encode(reclamaciones, clave, algorithm="RS256")


@pytest.fixture
def cabecera(clave_de_identidad):
    """Authorization: Bearer con un token de Identidad para ese usuario."""

    def para(usuario_id):
        token = firmar(clave_de_identidad, usuario_id)
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    return para


# ------------------------------------------------------------ ayudas


def crear(client, cabecera, usuario_id, reserva_id):
    return client.post(
        URL,
        {"reserva_id": str(reserva_id)},
        content_type="application/json",
        **cabecera(usuario_id),
    )


def consultar(client, cabecera, usuario_id, reserva_id):
    return client.get(URL, {"reserva": str(reserva_id)}, **cabecera(usuario_id))


def simular(client, cabecera, usuario_id, pago_id, resultado):
    return client.post(
        f"{URL}/{pago_id}/simular",
        {"resultado": resultado},
        content_type="application/json",
        **cabecera(usuario_id),
    )


def pago_en(reserva_id, estado=EstadoPago.PENDIENTE, notificado=True):
    """Un pago guardado directo en la base, con su aviso ya marcado o no."""
    return Pago.objects.create(
        reserva_id=reserva_id,
        monto=5000,
        estado=estado,
        notificado_en=timezone.now() if notificado else None,
    )


def cobro_exitoso(pago):
    return IntentoPago.objects.create(
        pago=pago, tipo=TipoIntento.COBRO, resultado=ResultadoIntento.EXITOSO
    )


def intentos_de(pago):
    """(tipo, resultado, mensaje) de cada intento, del mas nuevo al mas antiguo."""
    intentos = pago.intentos.order_by("-creado_en", "-id")
    return list(intentos.values_list("tipo", "resultado", "mensaje"))


def preciso(instante):
    """El actualizado_en que manda Pagos: UTC, con microsegundos y con Z."""
    return instante.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def error(codigo, mensaje):
    return {"codigo": codigo, "mensaje": mensaje, "detalles": None}


# ------------------------------------------------------------ criterios 1 a 5


@pytest.mark.django_db
def test_c1_el_solicitante_crea_el_pago_pendiente_y_tutorias_recibe_el_aviso(
    client, cabecera, tutorias, django_capture_on_commit_callbacks
):
    reserva_id = tutorias.fijar(monto=5000)

    with django_capture_on_commit_callbacks(execute=True):
        respuesta = crear(client, cabecera, CAMILA, reserva_id)

    assert respuesta.status_code == 201
    datos = respuesta.json()
    pago = Pago.objects.get(reserva_id=reserva_id)
    assert set(datos) == CAMPOS_DEL_PAGO
    assert (datos["id"], datos["reserva_id"]) == (str(pago.id), str(reserva_id))
    assert (datos["estado"], datos["monto"], datos["proveedor"]) == (
        "PENDIENTE",
        5000,
        "SIMULADO",
    )
    # monto entero: 5000.0 seria igual a 5000, pero no es un int.
    assert isinstance(datos["monto"], int)
    assert datos["intentos"] == []
    # Las fechas de la API publica van en UTC, con Z y sin fraccion.
    datetime.strptime(datos["creado_en"], "%Y-%m-%dT%H:%M:%SZ")
    datetime.strptime(datos["actualizado_en"], "%Y-%m-%dT%H:%M:%SZ")
    # Pagos pidio la reserva a la ruta interna, con la clave y sin el token.
    [consulta] = tutorias.consultas
    assert consulta.get_header("X-clave-servicio") == CLAVE
    assert consulta.get_header("Authorization") is None
    # Despues del commit, un PATCH PENDIENTE con el actualizado_en del pago.
    [aviso] = tutorias.avisos
    assert aviso.reserva_id == str(reserva_id)
    assert aviso.cuerpo == {
        "estado_pago": "PENDIENTE",
        "actualizado_en": preciso(pago.actualizado_en),
    }
    assert aviso.cabeceras["X-clave-servicio"] == CLAVE
    assert pago.notificado_en is not None


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("resultado", "estado", "mensaje"),
    [("EXITOSO", "PAGADO", None), ("FALLIDO", "FALLIDO", RECHAZADO)],
    ids=["exitoso", "fallido"],
)
def test_c2_simular_deja_el_pago_pagado_o_fallido_con_su_intento(
    client,
    cabecera,
    tutorias,
    django_capture_on_commit_callbacks,
    resultado,
    estado,
    mensaje,
):
    pago = pago_en(tutorias.fijar())

    with django_capture_on_commit_callbacks(execute=True):
        respuesta = simular(client, cabecera, CAMILA, pago.id, resultado)

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["estado"] == estado
    [intento] = datos["intentos"]
    assert (intento["tipo"], intento["resultado"], intento["mensaje"]) == (
        "COBRO",
        resultado,
        mensaje,
    )
    pago.refresh_from_db()
    assert pago.estado == estado
    assert intentos_de(pago) == [("COBRO", resultado, mensaje)]


@pytest.mark.django_db
def test_c3_un_pago_fallido_se_reintenta_sobre_el_mismo_pago(
    client, cabecera, tutorias, django_capture_on_commit_callbacks
):
    pago = pago_en(tutorias.fijar())

    with django_capture_on_commit_callbacks(execute=True):
        fallido = simular(client, cabecera, CAMILA, pago.id, "FALLIDO")
    with django_capture_on_commit_callbacks(execute=True):
        exitoso = simular(client, cabecera, CAMILA, pago.id, "EXITOSO")

    assert fallido.json()["estado"] == "FALLIDO"
    datos = exitoso.json()
    assert (datos["id"], datos["estado"]) == (str(pago.id), "PAGADO")
    # Dos intentos sobre el mismo pago, el mas nuevo primero.
    assert [(i["tipo"], i["resultado"]) for i in datos["intentos"]] == [
        ("COBRO", "EXITOSO"),
        ("COBRO", "FALLIDO"),
    ]
    assert Pago.objects.count() == 1


@pytest.mark.django_db
def test_c4_crear_y_simular_avisan_cada_cambio_con_instantes_que_crecen(
    client, cabecera, tutorias, django_capture_on_commit_callbacks
):
    reserva_id = tutorias.fijar()

    with django_capture_on_commit_callbacks(execute=True):
        pago_id = crear(client, cabecera, CAMILA, reserva_id).json()["id"]
    for resultado in ("FALLIDO", "EXITOSO"):
        with django_capture_on_commit_callbacks(execute=True):
            simular(client, cabecera, CAMILA, pago_id, resultado)

    assert tutorias.estados_avisados() == ["PENDIENTE", "FALLIDO", "PAGADO"]
    assert {aviso.reserva_id for aviso in tutorias.avisos} == {str(reserva_id)}
    instantes = [
        datetime.fromisoformat(aviso.cuerpo["actualizado_en"])
        for aviso in tutorias.avisos
    ]
    assert instantes[0] < instantes[1] < instantes[2]
    pago = Pago.objects.get(pk=pago_id)
    assert instantes[2] == pago.actualizado_en
    assert pago.notificado_en is not None


FALLAS_DEL_AVISO = {
    "tutorias_caida": lambda cuerpo: urllib.error.URLError(
        ConnectionRefusedError(111, "refused")
    ),
    "error_500": lambda cuerpo: error_http(500, b"<h1>Server Error (500)</h1>"),
    "no_contesta_a_tiempo": lambda cuerpo: TimeoutError("timed out"),
}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "al_aviso", list(FALLAS_DEL_AVISO.values()), ids=list(FALLAS_DEL_AVISO)
)
def test_c4_si_el_aviso_falla_el_pago_cambia_igual_y_queda_sin_notificar(
    client, cabecera, tutorias, django_capture_on_commit_callbacks, caplog, al_aviso
):
    reserva_id = tutorias.fijar()
    tutorias.al_aviso = al_aviso

    with django_capture_on_commit_callbacks(execute=True):
        creado = crear(client, cabecera, CAMILA, reserva_id)
    pago = Pago.objects.get(reserva_id=reserva_id)
    assert creado.status_code == 201
    assert (pago.estado, pago.notificado_en) == ("PENDIENTE", None)

    with django_capture_on_commit_callbacks(execute=True):
        simulado = simular(client, cabecera, CAMILA, pago.id, "EXITOSO")
    pago.refresh_from_db()
    assert simulado.status_code == 200
    assert (pago.estado, pago.notificado_en) == ("PAGADO", None)

    assert tutorias.estados_avisados() == ["PENDIENTE", "PAGADO"]
    assert "No salió el aviso PAGADO" in caplog.text


@pytest.mark.django_db
def test_c5_una_reserva_gratuita_no_tiene_pago(
    client, cabecera, tutorias, django_capture_on_commit_callbacks
):
    reserva_id = tutorias.fijar(monto=0)

    with django_capture_on_commit_callbacks(execute=True):
        respuesta = crear(client, cabecera, CAMILA, reserva_id)

    assert respuesta.status_code == 409
    assert respuesta.json() == error(
        "sin_pago", "Esta tutoría es gratuita: no tiene pago."
    )
    assert not Pago.objects.exists()
    assert tutorias.avisos == []


# ------------------------------------------------------------ crear


@pytest.mark.django_db
def test_crear_dos_veces_devuelve_el_mismo_pago(
    client, cabecera, tutorias, django_capture_on_commit_callbacks
):
    reserva_id = tutorias.fijar()

    with django_capture_on_commit_callbacks(execute=True):
        primero = crear(client, cabecera, CAMILA, reserva_id)
    with django_capture_on_commit_callbacks(execute=True):
        segundo = crear(client, cabecera, CAMILA, reserva_id)

    assert (primero.status_code, segundo.status_code) == (201, 200)
    assert segundo.json()["id"] == primero.json()["id"]
    assert Pago.objects.count() == 1
    # El aviso del primero salio: el segundo no lo repite.
    assert tutorias.estados_avisados() == ["PENDIENTE"]


@pytest.mark.django_db
def test_si_la_base_rechaza_un_segundo_pago_guardar_nuevo_devuelve_el_que_quedo():
    # Dos peticiones a la vez: la otra ya guardo el pago de esta reserva.
    reserva_id = uuid.uuid4()
    existente = Pago.objects.create(reserva_id=reserva_id, monto=5000)

    pago, creado = guardar_nuevo(Pago(reserva_id=reserva_id, monto=5000))

    assert creado is False
    assert pago.pk == existente.pk
    assert Pago.objects.count() == 1


@pytest.mark.django_db
def test_guardar_nuevo_deja_pasar_otro_integrity_error():
    # ck_pago_monto (RN-05): no es la restriccion de un pago por reserva.
    with pytest.raises(IntegrityError):
        guardar_nuevo(Pago(reserva_id=uuid.uuid4(), monto=0))


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("usuario", "existe"),
    [(VALENTINA, True), (DIEGO, True), (CAMILA, False)],
    ids=["tutora", "otro_estudiante", "reserva_que_no_existe"],
)
def test_quien_no_pidio_la_tutoria_no_crea_el_pago(
    client, cabecera, tutorias, usuario, existe
):
    reserva_id = tutorias.fijar() if existe else uuid.uuid4()

    respuesta = crear(client, cabecera, usuario, reserva_id)

    assert respuesta.status_code == 404
    assert respuesta.json() == error(
        "reserva_no_encontrada", "No tienes una reserva con ese identificador."
    )
    assert not Pago.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("estado", ["SOLICITADA", "RECHAZADA", "EXPIRADA", "CANCELADA"])
def test_una_reserva_que_no_esta_confirmada_no_se_paga(
    client, cabecera, tutorias, estado
):
    reserva_id = tutorias.fijar(estado=estado)

    respuesta = crear(client, cabecera, CAMILA, reserva_id)

    assert respuesta.status_code == 409
    assert respuesta.json() == error(
        "reserva_no_confirmada", "Solo se paga una tutoría confirmada."
    )
    assert not Pago.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("estado", ["REALIZADA", "EVALUADA"])
def test_una_tutoria_realizada_o_evaluada_sin_pago_se_paga(
    client, cabecera, tutorias, django_capture_on_commit_callbacks, estado
):
    # Criterio 7: el pago no depende de la sesion.
    reserva_id = tutorias.fijar(estado=estado)

    with django_capture_on_commit_callbacks(execute=True):
        respuesta = crear(client, cabecera, CAMILA, reserva_id)

    assert respuesta.status_code == 201
    assert respuesta.json()["estado"] == "PENDIENTE"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "cuerpo",
    [{}, {"reserva_id": None}, {"reserva_id": "abc"}, {"reserva_id": 123}],
    ids=["falta", "nulo", "texto", "numero"],
)
def test_un_reserva_id_invalido_responde_400_sin_llamar_a_tutorias(
    client, cabecera, tutorias, cuerpo
):
    respuesta = client.post(
        URL, cuerpo, content_type="application/json", **cabecera(CAMILA)
    )

    assert respuesta.status_code == 400
    assert respuesta.json() == error(
        "reserva_invalida", "Indica la reserva que quieres pagar."
    )
    assert tutorias.consultas == []
    assert not Pago.objects.exists()


@pytest.mark.django_db
def test_si_tutorias_no_responde_no_se_crea_el_pago(client, cabecera, tutorias):
    reserva_id = tutorias.fijar()
    tutorias.caida = True

    respuesta = crear(client, cabecera, CAMILA, reserva_id)

    assert respuesta.status_code == 503
    datos = respuesta.json()
    assert datos["codigo"] == "servicio_no_disponible"
    assert "servicio de Tutorías" in datos["mensaje"]
    assert not Pago.objects.exists()


# ------------------------------------------------------------ consultar


@pytest.mark.django_db
@pytest.mark.parametrize("usuario", [CAMILA, VALENTINA], ids=["solicitante", "tutora"])
def test_el_solicitante_y_la_tutora_consultan_el_pago(
    client, cabecera, tutorias, usuario
):
    reserva_id = tutorias.fijar()
    pago = pago_en(reserva_id)

    respuesta = consultar(client, cabecera, usuario, reserva_id)

    assert respuesta.status_code == 200
    assert respuesta.json()["id"] == str(pago.id)


@pytest.mark.django_db
def test_otro_estudiante_no_ve_el_pago(client, cabecera, tutorias):
    reserva_id = tutorias.fijar()
    pago_en(reserva_id)

    respuesta = consultar(client, cabecera, DIEGO, reserva_id)

    assert respuesta.status_code == 404
    assert respuesta.json() == error(
        "pago_no_encontrado", "Esta reserva todavía no tiene pago."
    )


@pytest.mark.django_db
def test_consultar_una_reserva_sin_pago_responde_404_sin_llamar_a_tutorias(
    client, cabecera, tutorias
):
    reserva_id = tutorias.fijar()

    respuesta = consultar(client, cabecera, CAMILA, reserva_id)

    assert respuesta.status_code == 404
    assert respuesta.json() == error(
        "pago_no_encontrado", "Esta reserva todavía no tiene pago."
    )
    assert tutorias.consultas == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    "parametros",
    [{}, {"reserva": "abc"}, {"reserva": ""}],
    ids=["falta", "texto", "vacia"],
)
def test_consultar_sin_una_reserva_valida_responde_400(
    client, cabecera, tutorias, parametros
):
    respuesta = client.get(URL, parametros, **cabecera(CAMILA))

    assert respuesta.status_code == 400
    assert respuesta.json()["codigo"] == "reserva_invalida"
    assert tutorias.consultas == []


# ------------------------------------------------------------ simular


@pytest.mark.django_db
@pytest.mark.parametrize("usuario", [VALENTINA, DIEGO], ids=["tutora", "otro"])
def test_solo_quien_pidio_la_tutoria_simula_el_pago(
    client, cabecera, tutorias, usuario
):
    pago = pago_en(tutorias.fijar())

    respuesta = simular(client, cabecera, usuario, pago.id, "EXITOSO")

    assert respuesta.status_code == 404
    assert respuesta.json() == error(
        "pago_no_encontrado", "No tienes un pago con ese identificador."
    )
    pago.refresh_from_db()
    assert pago.estado == "PENDIENTE"
    assert not pago.intentos.exists()


@pytest.mark.django_db
def test_simular_un_pago_que_no_existe_responde_404_sin_llamar_a_tutorias(
    client, cabecera, tutorias
):
    respuesta = simular(client, cabecera, CAMILA, uuid.uuid4(), "EXITOSO")

    assert respuesta.status_code == 404
    assert respuesta.json()["codigo"] == "pago_no_encontrado"
    assert tutorias.consultas == []


@pytest.mark.django_db
@pytest.mark.parametrize("estado", ["PAGADO", "REEMBOLSADO"])
def test_simular_un_pago_pagado_o_reembolsado_responde_409(
    client, cabecera, tutorias, django_capture_on_commit_callbacks, estado
):
    pago = pago_en(tutorias.fijar(), estado=estado)
    antes = pago.actualizado_en

    with django_capture_on_commit_callbacks(execute=True):
        respuesta = simular(client, cabecera, CAMILA, pago.id, "EXITOSO")

    assert respuesta.status_code == 409
    assert respuesta.json() == error(
        "pago_no_simulable", "Este pago ya está pagado o reembolsado."
    )
    pago.refresh_from_db()
    assert (pago.estado, pago.actualizado_en) == (estado, antes)
    assert not pago.intentos.exists()
    assert tutorias.avisos == []


@pytest.mark.django_db
@pytest.mark.parametrize("estado", ["CANCELADA", "RECHAZADA", "EXPIRADA"])
def test_simular_una_tutoria_que_ya_no_esta_vigente_responde_409(
    client, cabecera, tutorias, estado
):
    pago = pago_en(tutorias.fijar(estado=estado))

    respuesta = simular(client, cabecera, CAMILA, pago.id, "EXITOSO")

    assert respuesta.status_code == 409
    assert respuesta.json() == error(
        "reserva_no_confirmada", "Esta tutoría ya no está vigente: no se puede pagar."
    )
    pago.refresh_from_db()
    assert pago.estado == "PENDIENTE"
    assert not pago.intentos.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("estado", ["REALIZADA", "EVALUADA"])
def test_simular_una_tutoria_ya_realizada_se_puede(
    client, cabecera, tutorias, django_capture_on_commit_callbacks, estado
):
    # Criterio 7: el pago no depende de la sesion.
    pago = pago_en(tutorias.fijar(estado=estado))

    with django_capture_on_commit_callbacks(execute=True):
        respuesta = simular(client, cabecera, CAMILA, pago.id, "EXITOSO")

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "PAGADO"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "cuerpo",
    [{}, {"resultado": None}, {"resultado": "OK"}, {"resultado": "exitoso"}],
    ids=["falta", "nulo", "otro", "minusculas"],
)
def test_un_resultado_invalido_responde_400_sin_llamar_a_tutorias(
    client, cabecera, tutorias, cuerpo
):
    pago = pago_en(tutorias.fijar())

    respuesta = client.post(
        f"{URL}/{pago.id}/simular",
        cuerpo,
        content_type="application/json",
        **cabecera(CAMILA),
    )

    assert respuesta.status_code == 400
    assert respuesta.json() == error(
        "resultado_invalido",
        "Indica el resultado de la simulación: EXITOSO o FALLIDO.",
    )
    assert tutorias.consultas == []
    assert not pago.intentos.exists()


# ------------------------------------------------------------ sin sesion


@pytest.mark.django_db
def test_sin_token_responde_401_con_el_desafio_de_pagos(client, tutorias):
    reserva_id = tutorias.fijar()
    pago = pago_en(reserva_id)

    respuestas = [
        client.post(
            URL, {"reserva_id": str(reserva_id)}, content_type="application/json"
        ),
        client.get(URL, {"reserva": str(reserva_id)}),
        client.post(
            f"{URL}/{pago.id}/simular",
            {"resultado": "EXITOSO"},
            content_type="application/json",
        ),
    ]

    for respuesta in respuestas:
        assert respuesta.status_code == 401
        assert respuesta["WWW-Authenticate"] == 'Bearer realm="payments"'
        assert respuesta.json()["codigo"] == "not_authenticated"
    assert tutorias.consultas == []


# ------------------------------------- la carrera entre pagar y cancelar


@pytest.mark.django_db
def test_si_la_reserva_se_cancelo_mientras_se_pagaba_el_pago_se_reembolsa_solo(
    client, cabecera, tutorias, django_capture_on_commit_callbacks, caplog
):
    pago = pago_en(tutorias.fijar())
    tutorias.al_aviso = cancelada_al_pagar

    with django_capture_on_commit_callbacks(execute=True):
        respuesta = simular(client, cabecera, CAMILA, pago.id, "EXITOSO")

    assert respuesta.status_code == 200
    pago.refresh_from_db()
    assert pago.estado == "REEMBOLSADO"
    assert intentos_de(pago) == [
        ("REEMBOLSO", "EXITOSO", AUTOMATICO),
        ("COBRO", "EXITOSO", None),
    ]
    # El PAGADO que Tutorias no aplico, y despues el REEMBOLSADO, que si.
    assert tutorias.estados_avisados() == ["PAGADO", "REEMBOLSADO"]
    assert pago.notificado_en is not None
    assert "Reembolso automático del pago" in caplog.text


@pytest.mark.django_db
def test_si_hu28_ya_reembolso_el_pago_no_hay_un_segundo_reembolso(
    tutorias, django_capture_on_commit_callbacks
):
    pago = pago_en(tutorias.fijar(estado="CANCELADA"), estado=EstadoPago.PAGADO)
    cobro_exitoso(pago)
    # El aviso lleva el pago PAGADO, pero entretanto HU-28 pidio el reembolso.
    Pago.objects.filter(pk=pago.pk).update(estado=EstadoPago.REEMBOLSADO)
    IntentoPago.objects.create(
        pago=pago, tipo=TipoIntento.REEMBOLSO, resultado=ResultadoIntento.EXITOSO
    )
    tutorias.al_aviso = cancelada_al_pagar

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        avisar_a_tutorias(pago)

    assert callbacks == []
    assert tutorias.estados_avisados() == ["PAGADO"]
    pago.refresh_from_db()
    assert pago.estado == "REEMBOLSADO"
    assert [tipo for tipo, _, _ in intentos_de(pago)] == ["REEMBOLSO", "COBRO"]


# ------------------------------------------------------------ el reintento


@pytest.mark.django_db
@pytest.mark.parametrize("peticion", [consultar, crear], ids=["consultar", "crear"])
def test_abrir_el_pago_reenvia_el_aviso_que_no_salio_y_lo_marca(
    client, cabecera, tutorias, django_capture_on_commit_callbacks, peticion
):
    reserva_id = tutorias.fijar()
    pago = pago_en(reserva_id, estado=EstadoPago.PAGADO, notificado=False)

    with django_capture_on_commit_callbacks(execute=True):
        respuesta = peticion(client, cabecera, CAMILA, reserva_id)

    assert respuesta.status_code == 200
    [aviso] = tutorias.avisos
    assert aviso.cuerpo == {
        "estado_pago": "PAGADO",
        "actualizado_en": preciso(pago.actualizado_en),
    }
    pago.refresh_from_db()
    assert pago.notificado_en is not None


@pytest.mark.django_db
@pytest.mark.parametrize("peticion", [consultar, crear], ids=["consultar", "crear"])
def test_con_el_aviso_ya_marcado_no_se_reenvia(
    client, cabecera, tutorias, django_capture_on_commit_callbacks, peticion
):
    reserva_id = tutorias.fijar()
    pago_en(reserva_id, estado=EstadoPago.PAGADO)

    with django_capture_on_commit_callbacks(execute=True):
        respuesta = peticion(client, cabecera, CAMILA, reserva_id)

    assert respuesta.status_code == 200
    assert tutorias.avisos == []


@pytest.mark.django_db
def test_un_pagado_sin_aviso_sobre_una_reserva_cancelada_queda_reembolsado(
    client, cabecera, tutorias, django_capture_on_commit_callbacks
):
    # El aviso PAGADO no llego y despues Camila cancelo: al abrir el pago se
    # reenvia, Tutorias responde reserva_cancelada y Pagos lo reembolsa solo.
    reserva_id = tutorias.fijar(estado="CANCELADA")
    pago = pago_en(reserva_id, estado=EstadoPago.PAGADO, notificado=False)
    cobro_exitoso(pago)
    tutorias.al_aviso = cancelada_al_pagar

    with django_capture_on_commit_callbacks(execute=True):
        respuesta = consultar(client, cabecera, CAMILA, reserva_id)

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["estado"] == "REEMBOLSADO"
    assert [(i["tipo"], i["mensaje"]) for i in datos["intentos"]] == [
        ("REEMBOLSO", AUTOMATICO),
        ("COBRO", None),
    ]
    assert tutorias.estados_avisados() == ["PAGADO", "REEMBOLSADO"]
    pago.refresh_from_db()
    assert pago.notificado_en is not None
