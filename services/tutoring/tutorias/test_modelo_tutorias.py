"""Pruebas de las reglas que sostiene la base de datos (HU-08).

Cada prueba intenta guardar algo que el anexo A prohibe y comprueba que
PostgreSQL lo rechaza, sin ayuda del codigo de la aplicacion.
"""

import uuid
from datetime import timedelta

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from .models import (
    ESTADOS_QUE_OCUPAN,
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

MANANA = timezone.now().replace(microsecond=0) + timedelta(days=1)


def persona(nombre):
    return UsuarioRef.objects.create(
        usuario_id=uuid.uuid4(), nombre=nombre, apellido="Demo"
    )


def bloque(tutor, desde_hora, hasta_hora, **campos):
    return BloqueDisponibilidad.objects.create(
        usuario=tutor,
        inicio_en=MANANA + timedelta(hours=desde_hora),
        fin_en=MANANA + timedelta(hours=hasta_hora),
        **campos,
    )


@pytest.fixture
def tutor():
    return persona("Tutora")


@pytest.fixture
def estudiante():
    return persona("Estudiante")


@pytest.fixture
def asignatura():
    return AsignaturaRef.objects.create(
        asignatura_id=uuid.uuid4(), sigla="PRU1101", nombre="Prueba"
    )


@pytest.mark.django_db
def test_tutoring_db_tiene_las_siete_tablas_y_btree_gist():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        )
        tablas = {fila[0] for fila in cursor.fetchall()}
        cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'btree_gist'")
        extension = cursor.fetchone()

    assert tablas == {
        "usuario_ref",
        "asignatura_ref",
        "perfil_tutor",
        "bloque_disponibilidad",
        "reserva",
        "evaluacion",
        "ejecucion_tarea",
        "django_migrations",
    }
    assert extension is not None


@pytest.mark.django_db
def test_dos_bloques_del_mismo_tutor_no_se_solapan(tutor):
    bloque(tutor, 10, 11)

    # atomic() deja viva la transaccion de la prueba despues del rechazo.
    with pytest.raises(IntegrityError), transaction.atomic():
        bloque(tutor, 10.5, 12)


@pytest.mark.django_db
def test_un_bloque_eliminado_no_impide_publicar_otro(tutor):
    bloque(tutor, 10, 11, estado=EstadoBloque.ELIMINADO)

    nuevo = bloque(tutor, 10, 11)

    assert nuevo.pk is not None


@pytest.mark.django_db
def test_nadie_reserva_su_propio_bloque(tutor, asignatura):
    propio = bloque(tutor, 10, 11)

    with pytest.raises(IntegrityError), transaction.atomic():
        Reserva.objects.create(
            bloque=propio, solicitante_usuario=tutor, asignatura=asignatura
        )


@pytest.mark.django_db
def test_un_bloque_admite_una_sola_reserva_confirmada(tutor, estudiante, asignatura):
    ocupado = bloque(tutor, 10, 11)
    confirmada = {
        "estado": EstadoReserva.CONFIRMADA,
        "modalidad": Modalidad.EN_LINEA,
        "lugar_o_enlace": "https://meet.example.com/prueba",
        "confirmada_en": timezone.now(),
    }
    Reserva.objects.create(
        bloque=ocupado,
        solicitante_usuario=estudiante,
        asignatura=asignatura,
        **confirmada,
    )
    otro = persona("Otro estudiante")

    with pytest.raises(IntegrityError), transaction.atomic():
        Reserva.objects.create(
            bloque=ocupado,
            solicitante_usuario=otro,
            asignatura=asignatura,
            **confirmada,
        )


@pytest.mark.django_db
def test_no_se_confirma_sin_modalidad_ni_lugar(tutor, estudiante, asignatura):
    with pytest.raises(IntegrityError), transaction.atomic():
        Reserva.objects.create(
            bloque=bloque(tutor, 10, 11),
            solicitante_usuario=estudiante,
            asignatura=asignatura,
            estado=EstadoReserva.CONFIRMADA,
            confirmada_en=timezone.now(),
        )


@pytest.mark.django_db
def test_no_se_declara_dos_veces_la_misma_asignatura(tutor, asignatura):
    PerfilTutor.objects.create(usuario=tutor, asignatura=asignatura, tarifa=3000)

    with pytest.raises(IntegrityError), transaction.atomic():
        PerfilTutor.objects.create(usuario=tutor, asignatura=asignatura, tarifa=0)


