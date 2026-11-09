"""Correos que envia Identidad (AD-11) y su registro en aviso_correo (A-08)."""

from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction

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


# ------------------------------------------------ avisos de las reservas (HU-16)

# Las plantillas que acepta POST /internal/avisos (internas.py). Las otras dos
# no: VERIFICACION_CORREO la manda el registro, y CUENTA_DESACTIVADA es de
# RF-14 (anexo A, seccion 8), un Should que no se promovio.
PLANTILLAS_DE_RESERVA = (
    PlantillaAviso.SOLICITUD_RECIBIDA,
    PlantillaAviso.RESERVA_CONFIRMADA,
    PlantillaAviso.RESERVA_RECHAZADA,
    PlantillaAviso.RESERVA_CANCELADA,
)
# La modalidad de una tutoria confirmada (RN-07): como se escribe en el correo
# y como se llama su lugar_o_enlace.
MODALIDADES = {
    "PRESENCIAL": ("Presencial", "Lugar"),
    "EN_LINEA": ("En línea", "Enlace"),
}
RESTRICCION_IDEMPOTENTE = "ux_aviso_idempotente"
# Los largos de aviso_correo.asunto y aviso_correo.error.
LARGO_ASUNTO = 150
LARGO_ERROR = 300
# Chile continental tiene horario de verano: la hora sale de la base de zonas
# horarias del sistema, nunca de un desfase fijo. La imagen python:3.12-slim la
# trae (el paquete tzdata de Debian), y el ubuntu-latest de la integracion
# continua tambien: zoneinfo la usa sin instalar nada mas.
ZONA_CHILE = "America/Santiago"
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MESES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def horario_en_chile(inicio, fin):
    """El horario en hora de Chile, como lo muestran los avisos.

    Por ejemplo: «viernes 6 de noviembre de 2026, de 18:00 a 19:00 (hora de
    Chile)». Los dias y los meses salen de DIAS y MESES, no del locale del
    sistema. La zona se carga aqui y no al importar el modulo: si faltara la
    base de zonas horarias, fallarian solo los avisos y no todo Identidad.
    """
    chile = ZoneInfo(ZONA_CHILE)
    inicio, fin = inicio.astimezone(chile), fin.astimezone(chile)
    dia = f"{DIAS[inicio.weekday()]} {inicio.day} de {MESES[inicio.month - 1]}"
    return f"{dia} de {inicio.year}, de {inicio:%H:%M} a {fin:%H:%M} (hora de Chile)"


def armar_aviso(usuario, plantilla, datos):
    """El asunto y el cuerpo, en texto plano, del aviso de una reserva.

    datos es el objeto "datos" del cuerpo de POST /internal/avisos, ya validado
    (DatosDelAviso, en internas.py). El asunto se corta a 150 caracteres, el
    largo de aviso_correo.asunto. Ningun cuerpo lleva una direccion de correo.
    """
    asignatura = datos["asignatura"]["nombre"]
    tutoria = f"{datos['asignatura']['sigla']} {asignatura}"
    persona = datos["otra_persona"]
    otra_persona = f"{persona['nombre']} {persona['apellido']}"
    horario = horario_en_chile(datos["inicio_en"], datos["fin_en"])
    mis_reservas = f"«Mis reservas»: {settings.URL_FRONTEND}/reservas.html"
    saludo = f"Hola, {usuario.nombre}:\n\n"

    if plantilla == PlantillaAviso.SOLICITUD_RECIBIDA:
        asunto = f"Nueva solicitud de tutoría: {asignatura}"
        nota = datos.get("nota")
        linea_nota = f"Nota de {persona['nombre']}: {nota}\n" if nota else ""
        cuerpo = (
            f"{saludo}{otra_persona} te pidió una tutoría de {tutoria}.\n"
            f"Horario: {horario}.\n"
            f"{linea_nota}\n"
            f"Para confirmarla o rechazarla, entra a {mis_reservas}\n"
            "Si no la respondes, la solicitud vence cuando empiece el horario.\n"
        )
    elif plantilla == PlantillaAviso.RESERVA_CONFIRMADA:
        asunto = f"Tu tutoría de {asignatura} está confirmada"
        modalidad, lugar = MODALIDADES[datos["modalidad"]]
        cuerpo = (
            f"{saludo}{otra_persona} confirmó tu tutoría de {tutoria}.\n"
            f"Horario: {horario}.\n"
            f"Modalidad: {modalidad}\n"
            f"{lugar}: {datos['lugar_o_enlace']}\n\n"
            f"Puedes ver el detalle en {mis_reservas}\n"
        )
    elif plantilla == PlantillaAviso.RESERVA_RECHAZADA:
        asunto = f"Tu solicitud de {asignatura} fue rechazada"
        cuerpo = (
            f"{saludo}Tu solicitud de tutoría de {tutoria} con {otra_persona}, "
            f"para el {horario}, fue rechazada.\n\n"
            "Puedes buscar otro horario u otro tutor en: "
            f"{settings.URL_FRONTEND}/tutores.html\n"
        )
    elif plantilla == PlantillaAviso.RESERVA_CANCELADA:
        asunto = f"Se canceló la tutoría de {asignatura}"
        cuerpo = (
            f"{saludo}Se canceló la tutoría de {tutoria} con {otra_persona}, "
            f"del {horario}.\n\n"
            f"Puedes ver tus reservas en {mis_reservas}\n"
        )
    else:
        raise ValueError(f"{plantilla} no es un aviso de reserva")
    return asunto[:LARGO_ASUNTO], cuerpo


