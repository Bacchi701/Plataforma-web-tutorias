from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError

ASUNTO = "Correo de prueba · Plataforma de Tutorías"
CUERPO = (
    "Si lees esto en la bandeja de desarrollo, el servicio de Identidad ya "
    "puede enviar correos (HU-02).\n"
)


class Command(BaseCommand):
    help = "Envia un correo de prueba a la bandeja de desarrollo."

    def add_arguments(self, parser):
        parser.add_argument(
            "--para",
            default="estudiante.prueba@duocuc.cl",
            help="Destinatario ficticio. La bandeja no reenvia nada a internet.",
        )

    def handle(self, *args, **opciones):
        destinatario = opciones["para"]
        try:
            # from_email=None usa DEFAULT_FROM_EMAIL de settings.py.
            send_mail(ASUNTO, CUERPO, None, [destinatario])
        except OSError as error:
            # Conexion rechazada, nombre que no resuelve, tiempo agotado y
            # errores del protocolo SMTP heredan todos de OSError.
            raise CommandError(
                f"No se pudo entregar el correo a {settings.EMAIL_HOST}:"
                f"{settings.EMAIL_PORT} ({error}). Revisa que el contenedor "
                "mailpit este arriba con: docker compose ps"
            ) from error

        self.stdout.write(
            self.style.SUCCESS(
                f"Correo enviado a {destinatario}. "
                "Revisa la bandeja en http://localhost:8025"
            )
        )
