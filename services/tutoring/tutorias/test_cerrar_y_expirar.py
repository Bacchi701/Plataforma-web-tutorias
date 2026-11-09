"""Pruebas de HU-29: el comando cerrar_y_expirar (criterios 1 a 4).

Corren contra PostgreSQL. Las reservas y los bloques se crean directo en la
base, tambien los bloques que ya empezaron o terminaron, porque la API no los
acepta, sin solaparse con otros del mismo tutor (ex_bloque_sin_solape). El
comando se corre con call_command, sin argumentos, como lo corre el
programador (HU-37), y su salida se captura con io.StringIO. Para probar los
errores, cerrar_realizadas y expirar_solicitudes se reemplazan en el modulo
del comando, donde se usan.
"""

import io
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.utils import timezone

from .management.commands import cerrar_y_expirar as comando
from .models import (
    ESTADOS_QUE_OCUPAN,
    AsignaturaRef,
    BloqueDisponibilidad,
    EjecucionTarea,
    EstadoBloque,
    EstadoReserva,
    Modalidad,
    Reserva,
    UsuarioRef,
)
from .por_tiempo import cerrar_realizadas

CERRO_Y_EXPIRO = "cerrar_y_expirar: 1 reserva cerrada, 1 solicitud expirada.\n"
NADA = "cerrar_y_expirar: 0 reservas cerradas, 0 solicitudes expiradas.\n"


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
def tutora(db):
    """Valentina. El comando no mira los perfiles: no le hace falta uno."""
    return persona("Valentina", "Soto")


@pytest.fixture
def camila(db):
    return persona("Camila", "Rojas")


def bloque(tutor, desde, hasta):
    """Bloque LIBRE del tutor, desde y hasta en minutos desde ahora."""
    ahora = timezone.now()
    return BloqueDisponibilidad.objects.create(
        usuario=tutor,
        inicio_en=ahora + timedelta(minutes=desde),
        fin_en=ahora + timedelta(minutes=hasta),
    )


def reserva(en_bloque, solicitante, asignatura, estado=EstadoReserva.SOLICITADA):
    """Reserva creada directo en la base, que cumple las reglas del modelo.

    Una CONFIRMADA lleva modalidad, lugar y confirmada_en
    (ck_reserva_confirmada_completa), y su bloque queda OCUPADO, como lo deja
    la confirmacion de HU-22.
    """
    valores = {"monto": Decimal("5000")}
    if estado in ESTADOS_QUE_OCUPAN:
        valores.update(
            modalidad=Modalidad.EN_LINEA,
            lugar_o_enlace="https://meet.example.com/prueba",
            confirmada_en=timezone.now() - timedelta(days=1),
        )
        en_bloque.estado = EstadoBloque.OCUPADO
        en_bloque.save(update_fields=["estado", "actualizado_en"])
    return Reserva.objects.create(
        bloque=en_bloque,
        solicitante_usuario=solicitante,
        asignatura=asignatura,
        estado=estado,
        **valores,
    )


@pytest.fixture
def pendientes(tutora, camila, asignatura):
    """Una tutoria CONFIRMADA que ya termino y una solicitud de un bloque en curso.

    La tutoria termino hace dos horas; el bloque de la solicitud empezo hace
    media hora y todavia no termina. Los dos bloques son de la misma tutora y
    no se solapan.
    """
    terminada = reserva(
        bloque(tutora, -180, -120), camila, asignatura, EstadoReserva.CONFIRMADA
    )
    solicitud = reserva(bloque(tutora, -30, 30), camila, asignatura)
    return terminada, solicitud


def como_esta(una_reserva):
    """El estado y cerrada_en de la reserva, leidos de la base."""
    una_reserva.refresh_from_db()
    return una_reserva.estado, una_reserva.cerrada_en


# ------------------------------------------------------------ el comando


def correr():
    """call_command sin argumentos, como el programador. Devuelve lo que escribio."""
    salida = io.StringIO()
    call_command("cerrar_y_expirar", stdout=salida)
    return salida.getvalue()


def correr_con_error():
    """Corre el comando, que termina con CommandError. Devuelve (salida, error)."""
    salida = io.StringIO()
    with pytest.raises(CommandError) as error:
        call_command("cerrar_y_expirar", stdout=salida)
    return salida.getvalue(), str(error.value)


def ultima_fila():
    return EjecucionTarea.objects.order_by("-id").first()


def contadores(fila):
    """(reservas_cerradas, solicitudes_expiradas) de una fila de ejecucion_tarea."""
    return fila.reservas_cerradas, fila.solicitudes_expiradas


