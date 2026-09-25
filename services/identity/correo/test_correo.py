import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


def test_el_comando_envia_un_correo_desde_identidad(mailoutbox, settings):
    call_command("enviar_correo_prueba", "--para", "prueba@duocuc.cl")

    assert len(mailoutbox) == 1
    correo = mailoutbox[0]
    assert correo.to == ["prueba@duocuc.cl"]
    assert correo.from_email == settings.DEFAULT_FROM_EMAIL
    assert "Correo de prueba" in correo.subject


def test_sin_bandeja_el_comando_falla_con_un_mensaje_claro(settings):
    # Se fuerza el envio real contra un puerto donde nadie escucha.
    settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    settings.EMAIL_HOST = "127.0.0.1"
    settings.EMAIL_PORT = 9
    settings.EMAIL_TIMEOUT = 2

    with pytest.raises(CommandError, match="docker compose ps"):
        call_command("enviar_correo_prueba")
