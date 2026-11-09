"""Comando cerrar_y_expirar (HU-29, criterios 1 a 4).

Cierra las tutorias que ya terminaron y expira las solicitudes sin respuesta,
con las dos funciones de tutorias/por_tiempo.py. Lo ejecuta el programador
(HU-37) al arrancar y despues cada 300 segundos: el nombre esta acordado con
HU-37. Tambien se corre a mano en cualquier momento, por ejemplo antes de
mostrar algo en la demostracion:

    docker compose exec -T tutoring python manage.py cerrar_y_expirar

Cada ejecucion deja su fila en ejecucion_tarea (R-18, A-09). La fila se crea
antes de empezar: si el proceso se corta, terminada_en queda en NULL, que es lo
que indica una ejecucion interrumpida. Los dos pasos usan el mismo ahora y
cada uno corre en su propia transaccion: si uno falla, se deshace solo ese
paso, su error queda anotado como «<paso>: <TipoDeError>: <mensaje>» y el otro
corre igual. Con error, el comando termina con CommandError (codigo de salida
1): el programador lo deja en su registro y sigue con su ciclo.

Es idempotente: los UPDATE solo tocan reservas CONFIRMADA o SOLICITADA, asi
que una segunda ejecucion seguida no encuentra nada que cambiar y deja su fila
con 0 y 0. No llama a otros servicios.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from tutorias.models import EjecucionTarea
from tutorias.por_tiempo import cerrar_realizadas, expirar_solicitudes

# ejecucion_tarea.error es varchar(300).
LARGO_DEL_ERROR = 300


def cantidad(numero, singular, plural):
    """«1 reserva cerrada», «0 solicitudes expiradas»."""
    return f"{numero} {singular if numero == 1 else plural}"


def _paso(nombre, funcion, ahora, errores):
    """Corre un paso en su propia transaccion. Devuelve cuantas reservas cambio.

    Si falla, devuelve 0 y anota «<paso>: <TipoDeError>: <mensaje>» en
    errores. El try va por fuera del with: cuando se anota el error, atomic()
    ya deshizo el paso, y la conexion queda lista para el paso siguiente.
    """
    try:
        with transaction.atomic():
            return funcion(ahora)
    except Exception as error:
        errores.append(f"{nombre}: {type(error).__name__}: {error}")
        return 0


class Command(BaseCommand):
    help = (
        "Cierra las tutorías que ya terminaron (REALIZADA) y expira las "
        "solicitudes sin respuesta (EXPIRADA). Lo ejecuta el programador cada "
        "cinco minutos (AD-10)."
    )

    def handle(self, *args, **opciones):
        fila = EjecucionTarea.objects.create(comando="cerrar_y_expirar")
        ahora = timezone.now()
        errores = []

        # cerrar_realizadas y expirar_solicitudes se leen de este modulo al
        # llamarlas: las pruebas las reemplazan aqui con monkeypatch.
        reservas_cerradas = _paso("cerrar", cerrar_realizadas, ahora, errores)
        solicitudes_expiradas = _paso("expirar", expirar_solicitudes, ahora, errores)

        error = "; ".join(errores)
        fila.reservas_cerradas = reservas_cerradas
        fila.solicitudes_expiradas = solicitudes_expiradas
        fila.error = error[:LARGO_DEL_ERROR] or None
        fila.terminada_en = timezone.now()
        # La fila se guarda tambien cuando hubo error: la ejecucion termino.
        fila.save(
            update_fields=[
                "reservas_cerradas",
                "solicitudes_expiradas",
                "error",
                "terminada_en",
            ]
        )

        cerradas = cantidad(reservas_cerradas, "reserva cerrada", "reservas cerradas")
        expiradas = cantidad(
            solicitudes_expiradas, "solicitud expirada", "solicitudes expiradas"
        )
        self.stdout.write(f"cerrar_y_expirar: {cerradas}, {expiradas}.")
        if error:
            raise CommandError(error)
