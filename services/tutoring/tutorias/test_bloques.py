"""Pruebas de HU-15: bloques de disponibilidad del tutor.

Corren contra PostgreSQL, porque la restriccion EXCLUDE de RN-02 y el
disparador trg_reserva_no_auto solo existen ahi. Como en test_autenticacion.py
(HU-17), no usan las claves de keys/: generan su propio par RSA y firman los
tokens con la privada, como Identidad.
"""

import uuid
from datetime import timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from .autenticacion import leer_clave
from .bloques import guardar_sin_solape
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

URL = "/api/tutoring/v1/disponibilidad"
# Los bloques de las pruebas se cuentan en horas desde manana a mediodia (UTC).
MANANA = (timezone.now() + timedelta(days=1)).replace(
    hour=12, minute=0, second=0, microsecond=0
)


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

    def para(usuario):
        token = firmar(clave_de_identidad, getattr(usuario, "usuario_id", usuario))
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    return para


def persona(nombre, activo=True):
    return UsuarioRef.objects.create(
        usuario_id=uuid.uuid4(), nombre=nombre, apellido="Demo", activo=activo
    )


def tutor_de(asignatura, nombre):
    usuario = persona(nombre)
    PerfilTutor.objects.create(usuario=usuario, asignatura=asignatura, tarifa=0)
    return usuario


@pytest.fixture
def asignatura(db):
    return AsignaturaRef.objects.create(
        asignatura_id=uuid.uuid4(), sigla="PRU1101", nombre="Prueba"
    )


@pytest.fixture
def tutora(asignatura):
    return tutor_de(asignatura, "Tutora")


@pytest.fixture
def otro_tutor(asignatura):
    return tutor_de(asignatura, "Otro tutor")


@pytest.fixture
def estudiante(db):
    return persona("Estudiante")


def bloque(tutor, desde, hasta, **campos):
    """Bloque desde MANANA + desde horas hasta MANANA + hasta horas."""
    return BloqueDisponibilidad.objects.create(
        usuario=tutor,
        inicio_en=MANANA + timedelta(hours=desde),
        fin_en=MANANA + timedelta(hours=hasta),
        **campos,
    )


def reserva(en_bloque, solicitante, asignatura, estado=EstadoReserva.SOLICITADA):
    """Reserva que cumple las restricciones del modelo (RN-07 y RN-03)."""
    confirmacion = {}
    if estado in ESTADOS_QUE_OCUPAN:
        confirmacion = {
            "modalidad": Modalidad.EN_LINEA,
            "lugar_o_enlace": "https://meet.example.com/prueba",
            "confirmada_en": timezone.now(),
        }
    return Reserva.objects.create(
        bloque=en_bloque,
        solicitante_usuario=solicitante,
        asignatura=asignatura,
        estado=estado,
        **confirmacion,
    )


def en(horas):
    """MANANA + horas, como lo manda la pagina: toISOString() de JavaScript."""
    instante = MANANA + timedelta(hours=horas)
    return instante.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def publicar(client, cabecera, usuario, inicio, fin):
    return client.post(
        URL,
        {"inicio_en": inicio, "fin_en": fin},
        content_type="application/json",
        **cabecera(usuario),
    )


def editar(client, cabecera, usuario, id_bloque, **cambios):
    return client.patch(
        f"{URL}/{id_bloque}",
        cambios,
        content_type="application/json",
        **cabecera(usuario),
    )


def eliminar(client, cabecera, usuario, id_bloque):
    return client.delete(f"{URL}/{id_bloque}", **cabecera(usuario))


# ---------------------------------------------------------------- sesion y tutor


@pytest.mark.django_db
def test_sin_token_responde_401(client, tutora):
    suyo = bloque(tutora, 1, 2)

    respuestas = [
        client.get(URL),
        client.post(
            URL, {"inicio_en": en(3), "fin_en": en(4)}, content_type="application/json"
        ),
        client.patch(
            f"{URL}/{suyo.id}", {"fin_en": en(3)}, content_type="application/json"
        ),
        client.delete(f"{URL}/{suyo.id}"),
    ]

    assert [r.status_code for r in respuestas] == [401, 401, 401, 401]
    assert BloqueDisponibilidad.objects.get(pk=suyo.pk).fin_en == suyo.fin_en


def sin_perfil(asignatura):
    return persona("Camila")