def aviso_existente(usuario, plantilla, referencia_id):
    """La fila de aviso_correo de ese hecho (plantilla, reserva y destinatario).

    Devuelve None si todavia no existe.
    """
    return AvisoCorreo.objects.filter(
        usuario=usuario, plantilla=plantilla, referencia_id=referencia_id
    ).first()


def enviar_aviso_de_reserva(usuario, plantilla, referencia_id, datos):
    """Envia el aviso de una reserva una sola vez. Devuelve (aviso, creado).

    - Si ese hecho ya tiene su fila en aviso_correo, no envia nada y devuelve
      (esa fila, False), tambien si quedo FALLIDO.
    - Si no, en una transaccion: crea la fila (ENVIADO, el valor por defecto),
      envia el correo y, si la bandeja falla (OSError: caida, tiempo agotado o
      rechazo SMTP), deja la fila FALLIDO con el error, como
      enviar_verificacion. Devuelve (fila, True).
    - Dos pedidos iguales al mismo tiempo: el INSERT del segundo espera en el
      indice ux_aviso_idempotente hasta que el primero termina, y despues
      choca con ese indice (A-08). Se devuelve (la fila del primero, False),
      sin enviar. Asi lo que impide el segundo correo es el indice de la base,
      no este codigo.

    El correo sale dentro de la transaccion a proposito: si la bandeja demora,
    la fila queda reservada hasta EMAIL_TIMEOUT (10 segundos).
    """
    existente = aviso_existente(usuario, plantilla, referencia_id)
    if existente is not None:
        return existente, False

    asunto, cuerpo = armar_aviso(usuario, plantilla, datos)
    try:
        with transaction.atomic():
            aviso = AvisoCorreo.objects.create(
                usuario=usuario,
                plantilla=plantilla,
                asunto=asunto,
                referencia_id=referencia_id,
            )
            try:
                send_mail(asunto, cuerpo, None, [usuario.email])
            except OSError as error:
                aviso.estado = EstadoAviso.FALLIDO
                aviso.error = str(error)[:LARGO_ERROR]
                aviso.save(update_fields=["estado", "error"])
    except IntegrityError as error:
        # Fuera del bloque atomic, que ya se deshizo. Como guardar_sin_solape de
        # Tutorias: el nombre de la restriccion viene del error de PostgreSQL.
        diagnostico = getattr(error.__cause__, "diag", None)
        if getattr(diagnostico, "constraint_name", None) != RESTRICCION_IDEMPOTENTE:
            raise
        return aviso_existente(usuario, plantilla, referencia_id), False
    return aviso, True
