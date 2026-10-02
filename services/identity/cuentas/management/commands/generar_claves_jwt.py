"""Genera el par de claves RS256 de los tokens de acceso (una sola vez)."""

from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Genera jwt_private.pem y jwt_public.pem para firmar los tokens."

    def add_arguments(self, parser):
        parser.add_argument(
            "--carpeta",
            help="Carpeta donde dejar las claves. Por defecto, la de settings.",
        )
        parser.add_argument(
            "--forzar",
            action="store_true",
            help="Reemplaza claves que ya existen (cierra todas las sesiones).",
        )

    def handle(self, *args, **opciones):
        privada = Path(settings.JWT_CLAVE_PRIVADA)
        publica = Path(settings.JWT_CLAVE_PUBLICA)
        if opciones["carpeta"]:
            carpeta = Path(opciones["carpeta"])
            privada, publica = carpeta / privada.name, carpeta / publica.name

        if privada.exists() and not opciones["forzar"]:
            raise CommandError(
                f"{privada} ya existe. Usa --forzar solo si quieres reemplazarla."
            )

        clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        privada.parent.mkdir(parents=True, exist_ok=True)
        privada.write_bytes(
            clave.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        publica.write_bytes(
            clave.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Listo: {privada.name} (no se versiona) y {publica.name} "
                f"(se versiona) en {privada.parent}"
            )
        )