def con_el_perfil_desactivado(asignatura):
    usuario = persona("Camila")
    PerfilTutor.objects.create(usuario=usuario, asignatura=asignatura, activo=False)
    return usuario


def con_la_cuenta_desactivada(asignatura):
    usuario = persona("Josefa", activo=False)
    PerfilTutor.objects.create(usuario=usuario, asignatura=asignatura)
    return usuario


def sin_copia_en_tutorias(asignatura):
    return uuid.uuid4()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "quien",
    [
        sin_perfil,
        con_el_perfil_desactivado,
        con_la_cuenta_desactivada,
        sin_copia_en_tutorias,
    ],
    ids=lambda caso: caso.__name__,
)
def test_solo_un_tutor_activo_publica(client, cabecera, asignatura, quien):
    usuario = quien(asignatura)

    respuesta = publicar(client, cabecera, usuario, en(1), en(2))

    assert respuesta.status_code == 403
    assert respuesta.json()["codigo"] == "no_es_tutor"
    assert "primero declara al menos una asignatura" in respuesta.json()["mensaje"]
    assert not BloqueDisponibilidad.objects.exists()
    # Ver su disponibilidad no exige ser tutor: simplemente no tiene bloques.
    assert client.get(URL, **cabecera(usuario)).json() == []


@pytest.mark.django_db
def test_quien_dejo_de_ser_tutor_ve_y_borra_sus_bloques_pero_no_los_edita(
    client, cabecera, tutora
):
    suyo = bloque(tutora, 1, 2)
    PerfilTutor.objects.filter(usuario=tutora).update(activo=False)

    lista = client.get(URL, **cabecera(tutora))
    edicion = editar(client, cabecera, tutora, suyo.id, fin_en=en(3))
    borrado = eliminar(client, cabecera, tutora, suyo.id)

    assert [b["id"] for b in lista.json()] == [str(suyo.id)]
    assert edicion.status_code == 403
    assert edicion.json()["codigo"] == "no_es_tutor"
    assert borrado.status_code == 204


# ---------------------------------------------------------------- publicar


@pytest.mark.django_db
def test_publica_un_bloque_libre_que_aparece_en_su_disponibilidad(
    client, cabecera, tutora
):
    """Criterio 1."""
    respuesta = publicar(client, cabecera, tutora, en(1), en(2))

    assert respuesta.status_code == 201
    creado = respuesta.json()
    assert creado["estado"] == EstadoBloque.LIBRE
    assert creado["solicitudes_pendientes"] == 0
    guardado = BloqueDisponibilidad.objects.get(pk=creado["id"])
    assert guardado.usuario_id == tutora.usuario_id
    assert guardado.inicio_en == MANANA + timedelta(hours=1)
    assert guardado.fin_en == MANANA + timedelta(hours=2)
    lista = client.get(URL, **cabecera(tutora)).json()
    assert [b["id"] for b in lista] == [creado["id"]]


@pytest.mark.django_db
def test_rechaza_un_bloque_que_empieza_en_el_pasado(client, cabecera, tutora):
    """Criterio 2."""
    hace_una_hora = (timezone.now() - timedelta(hours=1)).isoformat()
    en_una_hora = (timezone.now() + timedelta(hours=1)).isoformat()

    respuesta = publicar(client, cabecera, tutora, hace_una_hora, en_una_hora)

    assert respuesta.status_code == 400
    assert respuesta.json()["codigo"] == "bloque_en_el_pasado"
    assert not BloqueDisponibilidad.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("hasta", [0.5, 1], ids=["antes", "igual"])
def test_rechaza_un_termino_que_no_es_posterior_al_inicio(
    client, cabecera, tutora, hasta
):
    respuesta = publicar(client, cabecera, tutora, en(1), en(hasta))

    assert respuesta.status_code == 400
    assert respuesta.json()["codigo"] == "fin_antes_de_inicio"
    assert not BloqueDisponibilidad.objects.exists()


