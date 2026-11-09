"""Comando sincronizar_copias (HU-19, criterios 4 y 5).

Pone al dia las copias de lectura de Tutorias (tutorias/sincronizacion.py). Lo
ejecuta el programador (HU-37) al arrancar y despues cada 300 segundos: el
nombre esta acordado con HU-37. Tambien se corre a mano en cualquier momento,
por ejemplo en la demostracion (R-18):

    docker compose exec -T tutoring python manage.py sincronizar_copias

Cada ejecucion deja su fila en ejecucion_tarea (A-09). La fila se crea antes
de empezar: si el proceso se corta, terminada_en queda en NULL, que es lo que
indica una ejecucion interrumpida. Si un paso fallo, la fila guarda el error y
el comando termina con CommandError (codigo de salida 1): el programador lo
deja en su registro y sigue con el comando siguiente.
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tutorias.models import EjecucionTarea
from tutorias.sincronizacion import sincronizar

# ejecucion_tarea.error es varchar(300).
LARGO_DEL_ERROR = 300


def cantidad(numero, singular, plural):
    """«1 perfil desactivado», «0 perfiles desactivados»."""
    return f"{numero} {singular if numero == 1 else plural}"


class Command(BaseCommand):
    help = (
        "Pone al día las copias de lectura de Tutorías (usuario_ref y "
        "asignatura_ref) y desactiva los perfiles de tutor que ya no cumplen "
        "RN-01. Lo ejecuta el programador cada cinco minutos (AD-10)."
    )

    def handle(self, *args, **opciones):
        fila = EjecucionTarea.objects.create(comando="sincronizar_copias")

        resultado = sincronizar()

        errores = "; ".join(resultado.errores)
        fila.refs_sincronizadas = resultado.refs_sincronizadas
        fila.perfiles_desactivados = resultado.perfiles_desactivados
        fila.error = errores[:LARGO_DEL_ERROR] or None
        fila.terminada_en = timezone.now()
        # La fila se guarda tambien cuando hubo error: la ejecucion termino.
        fila.save(
            update_fields=[
                "refs_sincronizadas",
                "perfiles_desactivados",
                "error",
                "terminada_en",
            ]
        )

        copias = cantidad(
            resultado.refs_sincronizadas, "copia sincronizada", "copias sincronizadas"
        )
        perfiles = cantidad(
            resultado.perfiles_desactivados,
            "perfil desactivado",
            "perfiles desactivados",
        )
        self.stdout.write(f"sincronizar_copias: {copias}, {perfiles}.")
        if errores:
            raise CommandError(errores)