@pytest.mark.django_db
def test_la_tarifa_no_es_negativa(tutor, asignatura):
    with pytest.raises(IntegrityError), transaction.atomic():
        PerfilTutor.objects.create(usuario=tutor, asignatura=asignatura, tarifa=-1)


# ---------------------------------------- SCRUM-62 (HU-36, parte A)
# Reglas del anexo A que no tenian prueba. Ademas del IntegrityError, cada
# rechazo revisa el nombre de la restriccion que dio PostgreSQL
# (error.__cause__.diag.constraint_name, como guardar_sin_solape en
# bloques.py): si la base rechazara por otra razon, la prueba falla. Las que
# guardan algo permitido comprueban que quedo en la base.

# Reservas que ya no estan pendientes ni ocupan el bloque.
CERRADAS = [EstadoReserva.RECHAZADA, EstadoReserva.CANCELADA, EstadoReserva.EXPIRADA]


def reserva(
    en_bloque, solicitante, asignatura, estado=EstadoReserva.SOLICITADA, **campos
):
    """Reserva que cumple las demas reglas del modelo.

    La que ocupa el bloque (CONFIRMADA, REALIZADA o EVALUADA) lleva modalidad,
    lugar y confirmada_en, como exige ck_reserva_confirmada_completa (RN-07).
    """
    if estado in ESTADOS_QUE_OCUPAN:
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


def restriccion(rechazo):
    """El nombre de la restriccion que dio PostgreSQL al rechazar."""
    return rechazo.value.__cause__.diag.constraint_name


# ---------------------------------------- RN-03: nadie se reserva a si mismo


@pytest.mark.django_db
def test_cambiar_el_solicitante_por_el_dueno_del_bloque_se_rechaza(
    tutor, estudiante, asignatura
):
    """El disparador trg_reserva_no_auto frena tambien un UPDATE."""
    solicitud = reserva(bloque(tutor, 10, 11), estudiante, asignatura)

    with pytest.raises(IntegrityError) as rechazo, transaction.atomic():
        Reserva.objects.filter(pk=solicitud.pk).update(solicitante_usuario=tutor)

    assert restriccion(rechazo) == "ck_reserva_no_auto"
    solicitud.refresh_from_db()
    assert solicitud.solicitante_usuario_id == estudiante.usuario_id


@pytest.mark.django_db
def test_mover_la_reserva_a_un_bloque_del_solicitante_se_rechaza(
    tutor, estudiante, asignatura
):
    del_tutor = bloque(tutor, 10, 11)
    solicitud = reserva(del_tutor, estudiante, asignatura)
    propio = bloque(estudiante, 12, 13)

    with pytest.raises(IntegrityError) as rechazo, transaction.atomic():
        Reserva.objects.filter(pk=solicitud.pk).update(bloque=propio)

    assert restriccion(rechazo) == "ck_reserva_no_auto"
    solicitud.refresh_from_db()
    assert solicitud.bloque_id == del_tutor.id


# ---------------------------------------- RN-03: una solicitud pendiente por bloque


@pytest.mark.django_db
def test_una_segunda_solicitud_pendiente_al_mismo_bloque_se_rechaza(
    tutor, estudiante, asignatura
):
    pedido = bloque(tutor, 10, 11)
    reserva(pedido, estudiante, asignatura)

    with pytest.raises(IntegrityError) as rechazo, transaction.atomic():
        reserva(pedido, estudiante, asignatura)

    assert restriccion(rechazo) == "ux_reserva_solicitud_unica"
    assert Reserva.objects.filter(bloque=pedido).count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("anterior", CERRADAS)
def test_si_la_primera_ya_no_esta_pendiente_la_segunda_se_acepta(
    tutor, estudiante, asignatura, anterior
):
    """Cada caso corre con la base vacia: un bloque por caso."""
    pedido = bloque(tutor, 10, 11)
    reserva(pedido, estudiante, asignatura, anterior, cerrada_en=timezone.now())

    segunda = reserva(pedido, estudiante, asignatura)

    pendientes = Reserva.objects.filter(bloque=pedido, estado=EstadoReserva.SOLICITADA)
    assert list(pendientes.values_list("id", flat=True)) == [segunda.id]


# ---------------------------------------- RN-05: sin tarifa no hay pago


@pytest.mark.django_db
def test_un_estado_de_pago_con_monto_0_se_rechaza(tutor, estudiante, asignatura):
    """ck_reserva_pago_con_monto: una tutoria gratuita no lleva pago."""
    libre = bloque(tutor, 10, 11)

    with pytest.raises(IntegrityError) as rechazo, transaction.atomic():
        reserva(
            libre,
            estudiante,
            asignatura,
            EstadoReserva.CONFIRMADA,
            monto=0,
            estado_pago=EstadoPago.PENDIENTE,
        )

    assert restriccion(rechazo) == "ck_reserva_pago_con_monto"
    assert not Reserva.objects.exists()