@pytest.mark.django_db
def test_rechaza_fechas_sin_zona_horaria(client, cabecera, tutora):
    sin_zona = (MANANA + timedelta(hours=1)).replace(tzinfo=None).isoformat()

    respuesta = publicar(client, cabecera, tutora, sin_zona, en(2))

    assert respuesta.status_code == 400
    assert respuesta.json()["codigo"] == "zona_horaria_requerida"
    assert not BloqueDisponibilidad.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "cuerpo",
    [
        {"inicio_en": "mañana a las 18:00", "fin_en": en(2)},
        {"inicio_en": 20271201, "fin_en": en(2)},
        {"fin_en": en(2)},
    ],
    ids=["texto", "numero", "sin_inicio"],
)
def test_rechaza_fechas_que_no_son_iso_8601(client, cabecera, tutora, cuerpo):
    respuesta = client.post(
        URL, cuerpo, content_type="application/json", **cabecera(tutora)
    )

    assert respuesta.status_code == 400
    assert respuesta.json()["codigo"] == "fecha_invalida"


@pytest.mark.django_db
def test_rechaza_un_bloque_que_se_solapa_con_otro_suyo(client, cabecera, tutora):
    """Criterio 2 (RN-02): lo rechaza la restriccion EXCLUDE de la base."""
    bloque(tutora, 1, 2)

    respuesta = publicar(client, cabecera, tutora, en(1.5), en(3))

    assert respuesta.status_code == 409
    assert respuesta.json()["codigo"] == "bloque_solapado"
    assert "se cruza con otro de tus bloques" in respuesta.json()["mensaje"]
    assert BloqueDisponibilidad.objects.count() == 1


@pytest.mark.django_db
def test_un_bloque_seguido_o_de_otro_tutor_no_es_solape(
    client, cabecera, tutora, otro_tutor
):
    bloque(tutora, 1, 2)

    seguido = publicar(client, cabecera, tutora, en(2), en(3))
    a_la_misma_hora = publicar(client, cabecera, otro_tutor, en(1), en(2))

    assert seguido.status_code == 201
    assert a_la_misma_hora.status_code == 201


@pytest.mark.django_db
def test_otro_rechazo_de_la_base_no_se_disfraza_de_solape(tutora):
    """Solo ex_bloque_sin_solape se vuelve 409; otro IntegrityError se relanza."""
    sin_duracion = BloqueDisponibilidad(usuario=tutora, inicio_en=MANANA, fin_en=MANANA)

    with pytest.raises(IntegrityError), transaction.atomic():
        guardar_sin_solape(sin_duracion)


# ---------------------------------------------------------------- editar


