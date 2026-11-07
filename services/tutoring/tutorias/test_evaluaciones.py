import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.db import connections
from django.utils import timezone as tz
from rest_framework.test import APIClient

from tutorias.autenticacion import leer_clave
from tutorias.models import (
    ESTADOS_QUE_OCUPAN,
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
from tutorias.reputacion import recalcular_reputacion

ID_TUTOR = UUID("10000000-0000-4000-8000-000000000001")
ID_SOLICITANTE = UUID("10000000-0000-4000-8000-000000000002")
ID_AJENO = UUID("10000000-0000-4000-8000-000000000003")
ID_INEXISTENTE = UUID("99999999-9999-4999-8999-999999999999")

ID_ASIGNATURA = UUID("40000000-0000-4000-8000-000000000006")
ID_SEDE = UUID("20000000-0000-4000-8000-000000000001")


@pytest.fixture(scope="module")
def clave_de_identidad():
    """Hace de la clave privada de Identidad: firma los tokens de las pruebas."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def clave_publica(clave_de_identidad, settings, tmp_path):
    """Deja la clave pública en tmp_path y Tutorías la lee de ahí."""
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
    ahora = tz.now()
    reclamaciones = {
        "sub": str(usuario_id),
        "es_admin": False,
        "iat": int(ahora.timestamp()),
        "exp": int((ahora + timedelta(minutes=30)).timestamp()),
        "iss": "identity",
    }
    return jwt.encode(reclamaciones, clave, algorithm="RS256")


@pytest.fixture
def cliente_autenticado(clave_de_identidad):
    def _crear(usuario_id):
        cliente = APIClient()
        token = firmar(clave_de_identidad, usuario_id)
        cliente.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return cliente

    return _crear


def asegurar_usuario_ref(
    usuario_id,
    nombre="Diego",
    apellido="Rojas",
    reputacion_promedio=Decimal("0.00"),
    reputacion_total=0,
):
    usuario, _ = UsuarioRef.objects.update_or_create(
        usuario_id=usuario_id,
        defaults={
            "nombre": nombre,
            "apellido": apellido,
            "sede_id": ID_SEDE,
            "activo": True,
            "reputacion_promedio": reputacion_promedio,
            "reputacion_total": reputacion_total,
        },
    )
    return usuario


def crear_asignatura(
    asignatura_id=ID_ASIGNATURA, sigla="BDD1101", nombre="Base de Datos"
):
    asignatura, _ = AsignaturaRef.objects.get_or_create(
        asignatura_id=asignatura_id,
        defaults={"sigla": sigla, "nombre": nombre},
    )
    return asignatura


def crear_reserva(
    *,
    tutor_id=ID_TUTOR,
    solicitante_id=ID_SOLICITANTE,
    estado=EstadoReserva.REALIZADA,
    inicio_en=None,
    fin_en=None,
):
    asegurar_usuario_ref(tutor_id, nombre="Diego", apellido="Rojas")
    asegurar_usuario_ref(solicitante_id, nombre="Camila", apellido="Soto")
    crear_asignatura()
    ahora = tz.now().replace(microsecond=0)
    if inicio_en is None:
        inicio_en = ahora - timedelta(hours=3)
    if fin_en is None:
        fin_en = ahora - timedelta(hours=2)

    bloque = BloqueDisponibilidad.objects.create(
        usuario_id=tutor_id,
        inicio_en=inicio_en,
        fin_en=fin_en,
        estado=(
            EstadoBloque.OCUPADO if estado in ESTADOS_QUE_OCUPAN else EstadoBloque.LIBRE
        ),
    )
    confirmada = estado in ESTADOS_QUE_OCUPAN or estado == EstadoReserva.CANCELADA
    return Reserva.objects.create(
        bloque=bloque,
        solicitante_usuario_id=solicitante_id,
        asignatura_id=ID_ASIGNATURA,
        modalidad=Modalidad.EN_LINEA if confirmada else None,
        lugar_o_enlace="https://meet.example.com/bdd" if confirmada else None,
        monto=Decimal("4500"),
        estado=estado,
        confirmada_en=(inicio_en - timedelta(hours=1)) if confirmada else None,
        cerrada_en=fin_en if estado == EstadoReserva.REALIZADA else None,
    )


def url_evaluacion(reserva_id):
    return f"/api/tutoring/v1/reservas/{reserva_id}/evaluacion"


@pytest.mark.django_db
class TestEvaluar:
    def test_evalua_con_comentario_actualiza_reserva_y_reputacion(
        self, cliente_autenticado
    ):
        tutor = asegurar_usuario_ref(ID_TUTOR)
        PerfilTutor.objects.create(
            usuario_id=ID_TUTOR,
            asignatura=crear_asignatura(),
            tarifa=Decimal("4500"),
            activo=True,
        )
        reserva = crear_reserva()
        cliente = cliente_autenticado(ID_SOLICITANTE)

        respuesta = cliente.post(
            url_evaluacion(reserva.id),
            {"calificacion": 5, "comentario": "  Explicó claro y con ejercicios.  "},
            format="json",
        )

        assert respuesta.status_code == 201
        cuerpo = respuesta.json()
        assert cuerpo["reserva_id"] == str(reserva.id)
        assert cuerpo["calificacion"] == 5
        assert cuerpo["comentario"] == "Explicó claro y con ejercicios."
        assert cuerpo["creada_en"].endswith("Z")

        evaluacion = Evaluacion.objects.get(pk=cuerpo["id"])
        assert evaluacion.calificacion == 5
        assert evaluacion.comentario == "Explicó claro y con ejercicios."
        assert evaluacion.retirada_en is None

        reserva.refresh_from_db()
        assert reserva.estado == EstadoReserva.EVALUADA
        assert reserva.cerrada_en is not None

        tutor.refresh_from_db()
        assert tutor.reputacion_promedio == Decimal("5.00")
        assert tutor.reputacion_total == 1

        perfil = APIClient().get(f"/api/tutoring/v1/tutores/{ID_TUTOR}")
        assert perfil.status_code == 200
        datos_perfil = perfil.json()
        assert datos_perfil["reputacion"] == {"promedio": 5.0, "total": 1}
        assert len(datos_perfil["evaluaciones"]) == 1
        assert datos_perfil["evaluaciones"][0]["calificacion"] == 5
        assert (
            datos_perfil["evaluaciones"][0]["comentario"]
            == "Explicó claro y con ejercicios."
        )

    @pytest.mark.parametrize(
        "cuerpo_extra",
        [
            {},
            {"comentario": None},
            {"comentario": "   \n\t  "},
        ],
    )
    def test_evalua_sin_comentario_o_en_blanco_guarda_null(
        self, cliente_autenticado, cuerpo_extra
    ):
        reserva = crear_reserva()
        cliente = cliente_autenticado(ID_SOLICITANTE)

        datos = {"calificacion": 4, **cuerpo_extra}
        respuesta = cliente.post(url_evaluacion(reserva.id), datos, format="json")

        assert respuesta.status_code == 201
        assert respuesta.json()["comentario"] is None
        evaluacion = Evaluacion.objects.get(reserva=reserva)
        assert evaluacion.comentario is None

    def test_recalcula_reputacion_con_redondeo_half_up_y_sin_tocar_actualizado_en(
        self, cliente_autenticado
    ):
        ahora = tz.now().replace(microsecond=0)
        r1 = crear_reserva(
            inicio_en=ahora - timedelta(hours=8),
            fin_en=ahora - timedelta(hours=7),
        )
        r2 = crear_reserva(
            inicio_en=ahora - timedelta(hours=6),
            fin_en=ahora - timedelta(hours=5),
        )
        r3 = crear_reserva(
            inicio_en=ahora - timedelta(hours=4),
            fin_en=ahora - timedelta(hours=3),
        )

        # Evaluación previa retirada: no debe entrar al promedio ni al total
        r_retirada = crear_reserva(
            inicio_en=ahora - timedelta(hours=12),
            fin_en=ahora - timedelta(hours=11),
            estado=EstadoReserva.EVALUADA,
        )
        Evaluacion.objects.create(
            reserva=r_retirada,
            calificacion=1,
            comentario="Retirada",
            retirada_en=ahora - timedelta(hours=10),
            retirada_por_usuario_id=ID_SOLICITANTE,
        )

        instante_fijo = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
        UsuarioRef.objects.filter(pk=ID_TUTOR).update(actualizado_en=instante_fijo)
        tutor = UsuarioRef.objects.get(pk=ID_TUTOR)

        cliente = cliente_autenticado(ID_SOLICITANTE)

        # (5 + 4) / 2 = 4.50
        assert (
            cliente.post(
                url_evaluacion(r1.id), {"calificacion": 5}, format="json"
            ).status_code
            == 201
        )
        assert (
            cliente.post(
                url_evaluacion(r2.id), {"calificacion": 4}, format="json"
            ).status_code
            == 201
        )
        tutor.refresh_from_db()
        assert tutor.reputacion_promedio == Decimal("4.50")
        assert tutor.reputacion_total == 2
        assert tutor.actualizado_en == instante_fijo

        # (5 + 4 + 5) / 3 = 4.666... -> 4.67
        assert (
            cliente.post(
                url_evaluacion(r3.id), {"calificacion": 5}, format="json"
            ).status_code
            == 201
        )
        tutor.refresh_from_db()
        assert tutor.reputacion_promedio == Decimal("4.67")
        assert tutor.reputacion_total == 3
        assert tutor.actualizado_en == instante_fijo

    def test_recalcular_reputacion_sin_evaluaciones_activas_da_cero(self):
        tutor = asegurar_usuario_ref(
            ID_TUTOR, reputacion_promedio=Decimal("4.50"), reputacion_total=2
        )
        promedio, total = recalcular_reputacion(ID_TUTOR)
        assert promedio == Decimal("0.00")
        assert total == 0
        tutor.refresh_from_db()
        assert tutor.reputacion_promedio == Decimal("0.00")
        assert tutor.reputacion_total == 0

    @pytest.mark.parametrize(
        "cuerpo",
        [
            {},
            {"calificacion": None},
            {"calificacion": 0},
            {"calificacion": 6},
            {"calificacion": -1},
            {"calificacion": 4.5},
            {"calificacion": "5"},
            {"calificacion": True},
            {"calificacion": False},
            {"calificacion": [5]},
        ],
    )
    def test_calificacion_invalida_responde_400(self, cliente_autenticado, cuerpo):
        reserva = crear_reserva()
        cliente = cliente_autenticado(ID_SOLICITANTE)

        respuesta = cliente.post(url_evaluacion(reserva.id), cuerpo, format="json")

        assert respuesta.status_code == 400
        assert respuesta.json() == {
            "codigo": "calificacion_invalida",
            "mensaje": "La nota tiene que ser un número entero de 1 a 5.",
            "detalles": None,
        }
        assert Evaluacion.objects.count() == 0

    @pytest.mark.parametrize(
        "comentario,mensaje_esperado",
        [
            (123, "El comentario puede tener hasta 500 caracteres."),
            (["hola"], "El comentario puede tener hasta 500 caracteres."),
            ("a" * 501, "El comentario puede tener hasta 500 caracteres."),
            (
                "hola\x00mundo",
                "El comentario tiene caracteres que no se pueden guardar.",
            ),
            (
                "hola\ud800mundo",
                "El comentario tiene caracteres que no se pueden guardar.",
            ),
        ],
    )
    def test_comentario_invalido_responde_400(
        self, client, clave_de_identidad, comentario, mensaje_esperado
    ):
        reserva = crear_reserva()
        token = firmar(clave_de_identidad, ID_SOLICITANTE)

        respuesta = client.post(
            url_evaluacion(reserva.id),
            {"calificacion": 5, "comentario": comentario},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        assert respuesta.status_code == 400
        assert respuesta.json() == {
            "codigo": "comentario_invalido",
            "mensaje": mensaje_esperado,
            "detalles": None,
        }
        assert Evaluacion.objects.count() == 0

    def test_comentario_de_500_caracteres_con_espacios_laterales_es_valido(
        self, cliente_autenticado
    ):
        reserva = crear_reserva()
        cliente = cliente_autenticado(ID_SOLICITANTE)
        texto_500 = "x" * 500

        respuesta = cliente.post(
            url_evaluacion(reserva.id),
            {"calificacion": 5, "comentario": f"   {texto_500}   "},
            format="json",
        )

        assert respuesta.status_code == 201
        assert respuesta.json()["comentario"] == texto_500

    def test_sin_token_responde_401(self):
        reserva = crear_reserva()
        respuesta = APIClient().post(
            url_evaluacion(reserva.id), {"calificacion": 5}, format="json"
        )
        assert respuesta.status_code == 401
        assert respuesta.json()["codigo"] == "not_authenticated"

    def test_reserva_inexistente_o_de_tercero_responde_404_identico(
        self, cliente_autenticado
    ):
        reserva = crear_reserva()
        cliente_ajeno = cliente_autenticado(ID_AJENO)

        r_inexistente = cliente_ajeno.post(
            url_evaluacion(ID_INEXISTENTE), {"calificacion": 5}, format="json"
        )
        r_ajena = cliente_ajeno.post(
            url_evaluacion(reserva.id), {"calificacion": 5}, format="json"
        )

        esperado = {
            "codigo": "reserva_no_encontrada",
            "mensaje": "No encontramos esa tutoría.",
            "detalles": None,
        }
        assert r_inexistente.status_code == 404
        assert r_ajena.status_code == 404
        assert r_inexistente.json() == esperado
        assert r_ajena.json() == esperado

    def test_el_tutor_no_puede_evaluar_su_propia_tutoria_403(self, cliente_autenticado):
        reserva = crear_reserva()
        cliente_tutor = cliente_autenticado(ID_TUTOR)

        respuesta = cliente_tutor.post(
            url_evaluacion(reserva.id), {"calificacion": 5}, format="json"
        )

        assert respuesta.status_code == 403
        assert respuesta.json() == {
            "codigo": "solo_el_solicitante",
            "mensaje": "Solo quien pidió la tutoría puede evaluarla.",
            "detalles": None,
        }

    def test_evaluar_por_segunda_vez_responde_409_reserva_ya_evaluada(
        self, cliente_autenticado
    ):
        reserva = crear_reserva()
        cliente = cliente_autenticado(ID_SOLICITANTE)

        primera = cliente.post(
            url_evaluacion(reserva.id), {"calificacion": 5}, format="json"
        )
        assert primera.status_code == 201

        segunda = cliente.post(
            url_evaluacion(reserva.id), {"calificacion": 1}, format="json"
        )
        assert segunda.status_code == 409
        assert segunda.json() == {
            "codigo": "reserva_ya_evaluada",
            "mensaje": "Ya evaluaste esta tutoría.",
            "detalles": None,
        }
        assert Evaluacion.objects.filter(reserva=reserva).count() == 1

    @pytest.mark.parametrize(
        "estado",
        [
            EstadoReserva.SOLICITADA,
            EstadoReserva.CONFIRMADA,
            EstadoReserva.RECHAZADA,
            EstadoReserva.EXPIRADA,
            EstadoReserva.CANCELADA,
        ],
    )
    def test_reserva_en_estado_no_realizada_responde_409(
        self, cliente_autenticado, estado
    ):
        reserva = crear_reserva(estado=estado)
        cliente = cliente_autenticado(ID_SOLICITANTE)

        respuesta = cliente.post(
            url_evaluacion(reserva.id), {"calificacion": 5}, format="json"
        )

        assert respuesta.status_code == 409
        assert respuesta.json() == {
            "codigo": "reserva_no_realizada",
            "mensaje": "Solo se puede evaluar una tutoría realizada.",
            "detalles": None,
        }

    def test_bloque_que_aun_no_termina_responde_409_tutoria_no_terminada(
        self, cliente_autenticado
    ):
        ahora = tz.now().replace(microsecond=0)
        reserva = crear_reserva(
            estado=EstadoReserva.REALIZADA,
            inicio_en=ahora - timedelta(minutes=30),
            fin_en=ahora + timedelta(minutes=30),
        )
        cliente = cliente_autenticado(ID_SOLICITANTE)

        respuesta = cliente.post(
            url_evaluacion(reserva.id), {"calificacion": 5}, format="json"
        )

        assert respuesta.status_code == 409
        assert respuesta.json() == {
            "codigo": "tutoria_no_terminada",
            "mensaje": "Podrás evaluarla cuando termine la tutoría.",
            "detalles": None,
        }


@pytest.mark.django_db(transaction=True)
def test_concurrencia_dos_evaluaciones_simultaneas_una_201_y_una_409(
    clave_de_identidad,
):
    reserva = crear_reserva()
    token = firmar(clave_de_identidad, ID_SOLICITANTE)

    barrera = threading.Barrier(2)
    resultados = []
    candado = threading.Lock()

    def enviar(nota):
        try:
            cliente = APIClient()
            cliente.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
            barrera.wait(timeout=5)
            respuesta = cliente.post(
                url_evaluacion(reserva.id),
                {"calificacion": nota, "comentario": f"Nota {nota}"},
                format="json",
            )
            with candado:
                resultados.append((respuesta.status_code, respuesta.json()))
        finally:
            connections.close_all()

    hilo_1 = threading.Thread(target=enviar, args=(5,))
    hilo_2 = threading.Thread(target=enviar, args=(3,))
    hilo_1.start()
    hilo_2.start()
    hilo_1.join(timeout=10)
    hilo_2.join(timeout=10)

    estados = sorted(estado for estado, _ in resultados)
    assert estados == [201, 409]

    cuerpo_409 = next(cuerpo for estado, cuerpo in resultados if estado == 409)
    assert cuerpo_409["codigo"] == "reserva_ya_evaluada"

    assert Evaluacion.objects.filter(reserva=reserva).count() == 1
    tutor = UsuarioRef.objects.get(pk=ID_TUTOR)
    assert tutor.reputacion_total == 1