@pytest.mark.django_db
def test_un_estado_de_pago_con_monto_se_acepta(tutor, estudiante, asignatura):
    confirmada = reserva(
        bloque(tutor, 10, 11),
        estudiante,
        asignatura,
        EstadoReserva.CONFIRMADA,
        monto=5000,
        estado_pago=EstadoPago.PENDIENTE,
    )

    guardada = Reserva.objects.get(pk=confirmada.pk)
    assert (guardada.monto, guardada.estado_pago) == (5000, EstadoPago.PENDIENTE)


# ---------------------------------------- RN-02: el bloque termina despues de empezar


@pytest.mark.django_db
@pytest.mark.parametrize("hasta_hora", [10, 9.5], ids=["igual", "antes"])
def test_un_bloque_que_no_termina_despues_de_empezar_se_rechaza(tutor, hasta_hora):
    """ck_bloque_fin_posterior, sin la revision de fechas de bloques.py."""
    with pytest.raises(IntegrityError) as rechazo, transaction.atomic():
        bloque(tutor, 10, hasta_hora)

    assert restriccion(rechazo) == "ck_bloque_fin_posterior"
    assert not BloqueDisponibilidad.objects.exists()


# ---------------------------------------- RN-06: la calificacion va de 1 a 5


@pytest.mark.django_db
@pytest.mark.parametrize("calificacion", [0, 6])
def test_una_calificacion_fuera_de_1_a_5_se_rechaza(
    tutor, estudiante, asignatura, calificacion
):
    realizada = reserva(
        bloque(tutor, 10, 11), estudiante, asignatura, EstadoReserva.REALIZADA
    )

    with pytest.raises(IntegrityError) as rechazo, transaction.atomic():
        Evaluacion.objects.create(reserva=realizada, calificacion=calificacion)

    assert restriccion(rechazo) == "ck_evaluacion_calificacion"
    assert not Evaluacion.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("calificacion", [1, 5])
def test_una_calificacion_de_1_a_5_se_acepta(
    tutor, estudiante, asignatura, calificacion
):
    """Una evaluacion por reserva (OneToOne): cada caso, su reserva y su bloque."""
    realizada = reserva(
        bloque(tutor, 10, 11), estudiante, asignatura, EstadoReserva.REALIZADA
    )

    Evaluacion.objects.create(reserva=realizada, calificacion=calificacion)

    assert Evaluacion.objects.get(reserva=realizada).calificacion == calificacion


# ---------------------------------------- RN-03 y RN-04: que reserva ocupa el bloque


@pytest.mark.django_db
@pytest.mark.parametrize("anterior", CERRADAS)
def test_una_reserva_que_ya_no_ocupa_el_bloque_deja_confirmar_otra(
    tutor, estudiante, asignatura, anterior
):
    """ux_reserva_bloque_ocupado solo cuenta CONFIRMADA, REALIZADA y EVALUADA."""
    horario = bloque(tutor, 10, 11)
    reserva(horario, estudiante, asignatura, anterior, cerrada_en=timezone.now())
    otro = persona("Otro estudiante")

    nueva = reserva(horario, otro, asignatura, EstadoReserva.CONFIRMADA)

    confirmadas = Reserva.objects.filter(
        bloque=horario, estado=EstadoReserva.CONFIRMADA
    )
    assert list(confirmadas.values_list("id", flat=True)) == [nueva.id]


@pytest.mark.django_db
@pytest.mark.parametrize("ocupa", [EstadoReserva.REALIZADA, EstadoReserva.EVALUADA])
def test_una_reserva_realizada_o_evaluada_sigue_ocupando_el_bloque(
    tutor, estudiante, asignatura, ocupa
):
    """Ajuste A-03: una tutoria que ya paso no deja confirmar otra en su bloque."""
    horario = bloque(tutor, 10, 11)
    reserva(horario, estudiante, asignatura, ocupa)
    otro = persona("Otro estudiante")

    with pytest.raises(IntegrityError) as rechazo, transaction.atomic():
        reserva(horario, otro, asignatura, EstadoReserva.CONFIRMADA)

    assert restriccion(rechazo) == "ux_reserva_bloque_ocupado"
    assert Reserva.objects.filter(bloque=horario).count() == 1