@pytest.mark.django_db
def test_edita_un_bloque_libre_sin_solicitudes(client, cabecera, tutora):
    """Criterio 3."""
    libre = bloque(tutora, 1, 2)

    respuesta = editar(
        client, cabecera, tutora, libre.id, inicio_en=en(3), fin_en=en(4)
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["id"] == str(libre.id)
    libre.refresh_from_db()
    assert libre.inicio_en == MANANA + timedelta(hours=3)
    assert libre.fin_en == MANANA + timedelta(hours=4)


@pytest.mark.django_db
def test_editar_solo_el_termino_conserva_el_inicio(client, cabecera, tutora):
    libre = bloque(tutora, 1, 2)

    respuesta = editar(client, cabecera, tutora, libre.id, fin_en=en(3))

    assert respuesta.status_code == 200
    libre.refresh_from_db()
    assert libre.inicio_en == MANANA + timedelta(hours=1)
    assert libre.fin_en == MANANA + timedelta(hours=3)


@pytest.mark.django_db
def test_editar_aplica_las_mismas_reglas_de_fechas_y_solape(client, cabecera, tutora):
    libre = bloque(tutora, 1, 2)
    bloque(tutora, 3, 4)
    hace_una_hora = (timezone.now() - timedelta(hours=1)).isoformat()

    respuestas = [
        editar(client, cabecera, tutora, libre.id, inicio_en=hace_una_hora),
        editar(client, cabecera, tutora, libre.id, inicio_en=en(3), fin_en=en(5)),
        editar(client, cabecera, tutora, libre.id, fin_en=en(0.5)),
    ]

    assert [r.status_code for r in respuestas] == [400, 409, 400]
    assert [r.json()["codigo"] for r in respuestas] == [
        "bloque_en_el_pasado",
        "bloque_solapado",
        "fin_antes_de_inicio",
    ]
    libre.refresh_from_db()
    assert libre.inicio_en == MANANA + timedelta(hours=1)
    assert libre.fin_en == MANANA + timedelta(hours=2)


@pytest.mark.django_db
def test_no_edita_un_bloque_con_solicitudes_pendientes(
    client, cabecera, tutora, estudiante, asignatura
):
    pedido = bloque(tutora, 1, 2)
    reserva(pedido, estudiante, asignatura)

    respuesta = editar(
        client, cabecera, tutora, pedido.id, inicio_en=en(3), fin_en=en(4)
    )

    assert respuesta.status_code == 409
    assert respuesta.json()["codigo"] == "bloque_con_solicitudes"
    pedido.refresh_from_db()
    assert pedido.inicio_en == MANANA + timedelta(hours=1)


@pytest.mark.django_db
def test_no_edita_un_bloque_con_reserva_confirmada(
    client, cabecera, tutora, estudiante, asignatura
):
    ocupado = bloque(tutora, 1, 2, estado=EstadoBloque.OCUPADO)
    reserva(ocupado, estudiante, asignatura, EstadoReserva.CONFIRMADA)

    respuesta = editar(
        client, cabecera, tutora, ocupado.id, inicio_en=en(3), fin_en=en(4)
    )

    assert respuesta.status_code == 409
    assert respuesta.json()["codigo"] == "bloque_con_reserva_confirmada"
    ocupado.refresh_from_db()
    assert ocupado.inicio_en == MANANA + timedelta(hours=1)


# ---------------------------------------------------------------- eliminar


@pytest.mark.django_db
def test_borra_un_bloque_sin_reservas(client, cabecera, tutora):
    """Criterio 3: sin reservas, se borra la fila."""
    libre = bloque(tutora, 1, 2)

    respuesta = eliminar(client, cabecera, tutora, libre.id)

    assert respuesta.status_code == 204
    assert not BloqueDisponibilidad.objects.filter(pk=libre.pk).exists()


@pytest.mark.django_db
def test_borrar_un_bloque_con_solicitudes_pendientes_las_rechaza(
    client, cabecera, tutora, estudiante, asignatura
):
    """Criterio 4: las solicitudes quedan RECHAZADAS y el bloque, ELIMINADO."""
    pedido = bloque(tutora, 1, 2)
    solicitud = reserva(pedido, estudiante, asignatura)

    respuesta = eliminar(client, cabecera, tutora, pedido.id)

    assert respuesta.status_code == 204
    solicitud.refresh_from_db()
    assert solicitud.estado == EstadoReserva.RECHAZADA
    assert solicitud.cerrada_en is not None
    pedido.refresh_from_db()
    assert pedido.estado == EstadoBloque.ELIMINADO
    assert client.get(URL, **cabecera(tutora)).json() == []
    # El bloque eliminado ya no cuenta para RN-02: esa hora se puede publicar.
    assert publicar(client, cabecera, tutora, en(1), en(2)).status_code == 201


@pytest.mark.django_db
@pytest.mark.parametrize(
    "estado",
    [EstadoReserva.RECHAZADA, EstadoReserva.CANCELADA, EstadoReserva.EXPIRADA],
)
def test_borrar_un_bloque_que_tuvo_reservas_lo_deja_eliminado(
    client, cabecera, tutora, estudiante, asignatura, estado
):
    usado = bloque(tutora, 1, 2)
    cerrada = reserva(usado, estudiante, asignatura, estado)

    respuesta = eliminar(client, cabecera, tutora, usado.id)

    assert respuesta.status_code == 204
    usado.refresh_from_db()
    assert usado.estado == EstadoBloque.ELIMINADO
    cerrada.refresh_from_db()
    assert cerrada.estado == estado


@pytest.mark.django_db
@pytest.mark.parametrize("estado", ESTADOS_QUE_OCUPAN)
def test_no_borra_un_bloque_con_reserva_confirmada(
    client, cabecera, tutora, estudiante, asignatura, estado
):
    """Criterio 5."""
    ocupado = bloque(tutora, 1, 2, estado=EstadoBloque.OCUPADO)
    confirmada = reserva(ocupado, estudiante, asignatura, estado)

    respuesta = eliminar(client, cabecera, tutora, ocupado.id)

    assert respuesta.status_code == 409
    assert respuesta.json()["codigo"] == "bloque_con_reserva_confirmada"
    ocupado.refresh_from_db()
    assert ocupado.estado == EstadoBloque.OCUPADO
    confirmada.refresh_from_db()
    assert confirmada.estado == estado


@pytest.mark.django_db
def test_un_bloque_ajeno_eliminado_o_que_no_existe_responde_404(
    client, cabecera, tutora, otro_tutor
):
    ajeno = bloque(otro_tutor, 1, 2)
    eliminado = bloque(tutora, 3, 4, estado=EstadoBloque.ELIMINADO)

    for id_bloque in (ajeno.id, eliminado.id, uuid.uuid4()):
        edicion = editar(client, cabecera, tutora, id_bloque, fin_en=en(5))
        borrado = eliminar(client, cabecera, tutora, id_bloque)
        assert (edicion.status_code, borrado.status_code) == (404, 404)
        assert borrado.json()["codigo"] == "not_found"

    ajeno.refresh_from_db()
    assert ajeno.fin_en == MANANA + timedelta(hours=2)
    assert ajeno.estado == EstadoBloque.LIBRE


# ---------------------------------------------------------------- lista


@pytest.mark.django_db
def test_la_lista_trae_sus_bloques_vigentes_en_orden_y_sus_solicitudes(
    client, cabecera, tutora, otro_tutor, asignatura
):
    ahora = timezone.now()
    tarde = bloque(tutora, 5, 6)
    temprano = bloque(tutora, 1, 2)
    pedido = bloque(tutora, 3, 4)
    en_curso = BloqueDisponibilidad.objects.create(
        usuario=tutora,
        inicio_en=ahora - timedelta(minutes=30),
        fin_en=ahora + timedelta(minutes=30),
    )
    for nombre in ("Ana", "Beto"):
        reserva(pedido, persona(nombre), asignatura)
    reserva(pedido, persona("Carla"), asignatura, EstadoReserva.RECHAZADA)
    # No aparecen: uno eliminado, uno que ya termino y uno de otro tutor.
    bloque(tutora, 7, 8, estado=EstadoBloque.ELIMINADO)
    BloqueDisponibilidad.objects.create(
        usuario=tutora,
        inicio_en=ahora - timedelta(hours=3),
        fin_en=ahora - timedelta(hours=2),
    )
    bloque(otro_tutor, 1, 2)

    respuesta = client.get(URL, **cabecera(tutora))

    assert respuesta.status_code == 200
    lista = respuesta.json()
    assert [b["id"] for b in lista] == [
        str(en_curso.id),
        str(temprano.id),
        str(pedido.id),
        str(tarde.id),
    ]
    assert [b["solicitudes_pendientes"] for b in lista] == [0, 0, 2, 0]
    assert set(lista[0]) == {
        "id",
        "inicio_en",
        "fin_en",
        "estado",
        "solicitudes_pendientes",
    }


def consultas_de_la_lista(client, cabecera, usuario):
    with CaptureQueriesContext(connection) as consultas:
        respuesta = client.get(URL, **cabecera(usuario))
    assert respuesta.status_code == 200
    return len(consultas)


@pytest.mark.django_db
def test_la_lista_no_hace_una_consulta_por_bloque(client, cabecera, tutora, asignatura):
    bloque(tutora, 1, 2)
    con_un_bloque = consultas_de_la_lista(client, cabecera, tutora)

    for desde in (3, 5, 7):
        solicitante = persona(f"Estudiante {desde}")
        reserva(bloque(tutora, desde, desde + 1), solicitante, asignatura)

    assert consultas_de_la_lista(client, cabecera, tutora) == con_un_bloque


# ---------------------------------------------------------------- hora de Chile


@pytest.mark.django_db
def test_un_bloque_a_las_20_de_chile_se_guarda_en_utc(client, cabecera, tutora):
    """Criterio 6: 20:00 en Chile en verano (-03:00) son las 23:00 en UTC."""
    anio = timezone.now().year + 1

    respuesta = publicar(
        client,
        cabecera,
        tutora,
        f"{anio}-12-01T20:00:00-03:00",
        f"{anio}-12-01T21:00:00-03:00",
    )

    assert respuesta.status_code == 201
    creado = respuesta.json()
    assert creado["inicio_en"] == f"{anio}-12-01T23:00:00Z"
    assert creado["fin_en"] == f"{anio}-12-02T00:00:00Z"
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT inicio_en::text FROM bloque_disponibilidad WHERE id = %s",
            [uuid.UUID(creado["id"])],
        )
        assert cursor.fetchone()[0] == f"{anio}-12-01 23:00:00+00"
    lista = client.get(URL, **cabecera(tutora)).json()
    assert lista[0]["inicio_en"] == f"{anio}-12-01T23:00:00Z"
