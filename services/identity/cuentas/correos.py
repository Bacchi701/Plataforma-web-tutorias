"""Correos que envia Identidad (AD-11) y su registro en aviso_correo (A-08)."""

from django.conf import settings
from django.core.mail import send_mail

from .models import AvisoCorreo, EstadoAviso, PlantillaAviso

ASUNTO_VERIFICACION = "Verifica tu correo · Plataforma de Tutorías"


def enviar_verificacion(usuario, token):
    """Envia el enlace de verificacion y deja constancia, salga bien o mal.

    Si la bandeja no responde, la cuenta igual queda creada: el aviso queda
    como FALLIDO y el usuario puede pedir otro correo mas adelante.
    """
    enlace = f"{settings.URL_FRONTEND}/verificar.html?token={token}"
    horas = settings.VERIFICACION_HORAS
    cuerpo = (
        f"Hola, {usuario.nombre}:\n\n"
        "Para activar tu cuenta en la Plataforma de Tutorías, abre este enlace:\n\n"
        f"{enlace}\n\n"
        f"El enlace vence en {horas} horas y sirve una sola vez.\n"
        "Si no creaste esta cuenta, ignora este correo.\n"
    )
    aviso = AvisoCorreo(
        usuario=usuario,
        plantilla=PlantillaAviso.VERIFICACION_CORREO,
        asunto=ASUNTO_VERIFICACION,
    )
    try:
        send_mail(ASUNTO_VERIFICACION, cuerpo, None, [usuario.email])
    except OSError as error:
        aviso.estado = EstadoAviso.FALLIDO
        aviso.error = str(error)[:300]
    aviso.save()
    return aviso.estado == EstadoAviso.ENVIADO
