import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.db import IntegrityError, connection, connections
from django.test.utils import CaptureQueriesContext
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
ID_OTRO_ESTUDIANTE = UUID("10000000-0000-4000-8000-000000000004")
ID_ADMIN = UUID("10000000-0000-4000-8000-000000000008")

ID_ASIGNATURA = UUID("40000000-0000-4000-8000-000000000006")
ID_ASIGNATURA_REDES = UUID("40000000-0000-4000-8000-000000000010")
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
    usuario, _ = UsuarioRef.objects.get_or_create(
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
    asignatura_id=ID_ASIGNATURA,
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
        asignatura_id=asignatura_id,
        modalidad=Modalidad.EN_LINEA if confirmada else None,
        lugar_o_enlace="https://meet.example.com/bdd" if confirmada else None,
        monto=Decimal("4500"),
        estado=estado,
        confirmada_en=(inicio_en - timedelta(hours=1)) if confirmada else None,
        # HU-29 deja la REALIZADA sin cerrada_en: lo escribe la evaluacion.
        cerrada_en=None,
    )


def foto(reserva):
    """Lo que un rechazo no puede cambiar: reserva, evaluaciones y reputacion."""
    reserva.refresh_from_db()
    tutor = UsuarioRef.objects.get(pk=reserva.bloque.usuario_id)
    return (
        reserva.estado,
        reserva.cerrada_en,
        Evaluacion.objects.count(),
        tutor.reputacion_promedio,
        tutor.reputacion_total,
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
        assert reserva.cerrada_en is not None  # la REALIZADA llega sin cerrada_en

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
            (123, "El comentario tiene que ser un texto."),
            (["hola"], "El comentario tiene que ser un texto."),
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
        antes = foto(reserva)
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
        assert foto(reserva) == antes

    def test_el_tutor_no_puede_evaluar_su_propia_tutoria_403(self, cliente_autenticado):
        reserva = crear_reserva()
        antes = foto(reserva)
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
        assert foto(reserva) == antes

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
        primera_guardada = Evaluacion.objects.get(reserva=reserva)
        assert primera_guardada.calificacion == 5
        tutor = UsuarioRef.objects.get(pk=ID_TUTOR)
        assert (tutor.reputacion_promedio, tutor.reputacion_total) == (
            Decimal("5.00"),
            1,
        )

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
        antes = foto(reserva)
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
        assert foto(reserva) == antes

    def test_bloque_que_aun_no_termina_responde_409_tutoria_no_terminada(
        self, cliente_autenticado
    ):
        ahora = tz.now().replace(microsecond=0)
        reserva = crear_reserva(
            estado=EstadoReserva.REALIZADA,
            inicio_en=ahora - timedelta(minutes=30),
            fin_en=ahora + timedelta(minutes=30),
        )
        antes = foto(reserva)
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
        assert foto(reserva) == antes

    def test_bloque_terminado_hace_un_minuto_y_nota_1_se_aceptan(
        self, cliente_autenticado
    ):
        ahora = tz.now()
        reserva = crear_reserva(
            inicio_en=ahora - timedelta(minutes=61),
            fin_en=ahora - timedelta(minutes=1),
        )
        cliente = cliente_autenticado(ID_SOLICITANTE)

        respuesta = cliente.post(
            url_evaluacion(reserva.id), {"calificacion": 1}, format="json"
        )

        assert respuesta.status_code == 201
        reserva.refresh_from_db()
        assert reserva.estado == EstadoReserva.EVALUADA
        assert reserva.cerrada_en >= ahora

    def test_reputacion_no_cuenta_otro_tutor_y_junta_asignaturas(
        self, cliente_autenticado
    ):
        ahora = tz.now().replace(microsecond=0)
        crear_asignatura(ID_ASIGNATURA_REDES, "RED1101", "Fundamentos de Redes")
        base_de_datos = crear_reserva(
            inicio_en=ahora - timedelta(hours=6), fin_en=ahora - timedelta(hours=5)
        )
        redes = crear_reserva(
            inicio_en=ahora - timedelta(hours=4),
            fin_en=ahora - timedelta(hours=3),
            asignatura_id=ID_ASIGNATURA_REDES,
        )
        de_otro_tutor = crear_reserva(
            tutor_id=ID_AJENO,
            inicio_en=ahora - timedelta(hours=4),
            fin_en=ahora - timedelta(hours=3),
        )
        UsuarioRef.objects.filter(pk=ID_TUTOR).update(
            actualizado_en=datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        )
        cliente = cliente_autenticado(ID_SOLICITANTE)

        for reserva, nota in ((base_de_datos, 5), (redes, 4), (de_otro_tutor, 1)):
            respuesta = cliente.post(
                url_evaluacion(reserva.id), {"calificacion": nota}, format="json"
            )
            assert respuesta.status_code == 201

        tutor = UsuarioRef.objects.get(pk=ID_TUTOR)
        assert (tutor.reputacion_promedio, tutor.reputacion_total) == (
            Decimal("4.50"),
            2,
        )
        assert tutor.actualizado_en == datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        otro = UsuarioRef.objects.get(pk=ID_AJENO)
        assert (otro.reputacion_promedio, otro.reputacion_total) == (
            Decimal("1.00"),
            1,
        )

    def test_recalcular_no_cuenta_evaluaciones_retiradas(self, cliente_autenticado):
        ahora = tz.now().replace(microsecond=0)
        visible = crear_reserva(
            inicio_en=ahora - timedelta(hours=6), fin_en=ahora - timedelta(hours=5)
        )
        a_retirar = crear_reserva(
            inicio_en=ahora - timedelta(hours=4), fin_en=ahora - timedelta(hours=3)
        )
        cliente = cliente_autenticado(ID_SOLICITANTE)
        for reserva, nota in ((visible, 5), (a_retirar, 1)):
            respuesta = cliente.post(
                url_evaluacion(reserva.id), {"calificacion": nota}, format="json"
            )
            assert respuesta.status_code == 201
        assert recalcular_reputacion(ID_TUTOR) == (Decimal("3.00"), 2)

        # Lo que hara DELETE /admin/evaluaciones/{id} (HU-33), directo en la base.
        Evaluacion.objects.filter(reserva=a_retirar).update(
            retirada_en=tz.now(), retirada_por_usuario_id=ID_ADMIN
        )
        assert recalcular_reputacion(ID_TUTOR) == (Decimal("5.00"), 1)

        Evaluacion.objects.filter(reserva=visible).update(
            retirada_en=tz.now(), retirada_por_usuario_id=ID_ADMIN
        )
        assert recalcular_reputacion(ID_TUTOR) == (Decimal("0.00"), 0)
        tutor = UsuarioRef.objects.get(pk=ID_TUTOR)
        assert (tutor.reputacion_promedio, tutor.reputacion_total) == (
            Decimal("0.00"),
            0,
        )


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
            resultado = (respuesta.status_code, respuesta.json())
        except Exception as error:
            resultado = (error, None)
        finally:
            connections.close_all()
        with candado:
            resultados.append(resultado)

    hilo_1 = threading.Thread(target=enviar, args=(5,))
    hilo_2 = threading.Thread(target=enviar, args=(3,))
    hilo_1.start()
    hilo_2.start()
    hilo_1.join(timeout=10)
    hilo_2.join(timeout=10)

    assert all(isinstance(estado, int) for estado, _ in resultados), resultados
    estados = sorted(estado for estado, _ in resultados)
    assert estados == [201, 409]

    cuerpo_409 = next(cuerpo for estado, cuerpo in resultados if estado == 409)
    assert cuerpo_409["codigo"] == "reserva_ya_evaluada"

    assert Evaluacion.objects.filter(reserva=reserva).count() == 1
    tutor = UsuarioRef.objects.get(pk=ID_TUTOR)
    assert tutor.reputacion_total == 1


@pytest.mark.django_db(transaction=True)
def test_concurrencia_dos_reservas_del_mismo_tutor_cuentan_las_dos(
    clave_de_identidad,
):
    ahora = tz.now().replace(microsecond=0)
    primera = crear_reserva(
        inicio_en=ahora - timedelta(hours=6), fin_en=ahora - timedelta(hours=5)
    )
    segunda = crear_reserva(
        solicitante_id=ID_OTRO_ESTUDIANTE,
        inicio_en=ahora - timedelta(hours=4),
        fin_en=ahora - timedelta(hours=3),
    )
    barrera = threading.Barrier(2)
    resultados = []
    candado = threading.Lock()

    def evaluar(reserva, estudiante_id, nota):
        try:
            cliente = APIClient()
            token = firmar(clave_de_identidad, estudiante_id)
            cliente.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
            barrera.wait(timeout=5)
            resultado = cliente.post(
                url_evaluacion(reserva.id), {"calificacion": nota}, format="json"
            ).status_code
        except Exception as error:
            resultado = error
        finally:
            connections.close_all()
        with candado:
            resultados.append(resultado)

    hilos = [
        threading.Thread(target=evaluar, args=(primera, ID_SOLICITANTE, 5)),
        threading.Thread(target=evaluar, args=(segunda, ID_OTRO_ESTUDIANTE, 4)),
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=15)

    assert resultados == [201, 201]
    tutor = UsuarioRef.objects.get(pk=ID_TUTOR)
    assert (tutor.reputacion_promedio, tutor.reputacion_total) == (
        Decimal("4.50"),
        2,
    )


# ----------------------------------- HU-27, criterio 1: lo que faltaba (parte 2)


def evaluacion_sin_revision_previa(**forzados):
    """Hace de Evaluacion dentro de tutorias/evaluaciones.py.

    Su revision previa no ve la evaluacion que ya existe, como si las dos
    llegaran a la vez, y su create es el de verdad: el INSERT llega a la base,
    que es la que decide. forzados cambia campos de ese INSERT.
    """

    def crear(**campos):
        return Evaluacion.objects.create(**{**campos, **forzados})

    return SimpleNamespace(
        objects=SimpleNamespace(
            filter=lambda **condiciones: Evaluacion.objects.none(), create=crear
        )
    )


@pytest.mark.django_db
class TestReglasDeEvaluar:
    def test_la_misma_reserva_se_evalua_recien_cuando_termina_el_bloque(
        self, cliente_autenticado
    ):
        # Solo despues de bloque.fin_en, sin margen: un minuto antes, 409; un
        # minuto despues, 201.
        ahora = tz.now()
        reserva = crear_reserva(
            inicio_en=ahora - timedelta(minutes=59),
            fin_en=ahora + timedelta(minutes=1),
        )
        antes = foto(reserva)
        cliente = cliente_autenticado(ID_SOLICITANTE)

        respuesta = cliente.post(
            url_evaluacion(reserva.id), {"calificacion": 4}, format="json"
        )

        assert respuesta.status_code == 409
        assert respuesta.json()["codigo"] == "tutoria_no_terminada"
        assert foto(reserva) == antes

        BloqueDisponibilidad.objects.filter(pk=reserva.bloque_id).update(
            inicio_en=ahora - timedelta(minutes=61),
            fin_en=ahora - timedelta(minutes=1),
        )
        respuesta = cliente.post(
            url_evaluacion(reserva.id), {"calificacion": 4}, format="json"
        )

        assert respuesta.status_code == 201
        reserva.refresh_from_db()
        assert reserva.estado == EstadoReserva.EVALUADA

    def test_una_reserva_realizada_que_ya_tiene_evaluacion_responde_409(
        self, cliente_autenticado
    ):
        # Una sola vez, aunque la reserva siga REALIZADA (por ejemplo, si la
        # evaluacion se cargo a mano): cuenta la fila de evaluacion.
        reserva = crear_reserva()
        Evaluacion.objects.create(reserva=reserva, calificacion=5)
        antes = foto(reserva)

        with CaptureQueriesContext(connection) as consultas:
            respuesta = cliente_autenticado(ID_SOLICITANTE).post(
                url_evaluacion(reserva.id), {"calificacion": 1}, format="json"
            )

        assert respuesta.status_code == 409
        assert respuesta.json() == {
            "codigo": "reserva_ya_evaluada",
            "mensaje": "Ya evaluaste esta tutoría.",
            "detalles": None,
        }
        assert foto(reserva) == antes
        # Lo corto la revision previa: ni siquiera se intento el INSERT.
        assert not any(
            'INSERT INTO "evaluacion"' in consulta["sql"]
            for consulta in consultas.captured_queries
        )

    def test_si_la_base_rechaza_la_evaluacion_repetida_responde_409(
        self, cliente_autenticado, monkeypatch
    ):
        # La ultima defensa es la restriccion unica de evaluacion.reserva_id.
        # Si RESTRICCION_EVALUACION_UNICA no fuera su nombre real, saldria 500.
        reserva = crear_reserva()
        Evaluacion.objects.create(reserva=reserva, calificacion=5)
        antes = foto(reserva)
        monkeypatch.setattr(
            "tutorias.evaluaciones.Evaluacion", evaluacion_sin_revision_previa()
        )

        respuesta = cliente_autenticado(ID_SOLICITANTE).post(
            url_evaluacion(reserva.id), {"calificacion": 1}, format="json"
        )

        assert respuesta.status_code == 409
        assert respuesta.json()["codigo"] == "reserva_ya_evaluada"
        assert foto(reserva) == antes

    @pytest.mark.parametrize("forzada", [9, None])
    def test_otro_rechazo_de_la_base_no_se_disfraza_de_evaluacion_repetida(
        self, cliente_autenticado, monkeypatch, forzada
    ):
        # Una nota que la base no acepta no es una evaluacion repetida: el error
        # sigue su camino y no queda nada escrito. Con 9 la rechaza
        # ck_evaluacion_calificacion; con None, el NOT NULL, que en PostgreSQL 16
        # llega sin nombre de restriccion (el respaldo de es_evaluacion_duplicada).
        reserva = crear_reserva()
        antes = foto(reserva)
        monkeypatch.setattr(
            "tutorias.evaluaciones.Evaluacion",
            evaluacion_sin_revision_previa(calificacion=forzada),
        )

        with pytest.raises(IntegrityError):
            cliente_autenticado(ID_SOLICITANTE).post(
                url_evaluacion(reserva.id), {"calificacion": 4}, format="json"
            )

        assert foto(reserva) == antes

    @pytest.mark.parametrize("cuerpo", [[{"calificacion": 5}], 5])
    def test_un_cuerpo_que_no_es_un_objeto_json_responde_400(
        self, cliente_autenticado, cuerpo
    ):
        reserva = crear_reserva()
        antes = foto(reserva)

        respuesta = cliente_autenticado(ID_SOLICITANTE).post(
            url_evaluacion(reserva.id), cuerpo, format="json"
        )

        assert respuesta.status_code == 400
        assert respuesta.json()["codigo"] == "calificacion_invalida"
        assert foto(reserva) == antes


# ------------------------------ GET /tutores/<id>/evaluaciones (HU-25, criterio 4)

# Los bloques de estas pruebas se cuentan en dias hacia atras desde ayer a
# mediodia (UTC): cada evaluacion del mismo tutor va en otro dia, porque dos
# bloques del mismo tutor no se pueden solapar (ex_bloque_sin_solape).
AYER = (tz.now() - timedelta(days=1)).replace(
    hour=12, minute=0, second=0, microsecond=0
)
ID_DESACTIVADO = UUID("10000000-0000-4000-8000-000000000006")
ID_SIN_PERFIL_ACTIVO = UUID("10000000-0000-4000-8000-000000000007")
NO_ES_TUTOR_ACTIVO = {
    "codigo": "not_found",
    "mensaje": "No existe un tutor activo con ese identificador.",
    "detalles": None,
}


def url_perfil(usuario_id):
    return f"/api/tutoring/v1/tutores/{usuario_id}"


def url_del_tutor(usuario_id):
    return f"/api/tutoring/v1/tutores/{usuario_id}/evaluaciones"


def con_perfil(tutor_id, activo=True):
    """El tutor con un perfil en Base de Datos.

    Sin un perfil activo, GET /tutores/<id> y GET /tutores/<id>/evaluaciones
    responden 404.
    """
    PerfilTutor.objects.create(
        usuario=asegurar_usuario_ref(tutor_id),
        asignatura=crear_asignatura(),
        tarifa=Decimal("4500"),
        activo=activo,
    )


def evaluacion_de(
    tutor_id,
    dias,
    calificacion=5,
    comentario=None,
    asignatura_id=ID_ASIGNATURA,
    retirada=False,
):
    """Evaluacion de una reserva EVALUADA sobre un bloque del tutor.

    El bloque es de una hora, tantos dias antes de AYER. La evaluacion se crea
    media hora despues de que termina, y si va retirada, la retiro el
    administrador (ck_evaluacion_retiro pide las dos columnas).
    """
    inicio = AYER - timedelta(days=dias)
    reserva = crear_reserva(
        tutor_id=tutor_id,
        estado=EstadoReserva.EVALUADA,
        inicio_en=inicio,
        fin_en=inicio + timedelta(hours=1),
        asignatura_id=asignatura_id,
    )
    return Evaluacion.objects.create(
        reserva=reserva,
        calificacion=calificacion,
        comentario=comentario,
        creada_en=inicio + timedelta(minutes=90),
        retirada_en=AYER if retirada else None,
        retirada_por_usuario_id=ID_ADMIN if retirada else None,
    )


def fecha(texto):
    """Fecha de la respuesta: ISO 8601 y con zona horaria."""
    valor = datetime.fromisoformat(texto)
    assert valor.tzinfo is not None
    return valor


def claves(valor):
    """Todas las claves de un JSON, a cualquier profundidad."""
    if isinstance(valor, dict):
        for clave, contenido in valor.items():
            yield clave
            yield from claves(contenido)
    elif isinstance(valor, list):
        for elemento in valor:
            yield from claves(elemento)


def consultas_de(url, evaluaciones):
    """Cuantas consultas hace GET url, que tiene que traer esas evaluaciones."""
    with CaptureQueriesContext(connection) as consultas:
        respuesta = APIClient().get(url)
    assert respuesta.status_code == 200
    assert len(respuesta.json()) == evaluaciones
    return len(consultas)


@pytest.mark.django_db
class TestEvaluacionesDelTutor:
    def test_trae_las_visibles_del_tutor_de_la_mas_nueva_a_la_mas_antigua(self):
        con_perfil(ID_TUTOR)
        con_perfil(ID_AJENO)
        crear_asignatura(ID_ASIGNATURA_REDES, "RED1101", "Fundamentos de Redes")
        vieja = evaluacion_de(ID_TUTOR, 10, calificacion=3, comentario="Clara.")
        sin_comentario = evaluacion_de(ID_TUTOR, 7, calificacion=4)
        nueva = evaluacion_de(
            ID_TUTOR,
            5,
            comentario="Explicó las subredes con ejemplos.",
            asignatura_id=ID_ASIGNATURA_REDES,
        )
        # No salen la retirada por el administrador (CA7) ni la de otro tutor.
        evaluacion_de(ID_TUTOR, 6, calificacion=1, retirada=True)
        evaluacion_de(ID_AJENO, 4, calificacion=2)

        respuesta = APIClient().get(url_del_tutor(ID_TUTOR))

        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert [e["calificacion"] for e in cuerpo] == [5, 4, 3]
        assert [fecha(e["creada_en"]) for e in cuerpo] == [
            nueva.creada_en,
            sin_comentario.creada_en,
            vieja.creada_en,
        ]
        assert set(cuerpo[0]) == {
            "calificacion",
            "comentario",
            "creada_en",
            "asignatura",
        }
        assert cuerpo[0]["comentario"] == "Explicó las subredes con ejemplos."
        assert cuerpo[0]["asignatura"] == {
            "sigla": "RED1101",
            "nombre": "Fundamentos de Redes",
        }
        assert cuerpo[1]["comentario"] is None
        assert cuerpo[2]["asignatura"] == {
            "sigla": "BDD1101",
            "nombre": "Base de Datos",
        }

        # Nada de quien evaluo: ni su id, ni su nombre, ni un correo.
        prohibidas = ("usuario", "solicitante", "email", "correo")
        assert [c for c in claves(cuerpo) if any(p in c for p in prohibidas)] == []
        texto = respuesta.content.decode()
        assert str(ID_SOLICITANTE) not in texto
        assert "Camila" not in texto

    def test_un_tutor_sin_evaluaciones_responde_una_lista_vacia(self):
        con_perfil(ID_TUTOR)

        respuesta = APIClient().get(url_del_tutor(ID_TUTOR))

        assert respuesta.status_code == 200
        assert respuesta.json() == []

    def test_responde_el_mismo_404_que_el_perfil_si_no_es_un_tutor_activo(self):
        # Los dos tienen una evaluacion visible, y aun asi responden 404.
        con_perfil(ID_DESACTIVADO)
        evaluacion_de(ID_DESACTIVADO, 1)
        UsuarioRef.objects.filter(pk=ID_DESACTIVADO).update(activo=False)
        con_perfil(ID_SIN_PERFIL_ACTIVO, activo=False)
        evaluacion_de(ID_SIN_PERFIL_ACTIVO, 1)

        casos = {
            "no existe": ID_INEXISTENTE,
            "cuenta desactivada (RN-08)": ID_DESACTIVADO,
            "sin perfiles activos": ID_SIN_PERFIL_ACTIVO,
        }
        for caso, usuario_id in casos.items():
            respuesta = APIClient().get(url_del_tutor(usuario_id))
            perfil = APIClient().get(url_perfil(usuario_id))
            assert respuesta.status_code == 404, caso
            assert respuesta.json() == NO_ES_TUTOR_ACTIVO, caso
            assert perfil.status_code == 404, caso
            assert perfil.json() == respuesta.json(), caso

    def test_hace_las_mismas_consultas_con_una_y_con_tres_evaluaciones(self):
        con_perfil(ID_TUTOR)
        crear_asignatura(ID_ASIGNATURA_REDES, "RED1101", "Fundamentos de Redes")
        evaluacion_de(ID_TUTOR, 1)
        con_una = consultas_de(url_del_tutor(ID_TUTOR), evaluaciones=1)

        evaluacion_de(ID_TUTOR, 2, asignatura_id=ID_ASIGNATURA_REDES)
        evaluacion_de(ID_TUTOR, 3)
        con_tres = consultas_de(url_del_tutor(ID_TUTOR), evaluaciones=3)

        # Una para el 404 y otra para la lista, sin una por evaluacion.
        assert con_una == con_tres == 2

    def test_no_pide_token_y_con_un_token_invalido_responde_401(
        self, cliente_autenticado
    ):
        con_perfil(ID_TUTOR)
        evaluacion_de(ID_TUTOR, 1)
        url = url_del_tutor(ID_TUTOR)

        sin_token = APIClient().get(url)
        con_token = cliente_autenticado(ID_SOLICITANTE).get(url)
        token_invalido = APIClient().get(
            url, HTTP_AUTHORIZATION="Bearer no-es-un-token"
        )

        assert sin_token.status_code == 200
        assert len(sin_token.json()) == 1
        assert con_token.status_code == 200
        assert con_token.json() == sin_token.json()
        assert token_invalido.status_code == 401
        assert token_invalido.json()["codigo"] == "token_invalido"

    def test_trae_hasta_100_evaluaciones_las_mas_nuevas(self):
        con_perfil(ID_TUTOR)
        evaluaciones = [evaluacion_de(ID_TUTOR, dias) for dias in range(1, 102)]

        cuerpo = APIClient().get(url_del_tutor(ID_TUTOR)).json()

        # Son 101 visibles: queda fuera la mas antigua.
        assert len(cuerpo) == 100
        assert [fecha(e["creada_en"]) for e in cuerpo] == [
            e.creada_en for e in evaluaciones[:100]
        ]


# ------------------------------------------ HU-27, criterio 2: de punta a punta


@pytest.mark.django_db
def test_de_punta_a_punta_evaluar_y_retirar_cambian_la_reputacion_y_las_listas(
    cliente_autenticado,
):
    con_perfil(ID_TUTOR)
    ahora = tz.now().replace(microsecond=0)
    anterior = crear_reserva(
        inicio_en=ahora - timedelta(hours=8), fin_en=ahora - timedelta(hours=7)
    )
    reserva = crear_reserva(
        solicitante_id=ID_OTRO_ESTUDIANTE,
        inicio_en=ahora - timedelta(hours=4),
        fin_en=ahora - timedelta(hours=3),
    )
    publico = APIClient()

    # La reputacion anterior: una evaluacion de 5.
    primera = cliente_autenticado(ID_SOLICITANTE).post(
        url_evaluacion(anterior.id), {"calificacion": 5}, format="json"
    )
    assert primera.status_code == 201
    perfil = publico.get(url_perfil(ID_TUTOR)).json()
    assert perfil["reputacion"] == {"promedio": 5.0, "total": 1}

    # Otro estudiante evalua con 3: la reputacion nueva sale en el perfil.
    respuesta = cliente_autenticado(ID_OTRO_ESTUDIANTE).post(
        url_evaluacion(reserva.id),
        {"calificacion": 3, "comentario": "Faltó tiempo para los ejercicios."},
        format="json",
    )
    assert respuesta.status_code == 201
    perfil = publico.get(url_perfil(ID_TUTOR)).json()
    assert perfil["reputacion"] == {"promedio": 4.0, "total": 2}
    assert [e["calificacion"] for e in perfil["evaluaciones"]] == [3, 5]
    lista = publico.get(url_del_tutor(ID_TUTOR)).json()
    assert [e["calificacion"] for e in lista] == [3, 5]
    assert lista[0]["comentario"] == "Faltó tiempo para los ejercicios."

    # Lo que va a hacer HU-33: retirar esa evaluacion en la base y recalcular.
    Evaluacion.objects.filter(reserva=reserva).update(
        retirada_en=tz.now(), retirada_por_usuario_id=ID_ADMIN
    )
    assert recalcular_reputacion(ID_TUTOR) == (Decimal("5.00"), 1)

    perfil = publico.get(url_perfil(ID_TUTOR)).json()
    assert perfil["reputacion"] == {"promedio": 5.0, "total": 1}
    assert [e["calificacion"] for e in perfil["evaluaciones"]] == [5]
    lista = publico.get(url_del_tutor(ID_TUTOR)).json()
    assert [e["calificacion"] for e in lista] == [5]