def falla_con(excepcion):
    """Un paso que falla con esa excepcion, para reemplazar una de las funciones."""

    def paso(ahora):
        raise excepcion

    return paso


# ------------------------------------------------------------ criterios 1 y 2


@pytest.mark.django_db
def test_c1_c2_cierra_la_tutoria_terminada_y_expira_la_solicitud(pendientes):
    terminada, solicitud = pendientes
    antes = timezone.now()

    salida = correr()

    assert salida == CERRO_Y_EXPIRO
    # Criterio 1: REALIZADA, sin cerrada_en, y el bloque sigue OCUPADO.
    assert como_esta(terminada) == (EstadoReserva.REALIZADA, None)
    bloque_de_la_tutoria = BloqueDisponibilidad.objects.get(pk=terminada.bloque_id)
    assert bloque_de_la_tutoria.estado == EstadoBloque.OCUPADO
    # Criterio 2: EXPIRADA, con cerrada_en en la hora de la ejecucion.
    estado, cerrada_en = como_esta(solicitud)
    assert estado == EstadoReserva.EXPIRADA
    assert antes <= cerrada_en <= timezone.now()


@pytest.mark.django_db
def test_sin_nada_que_cambiar_dice_0_y_0(tutora, camila, asignatura):
    # Una tutoria en curso, que todavia no termina, y una solicitud de un
    # bloque futuro.
    en_curso = reserva(
        bloque(tutora, -30, 30), camila, asignatura, EstadoReserva.CONFIRMADA
    )
    futura = reserva(bloque(tutora, 60, 120), camila, asignatura)

    assert correr() == NADA

    assert como_esta(en_curso) == (EstadoReserva.CONFIRMADA, None)
    assert como_esta(futura) == (EstadoReserva.SOLICITADA, None)
    fila = ultima_fila()
    assert contadores(fila) == (0, 0)
    assert fila.error is None


# ------------------------------------------------------------ criterio 3 (R-18)


@pytest.mark.django_db
def test_c3_cada_ejecucion_deja_una_fila_nueva_con_lo_que_hizo(
    tutora, camila, asignatura
):
    # Dos tutorias que ya terminaron y tres solicitudes de un bloque en curso:
    # numeros distintos, para que no se confundan las dos columnas.
    for desde in (-300, -180):
        reserva(
            bloque(tutora, desde, desde + 60),
            camila,
            asignatura,
            EstadoReserva.CONFIRMADA,
        )
    en_curso = bloque(tutora, -30, 30)
    for estudiante in (camila, persona("Diego", "Herrera"), persona("Fernanda")):
        reserva(en_curso, estudiante, asignatura)
    antes = EjecucionTarea.objects.count()

    salida = correr()

    assert salida == "cerrar_y_expirar: 2 reservas cerradas, 3 solicitudes expiradas.\n"
    assert EjecucionTarea.objects.count() == antes + 1
    fila = ultima_fila()
    assert fila.comando == "cerrar_y_expirar"
    assert contadores(fila) == (2, 3)
    assert fila.error is None
    assert fila.terminada_en is not None
    assert fila.terminada_en >= fila.iniciada_en
    # Esas dos columnas son de sincronizar_copias (HU-19).
    assert (fila.refs_sincronizadas, fila.perfiles_desactivados) == (0, 0)


@pytest.mark.django_db
def test_c3_si_un_paso_falla_el_otro_corre_y_la_fila_guarda_el_error(
    pendientes, monkeypatch
):
    terminada, solicitud = pendientes
    monkeypatch.setattr(
        comando, "cerrar_realizadas", falla_con(RuntimeError("falla de prueba"))
    )

    salida, error = correr_con_error()

    assert error == "cerrar: RuntimeError: falla de prueba"
    fila = ultima_fila()
    assert fila.error == "cerrar: RuntimeError: falla de prueba"
    assert fila.terminada_en is not None
    # El paso expirar corrio igual.
    assert contadores(fila) == (0, 1)
    assert como_esta(terminada) == (EstadoReserva.CONFIRMADA, None)
    assert como_esta(solicitud)[0] == EstadoReserva.EXPIRADA
    assert salida == "cerrar_y_expirar: 0 reservas cerradas, 1 solicitud expirada.\n"


