import io
import sys

import pytest
from django.conf import settings
from django.core.management import call_command

from .management.commands import programador
from .models import EjecucionTarea


class Doble:
    """Reemplaza ejecutar, esperar y reloj: no corre procesos ni duerme."""

    def __init__(self):
        self.ejecutados = []
        self.esperas = []
        self.resultados = {}
        self.horas = [0.0]

    def ejecutar(self, argumentos):
        self.ejecutados.append(argumentos)
        resultado = self.resultados.get(argumentos[-1], 0)
        if isinstance(resultado, BaseException):
            raise resultado
        return resultado

    def esperar(self, segundos):
        self.esperas.append(segundos)

    def reloj(self):
        # Entrega las horas fijadas en orden y despues repite la ultima.
        if len(self.horas) > 1:
            return self.horas.pop(0)
        return self.horas[0]


@pytest.fixture
def doble(monkeypatch):
    doble = Doble()
    monkeypatch.setattr(programador, "ejecutar", doble.ejecutar)
    monkeypatch.setattr(programador, "esperar", doble.esperar)
    monkeypatch.setattr(programador, "reloj", doble.reloj)
    return doble


def correr(ciclos):
    salida = io.StringIO()
    call_command("programador", ciclos=ciclos, stdout=salida)
    return salida.getvalue()


def argumentos(nombre):
    return [sys.executable, str(settings.BASE_DIR / "manage.py"), nombre]


def test_los_nombres_acordados():
    assert programador.COMANDOS == ("sincronizar_copias", "cerrar_y_expirar")
    assert programador.INTERVALO == 300


def test_un_ciclo_ejecuta_los_dos_comandos_en_orden(doble):
    salida = correr(ciclos=1)

    assert doble.ejecutados == [
        argumentos("sincronizar_copias"),
        argumentos("cerrar_y_expirar"),
    ]
    assert "sincronizar_copias: empieza" in salida
    assert "sincronizar_copias: terminó bien" in salida
    assert "cerrar_y_expirar: terminó bien" in salida
    assert "ciclo terminado" in salida
    assert doble.esperas == []


def test_las_lineas_llevan_el_prefijo_y_la_hora_en_utc(doble):
    salida = correr(ciclos=1)

    lineas = salida.splitlines()
    assert lineas[0].endswith(
        "Corre cada 300 segundos: sincronizar_copias y después cerrar_y_expirar."
    )
    for linea in lineas:
        prefijo, hora, _ = linea.split(" ", 2)
        assert prefijo == "[programador]"
        assert len(hora) == 20 and hora.endswith("Z") and hora[10] == "T"


def test_un_comando_que_falla_no_detiene_al_siguiente(doble):
    # Lo que hace Django con «Unknown command» antes de HU-19.
    doble.resultados["sincronizar_copias"] = 1

    salida = correr(ciclos=1)

    assert doble.ejecutados[-1] == argumentos("cerrar_y_expirar")
    assert "sincronizar_copias: terminó con el código 1" in salida
    assert "cerrar_y_expirar: terminó bien" in salida
    assert "ciclo terminado" in salida


def test_un_comando_que_no_se_puede_lanzar_no_detiene_al_siguiente(doble):
    doble.resultados["sincronizar_copias"] = OSError("sin python")

    salida = correr(ciclos=1)

    assert doble.ejecutados[-1] == argumentos("cerrar_y_expirar")
    assert "sincronizar_copias: no se pudo ejecutar" in salida
    assert "cerrar_y_expirar: terminó bien" in salida


def test_entre_ciclos_espera_el_intervalo_menos_lo_que_duro_el_ciclo(doble):
    doble.horas = [1000.0, 1002.5, 1300.0]

    correr(ciclos=2)

    un_ciclo = [argumentos("sincronizar_copias"), argumentos("cerrar_y_expirar")]
    assert doble.esperas == [297.5]
    assert doble.ejecutados == un_ciclo * 2


def test_si_el_ciclo_dura_mas_que_el_intervalo_no_espera(doble):
    doble.horas = [1000.0, 1400.0, 1400.0]

    correr(ciclos=2)

    assert doble.esperas == []
    assert len(doble.ejecutados) == 4


@pytest.mark.django_db
def test_el_programador_no_escribe_en_ejecucion_tarea(doble):
    antes = list(EjecucionTarea.objects.values_list("id", flat=True))

    correr(ciclos=1)

    assert list(EjecucionTarea.objects.values_list("id", flat=True)) == antes
