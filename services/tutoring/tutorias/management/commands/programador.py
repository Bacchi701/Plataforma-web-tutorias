"""Programador de tareas de Tutorias (AD-10, HU-37).

Al arrancar, y despues cada cinco minutos (INTERVALO), ejecuta en orden los
comandos de COMANDOS: sincronizar_copias (HU-19) y cerrar_y_expirar (HU-29).
Cada uno corre en su propio proceso con python manage.py <comando>: si uno se
cae, no se lleva al programador ni impide que corra el siguiente, y cada
ejecucion parte con su propia conexion a la base. Lo que escribe el comando va
directo al registro del contenedor.

El programador no escribe en ejecucion_tarea ni abre la base: cada comando
registra su propia fila, con su nombre en la columna comando. Asi la fila dice
lo que hizo el comando y no solo que se lanzo.
"""

import subprocess
import sys
import time
from datetime import UTC, datetime

from django.conf import settings
from django.core.management.base import BaseCommand

COMANDOS = ("sincronizar_copias", "cerrar_y_expirar")
# Segundos entre el inicio de un ciclo y el del siguiente.
INTERVALO = 300


# Las pruebas reemplazan estas tres funciones: ninguna corre un proceso de
# verdad ni duerme.
def ejecutar(argumentos):
    """Unica salida a otros procesos. Devuelve el codigo de salida."""
    return subprocess.run(argumentos, check=False).returncode


def esperar(segundos):
    time.sleep(segundos)


def reloj():
    return time.monotonic()


class Command(BaseCommand):
    help = "Ejecuta los comandos de Tutorias al arrancar y cada cinco minutos."

    def add_arguments(self, parser):
        parser.add_argument(
            "--ciclos",
            type=int,
            default=0,
            help="Termina despues de este ciclo, sin esperar. 0 es sin fin.",
        )

    def handle(self, *args, **opciones):
        ciclos = opciones["ciclos"]
        self.escribir(
            f"Corre cada {INTERVALO} segundos: {' y después '.join(COMANDOS)}."
        )
        ciclo = 0
        while True:
            ciclo += 1
            inicio = reloj()
            for nombre in COMANDOS:
                self.correr(nombre)
            self.escribir("ciclo terminado")
            if ciclos and ciclo >= ciclos:
                return
            restante = INTERVALO - (reloj() - inicio)
            if restante > 0:
                esperar(restante)

    def correr(self, nombre):
        self.escribir(f"{nombre}: empieza")
        try:
            codigo = ejecutar(
                [sys.executable, str(settings.BASE_DIR / "manage.py"), nombre]
            )
        except Exception as error:
            # Que un comando no se pueda lanzar no detiene al siguiente.
            self.escribir(f"{nombre}: no se pudo ejecutar ({error!r})")
            return
        if codigo == 0:
            self.escribir(f"{nombre}: terminó bien")
        else:
            self.escribir(f"{nombre}: terminó con el código {codigo}")

    def escribir(self, texto):
        hora = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.stdout.write(f"[programador] {hora} {texto}")