@pytest.mark.django_db
def test_c3_si_fallan_los_dos_pasos_la_fila_guarda_los_dos_errores(
    pendientes, monkeypatch
):
    terminada, solicitud = pendientes
    monkeypatch.setattr(
        comando, "cerrar_realizadas", falla_con(RuntimeError("falla de prueba"))
    )
    monkeypatch.setattr(
        comando, "expirar_solicitudes", falla_con(ValueError("otra falla"))
    )

    salida, error = correr_con_error()

    esperado = "cerrar: RuntimeError: falla de prueba; expirar: ValueError: otra falla"
    assert error == esperado
    fila = ultima_fila()
    assert fila.error == esperado
    assert fila.terminada_en is not None
    assert contadores(fila) == (0, 0)
    assert como_esta(terminada) == (EstadoReserva.CONFIRMADA, None)
    assert como_esta(solicitud) == (EstadoReserva.SOLICITADA, None)
    assert salida == NADA


@pytest.mark.django_db
def test_c3_un_error_de_la_base_deshace_solo_su_paso(pendientes, monkeypatch):
    """El paso cerrar alcanza a cerrar la tutoria y despues falla en la base."""
    terminada, solicitud = pendientes

    def cierra_y_falla(ahora):
        cerrar_realizadas(ahora)
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 / 0")

    monkeypatch.setattr(comando, "cerrar_realizadas", cierra_y_falla)

    _, error = correr_con_error()

    assert error.startswith("cerrar: ")
    fila = ultima_fila()
    assert fila.error == error
    assert fila.terminada_en is not None
    # Lo que alcanzo a hacer el paso cerrar se deshizo. El paso expirar corrio
    # y lo suyo quedo guardado.
    assert como_esta(terminada) == (EstadoReserva.CONFIRMADA, None)
    assert como_esta(solicitud)[0] == EstadoReserva.EXPIRADA
    assert contadores(fila) == (0, 1)


@pytest.mark.django_db
def test_c3_un_error_de_400_caracteres_queda_cortado_en_300(monkeypatch):
    falla = falla_con(RuntimeError("x" * 400))
    monkeypatch.setattr(comando, "cerrar_realizadas", falla)

    _, error = correr_con_error()

    completo = "cerrar: RuntimeError: " + "x" * 400
    assert error == completo
    fila = ultima_fila()
    assert fila.error == completo[:300]
    assert len(fila.error) == 300
    assert fila.terminada_en is not None


# ------------------------------------------------------------ criterio 4


@pytest.mark.django_db
def test_c4_dos_veces_seguidas_la_segunda_no_cambia_nada(pendientes):
    terminada, solicitud = pendientes
    antes = EjecucionTarea.objects.count()

    primera = correr()
    despues_de_la_primera = [como_esta(terminada), como_esta(solicitud)]
    segunda = correr()

    assert (primera, segunda) == (CERRO_Y_EXPIRO, NADA)
    # El estado y cerrada_en quedan como los dejo la primera.
    assert [como_esta(terminada), como_esta(solicitud)] == despues_de_la_primera
    assert despues_de_la_primera[0] == (EstadoReserva.REALIZADA, None)
    assert despues_de_la_primera[1][0] == EstadoReserva.EXPIRADA
    # Una fila por ejecucion, de la mas antigua a la mas nueva; la segunda,
    # con 0 y 0.
    assert EjecucionTarea.objects.count() == antes + 2
    filas = list(EjecucionTarea.objects.order_by("-id")[:2])[::-1]
    assert [contadores(fila) for fila in filas] == [(1, 1), (0, 0)]
    for fila in filas:
        assert fila.comando == "cerrar_y_expirar"
        assert fila.error is None
        assert fila.terminada_en is not None


@pytest.mark.django_db
def test_los_dos_pasos_usan_el_mismo_ahora(pendientes, monkeypatch):
    recibidos = []

    def anotar(funcion):
        def paso(ahora):
            recibidos.append(ahora)
            return funcion(ahora)

        return paso

    cerrar, expirar = comando.cerrar_realizadas, comando.expirar_solicitudes
    monkeypatch.setattr(comando, "cerrar_realizadas", anotar(cerrar))
    monkeypatch.setattr(comando, "expirar_solicitudes", anotar(expirar))

    assert correr() == CERRO_Y_EXPIRO

    assert len(recibidos) == 2
    assert recibidos[0] == recibidos[1]
    fila = ultima_fila()
    assert fila.iniciada_en <= recibidos[0] <= fila.terminada_en
    # La solicitud expirada queda con ese ahora en cerrada_en.
    assert como_esta(pendientes[1]) == (EstadoReserva.EXPIRADA, recibidos[0])
