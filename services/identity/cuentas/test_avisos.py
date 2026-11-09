"""Avisos por correo de las reservas: POST /internal/avisos (HU-16).

Identidad no llama a otros servicios, asi que estas pruebas no necesitan
dobles: el cuerpo es el que arma pedir_aviso en Tutorias, y el correo no sale,
queda en mailoutbox (pytest-django).
"""

import uuid

import pytest
from django.core.management import call_command

from . import correos
from .models import AvisoCorreo, EstadoAviso, Usuario
from .tokens import emitir_acceso, leer_clave

URL = "/api/identity/v1/internal/avisos"
CLAVE_PRUEBA = "clave-de-prueba"
RESERVA = "70000000-0000-4000-8000-000000000099"
FRONTEND = "https://tutorias.test/app"
RESERVAS_HTML = f"{FRONTEND}/reservas.html"
TUTORES_HTML = f"{FRONTEND}/tutores.html"
NOVIEMBRE = "viernes 6 de noviembre de 2026, de 18:00 a 19:00 (hora de Chile)"
CAMILA = {"nombre": "Camila", "apellido": "Rojas"}
VALENTINA = {"nombre": "Valentina", "apellido": "Soto"}
MEET = "https://meet.example.com/tutoria-bdd"
SALA = "Sede Alameda, biblioteca, sala de estudio 2"
PLANTILLA_INVALIDA = (
    "La plantilla tiene que ser un aviso de reserva: SOLICITUD_RECIBIDA, "
    "RESERVA_CONFIRMADA, RESERVA_RECHAZADA o RESERVA_CANCELADA."
)
SIN_MODALIDAD = "Indica la modalidad de la tutoría confirmada: PRESENCIAL o EN_LINEA."
SIN_LUGAR_O_ENLACE = "Indica el lugar o el enlace de la tutoría confirmada."


@pytest.fixture(autouse=True)
def entorno(settings):
    # Como test_registro.py: sin el millon de iteraciones de PBKDF2.
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    # En la integracion continua CLAVE_SERVICIO no existe: nunca se lee del
    # entorno. URL_FRONTEND tampoco: asi se ve que los enlaces salen de ahi.
    settings.CLAVE_SERVICIO = CLAVE_PRUEBA
    settings.URL_FRONTEND = FRONTEND


def cuenta(email, nombre, apellido, **campos):
    return Usuario.objects.create_user(
        email, "clave-segura-1", nombre=nombre, apellido=apellido, **campos
    )


@pytest.fixture
def tutora(db):
    return cuenta(
        "valentina.demo@duocuc.cl", "Valentina", "Soto", email_verificado=True
    )


@pytest.fixture
def estudiante(db):
    return cuenta("camila.demo@duocuc.cl", "Camila", "Rojas", email_verificado=True)


def aviso(usuario_id, plantilla="SOLICITUD_RECIBIDA", referencia_id=RESERVA, **datos):
    """El cuerpo que arma pedir_aviso en Tutorias (tutorias/llamadas.py).

    Por defecto, la solicitud de Camila a la tutora. Cada clave de datos
    reemplaza la del mismo nombre dentro de "datos".
    """
    return {
        "usuario_id": str(usuario_id),
        "plantilla": plantilla,
        "referencia_id": str(referencia_id),
        "datos": {
            "asignatura": {"sigla": "BDD1101", "nombre": "Base de Datos"},
            "inicio_en": "2026-11-06T21:00:00Z",
            "fin_en": "2026-11-06T22:00:00Z",
            "otra_persona": CAMILA,
            "nota": "Quiero repasar la tercera forma normal.",
            "modalidad": None,
            "lugar_o_enlace": None,
            **datos,
        },
    }


def pedir(client, cuerpo, clave=CLAVE_PRUEBA, **cabeceras):
    """POST /internal/avisos, con X-Clave-Servicio si clave no es None."""
    if clave is not None:
        cabeceras["HTTP_X_CLAVE_SERVICIO"] = clave
    return client.post(URL, cuerpo, content_type="application/json", **cabeceras)


# ------------------------------------------------- criterio 1: la clave


def test_con_la_clave_responde_201_y_envia_el_correo_al_destinatario(
    client, settings, tutora, mailoutbox
):
    respuesta = pedir(client, aviso(tutora.id))

    assert respuesta.status_code == 201
    assert respuesta.json() == {"estado": "ENVIADO", "repetido": False}
    [correo] = mailoutbox
    assert correo.to == ["valentina.demo@duocuc.cl"]
    assert correo.from_email == settings.DEFAULT_FROM_EMAIL
    # La direccion no sale de Identidad (AD-11).
    assert "duocuc.cl" not in respuesta.content.decode()


@pytest.mark.parametrize(
    "clave",
    [None, "clave-equivocada", ""],
    ids=["sin_cabecera", "otra_clave", "cabecera_vacia"],
)
def test_sin_la_clave_responde_404_sin_correo_ni_registro(
    client, tutora, mailoutbox, clave
):
    respuesta = pedir(client, aviso(tutora.id), clave=clave)

    assert respuesta.status_code == 404
    assert respuesta.json()["codigo"] == "ruta_no_encontrada"
    assert mailoutbox == []
    assert not AvisoCorreo.objects.exists()


def test_con_clave_servicio_vacia_en_settings_responde_404(
    client, settings, tutora, mailoutbox
):
    settings.CLAVE_SERVICIO = ""

    con_clave = pedir(client, aviso(tutora.id))
    vacia = pedir(client, aviso(tutora.id), clave="")

    for respuesta in (con_clave, vacia):
        assert respuesta.status_code == 404
        assert respuesta.json()["codigo"] == "ruta_no_encontrada"
    assert mailoutbox == []
    assert not AvisoCorreo.objects.exists()


@pytest.fixture
def token_de_la_tutora(settings, tmp_path, tutora):
    """Un token de acceso de verdad, con claves RS256 de prueba (test_perfil.py)."""
    settings.JWT_CLAVE_PRIVADA = str(tmp_path / "jwt_private.pem")
    settings.JWT_CLAVE_PUBLICA = str(tmp_path / "jwt_public.pem")
    call_command("generar_claves_jwt")
    leer_clave.cache_clear()
    yield emitir_acceso(tutora)
    leer_clave.cache_clear()


def test_con_un_token_de_usuario_y_sin_la_clave_responde_404(
    client, tutora, token_de_la_tutora, mailoutbox
):
    respuesta = pedir(
        client,
        aviso(tutora.id),
        clave=None,
        HTTP_AUTHORIZATION=f"Bearer {token_de_la_tutora}",
    )

    assert respuesta.status_code == 404
    assert respuesta.json()["codigo"] == "ruta_no_encontrada"
    assert mailoutbox == []
    assert not AvisoCorreo.objects.exists()


# ------------------------------------- criterio 2: lo que dice cada correo

# (plantilla, a quien, cambios en "datos", asunto, lineas del cuerpo). Tutorias
# manda la nota, la modalidad y el lugar de la reserva en todos los avisos:
# solo la solicitud muestra la nota, y solo la confirmacion, la modalidad.
PLANTILLAS = {
    "solicitud_al_tutor": (
        "SOLICITUD_RECIBIDA",
        "tutora",
        {},
        "Nueva solicitud de tutoría: Base de Datos",
        [
            "Hola, Valentina:",
            "",
            "Camila Rojas te pidió una tutoría de BDD1101 Base de Datos.",
            f"Horario: {NOVIEMBRE}.",
            "Nota de Camila: Quiero repasar la tercera forma normal.",
            "",
            f"Para confirmarla o rechazarla, entra a «Mis reservas»: {RESERVAS_HTML}",
            "Si no la respondes, la solicitud vence cuando empiece el horario.",
        ],
    ),
    "confirmada_en_linea": (
        "RESERVA_CONFIRMADA",
        "estudiante",
        {"otra_persona": VALENTINA, "modalidad": "EN_LINEA", "lugar_o_enlace": MEET},
        "Tu tutoría de Base de Datos está confirmada",
        [
            "Hola, Camila:",
            "",
            "Valentina Soto confirmó tu tutoría de BDD1101 Base de Datos.",
            f"Horario: {NOVIEMBRE}.",
            "Modalidad: En línea",
            f"Enlace: {MEET}",
            "",
            f"Puedes ver el detalle en «Mis reservas»: {RESERVAS_HTML}",
        ],
    ),
    "confirmada_presencial": (
        "RESERVA_CONFIRMADA",
        "estudiante",
        {"otra_persona": VALENTINA, "modalidad": "PRESENCIAL", "lugar_o_enlace": SALA},
        "Tu tutoría de Base de Datos está confirmada",
        [
            "Hola, Camila:",
            "",
            "Valentina Soto confirmó tu tutoría de BDD1101 Base de Datos.",
            f"Horario: {NOVIEMBRE}.",
            "Modalidad: Presencial",
            f"Lugar: {SALA}",
            "",
            f"Puedes ver el detalle en «Mis reservas»: {RESERVAS_HTML}",
        ],
    ),
    "rechazada_al_estudiante": (
        "RESERVA_RECHAZADA",
        "estudiante",
        {"otra_persona": VALENTINA},
        "Tu solicitud de Base de Datos fue rechazada",
        [
            "Hola, Camila:",
            "",
            "Tu solicitud de tutoría de BDD1101 Base de Datos con Valentina Soto, "
            f"para el {NOVIEMBRE}, fue rechazada.",
            "",
            f"Puedes buscar otro horario u otro tutor en: {TUTORES_HTML}",
        ],
    ),
    "cancelada_al_tutor": (
        "RESERVA_CANCELADA",
        "tutora",
        {"modalidad": "EN_LINEA", "lugar_o_enlace": MEET},
        "Se canceló la tutoría de Base de Datos",
        [
            "Hola, Valentina:",
            "",
            "Se canceló la tutoría de BDD1101 Base de Datos con Camila Rojas, "
            f"del {NOVIEMBRE}.",
            "",
            f"Puedes ver tus reservas en «Mis reservas»: {RESERVAS_HTML}",
        ],
    ),
}


@pytest.mark.parametrize(
    "plantilla, quien, datos, asunto, lineas",
    list(PLANTILLAS.values()),
    ids=list(PLANTILLAS),
)
def test_cada_plantilla_arma_su_asunto_y_su_cuerpo(
    client, tutora, estudiante, mailoutbox, plantilla, quien, datos, asunto, lineas
):
    destinatario = {"tutora": tutora, "estudiante": estudiante}[quien]

    respuesta = pedir(client, aviso(destinatario.id, plantilla, **datos))

    assert respuesta.status_code == 201
    [correo] = mailoutbox
    assert correo.to == [destinatario.email]
    assert correo.subject == asunto
    assert correo.body.splitlines() == lineas
    # Texto plano y sin ninguna direccion de correo (AD-11).
    assert correo.alternatives == []
    assert "@" not in correo.body


@pytest.mark.parametrize(
    "inicio_en, fin_en, horario",
    [
        ("2026-11-06T21:00:00Z", "2026-11-06T22:00:00Z", NOVIEMBRE),
        (
            "2027-07-01T21:00:00Z",
            "2027-07-01T22:00:00Z",
            "jueves 1 de julio de 2027, de 17:00 a 18:00 (hora de Chile)",
        ),
    ],
    ids=["horario_de_verano_utc_menos_3", "horario_de_invierno_utc_menos_4"],
)
def test_la_hora_de_chile_sale_de_su_zona_horaria_y_no_de_un_desfase_fijo(
    client, tutora, mailoutbox, inicio_en, fin_en, horario
):
    pedir(client, aviso(tutora.id, inicio_en=inicio_en, fin_en=fin_en))

    [correo] = mailoutbox
    assert f"Horario: {horario}." in correo.body.splitlines()


@pytest.mark.parametrize("nota", [None, ""], ids=["null", "vacia"])
def test_sin_nota_la_solicitud_no_trae_la_linea_de_la_nota(
    client, tutora, mailoutbox, nota
):
    pedir(client, aviso(tutora.id, nota=nota))

    [correo] = mailoutbox
    assert correo.body.splitlines() == [
        "Hola, Valentina:",
        "",
        "Camila Rojas te pidió una tutoría de BDD1101 Base de Datos.",
        f"Horario: {NOVIEMBRE}.",
        "",
        f"Para confirmarla o rechazarla, entra a «Mis reservas»: {RESERVAS_HTML}",
        "Si no la respondes, la solicitud vence cuando empiece el horario.",
    ]


def test_un_nombre_de_asignatura_de_150_caracteres_deja_el_asunto_en_150(
    client, tutora, mailoutbox
):
    nombre = "A" * 150

    respuesta = pedir(
        client, aviso(tutora.id, asignatura={"sigla": "BDD1101", "nombre": nombre})
    )

    assert respuesta.status_code == 201
    asunto = AvisoCorreo.objects.get().asunto
    assert asunto == f"Nueva solicitud de tutoría: {nombre}"[:150]
    assert len(asunto) == 150
    assert mailoutbox[0].subject == asunto


# -------------------------------------- criterio 3: un solo correo por hecho


def test_el_mismo_pedido_dos_veces_envia_un_solo_correo(client, tutora, mailoutbox):
    primera = pedir(client, aviso(tutora.id))
    segunda = pedir(client, aviso(tutora.id))

    assert primera.status_code == 201
    assert primera.json() == {"estado": "ENVIADO", "repetido": False}
    assert segunda.status_code == 200
    assert segunda.json() == {"estado": "ENVIADO", "repetido": True}
    assert len(mailoutbox) == 1
    assert AvisoCorreo.objects.count() == 1


def test_otra_plantilla_u_otro_destinatario_de_la_misma_reserva_si_envian(
    client, tutora, estudiante, mailoutbox
):
    pedir(client, aviso(tutora.id))

    otra_plantilla = pedir(client, aviso(tutora.id, "RESERVA_CANCELADA"))
    otro_destinatario = pedir(client, aviso(estudiante.id, otra_persona=VALENTINA))

    assert otra_plantilla.status_code == 201
    assert otro_destinatario.status_code == 201
    assert [correo.to for correo in mailoutbox] == [
        ["valentina.demo@duocuc.cl"],
        ["valentina.demo@duocuc.cl"],
        ["camila.demo@duocuc.cl"],
    ]
    assert AvisoCorreo.objects.count() == 3


def test_dos_pedidos_iguales_al_mismo_tiempo_los_frena_el_indice(
    client, tutora, mailoutbox, monkeypatch
):
    """El segundo de dos pedidos simultaneos todavia no ve la fila del primero.

    La fila ya esta en la base, pero aviso_existente devuelve None la primera
    vez: el INSERT choca con ux_aviso_idempotente, y se responde con la fila
    que ya estaba (aqui FALLIDO), sin enviar otro correo.
    """
    AvisoCorreo.objects.create(
        usuario=tutora,
        plantilla="SOLICITUD_RECIBIDA",
        asunto="Nueva solicitud de tutoría: Base de Datos",
        referencia_id=RESERVA,
        estado=EstadoAviso.FALLIDO,
        error="La bandeja no respondió.",
    )
    real = correos.aviso_existente
    consultas = []

    def sin_ver_la_fila_la_primera_vez(*argumentos):
        consultas.append(argumentos)
        return None if len(consultas) == 1 else real(*argumentos)

    monkeypatch.setattr(correos, "aviso_existente", sin_ver_la_fila_la_primera_vez)

    respuesta = pedir(client, aviso(tutora.id))

    assert respuesta.status_code == 200
    assert respuesta.json() == {"estado": "FALLIDO", "repetido": True}
    assert len(consultas) == 2
    assert mailoutbox == []
    assert AvisoCorreo.objects.count() == 1


# ----------------------------------- criterio 4: el registro en aviso_correo


def test_un_envio_que_sale_bien_queda_enviado_con_el_asunto_y_la_reserva(
    client, tutora, mailoutbox
):
    pedir(client, aviso(tutora.id))

    fila = AvisoCorreo.objects.get()
    assert fila.usuario_id == tutora.id
    assert fila.plantilla == "SOLICITUD_RECIBIDA"
    assert fila.estado == EstadoAviso.ENVIADO
    assert fila.asunto == "Nueva solicitud de tutoría: Base de Datos"
    assert fila.asunto == mailoutbox[0].subject
    assert fila.referencia_id == uuid.UUID(RESERVA)
    assert fila.error is None


def test_si_la_bandeja_falla_queda_fallido_y_repetirlo_no_lo_reintenta(
    client, tutora, mailoutbox, monkeypatch
):
    intentos = []

    def bandeja_caida(*argumentos, **opciones):
        intentos.append(argumentos)
        raise ConnectionRefusedError(111, "Connection refused " + "x" * 400)

    monkeypatch.setattr(correos, "send_mail", bandeja_caida)

    primera = pedir(client, aviso(tutora.id))
    segunda = pedir(client, aviso(tutora.id))

    assert primera.status_code == 201
    assert primera.json() == {"estado": "FALLIDO", "repetido": False}
    assert segunda.status_code == 200
    assert segunda.json() == {"estado": "FALLIDO", "repetido": True}
    assert len(intentos) == 1
    assert mailoutbox == []
    fila = AvisoCorreo.objects.get()
    assert fila.estado == EstadoAviso.FALLIDO
    assert fila.error.startswith("[Errno 111] Connection refused")
    assert len(fila.error) == 300


def test_el_aviso_sale_aunque_la_cuenta_este_desactivada_o_sin_verificar(
    client, db, mailoutbox
):
    # El aviso es por una reserva que ya existe: no se revisa la cuenta.
    josefa = cuenta(
        "josefa.demo@duocuc.cl",
        "Josefa",
        "Morales",
        activo=False,
        email_verificado=False,
    )

    respuesta = pedir(client, aviso(josefa.id))

    assert respuesta.status_code == 201
    assert [correo.to for correo in mailoutbox] == [["josefa.demo@duocuc.cl"]]


# --------------------------------------------- los cuerpos que no calzan


def sin(diccionario, clave):
    """Una copia del diccionario sin esa clave."""
    return {nombre: valor for nombre, valor in diccionario.items() if nombre != clave}


# (arma el cuerpo con el id del destinatario, donde queda el error en detalles)
CUERPOS_INVALIDOS = {
    "sin_usuario_id": (lambda u: sin(aviso(u), "usuario_id"), ["usuario_id"]),
    "referencia_que_no_es_uuid": (
        lambda u: aviso(u, referencia_id="reserva-1"),
        ["referencia_id"],
    ),
    "plantilla_cuenta_desactivada": (
        lambda u: aviso(u, "CUENTA_DESACTIVADA"),
        ["plantilla"],
    ),
    "plantilla_verificacion_correo": (
        lambda u: aviso(u, "VERIFICACION_CORREO"),
        ["plantilla"],
    ),
    "datos_sin_asignatura": (
        lambda u: {**aviso(u), "datos": sin(aviso(u)["datos"], "asignatura")},
        ["datos", "asignatura"],
    ),
    "fecha_que_no_es_iso_8601": (
        lambda u: aviso(u, inicio_en="06/11/2026 18:00"),
        ["datos", "inicio_en"],
    ),
    "confirmada_sin_modalidad": (
        lambda u: aviso(u, "RESERVA_CONFIRMADA", lugar_o_enlace=MEET),
        ["datos", "modalidad"],
    ),
    "confirmada_sin_lugar_o_enlace": (
        lambda u: aviso(u, "RESERVA_CONFIRMADA", modalidad="EN_LINEA"),
        ["datos", "lugar_o_enlace"],
    ),
    "una_lista": (lambda u: [aviso(u)], ["non_field_errors"]),
}


@pytest.mark.parametrize(
    "armar, ruta", list(CUERPOS_INVALIDOS.values()), ids=list(CUERPOS_INVALIDOS)
)
def test_un_cuerpo_que_no_calza_responde_400_sin_correo_ni_registro(
    client, tutora, mailoutbox, armar, ruta
):
    respuesta = pedir(client, armar(tutora.id))

    assert respuesta.status_code == 400
    assert respuesta.json()["codigo"] == "invalid"
    detalles = respuesta.json()["detalles"]
    for clave in ruta:
        detalles = detalles[clave]
    # Al final de la ruta esta la lista de mensajes de ese campo.
    assert isinstance(detalles, list)
    assert detalles
    assert mailoutbox == []
    assert not AvisoCorreo.objects.exists()


def test_una_plantilla_que_no_es_de_reservas_dice_cuales_acepta(client, tutora):
    respuesta = pedir(client, aviso(tutora.id, "CUENTA_DESACTIVADA"))

    assert respuesta.status_code == 400
    assert respuesta.json()["detalles"] == {"plantilla": [PLANTILLA_INVALIDA]}


def test_la_confirmacion_sin_modalidad_ni_lugar_dice_lo_que_falta(client, tutora):
    cuerpo = aviso(tutora.id, "RESERVA_CONFIRMADA", modalidad="", lugar_o_enlace="")

    respuesta = pedir(client, cuerpo)

    assert respuesta.status_code == 400
    assert respuesta.json() == {
        "codigo": "invalid",
        "mensaje": "La petición tiene datos inválidos.",
        "detalles": {
            "datos": {
                "modalidad": [SIN_MODALIDAD],
                "lugar_o_enlace": [SIN_LUGAR_O_ENLACE],
            }
        },
    }


def test_un_destinatario_que_no_existe_responde_404_usuario_no_encontrado(
    client, db, mailoutbox
):
    respuesta = pedir(client, aviso(uuid.uuid4()))

    assert respuesta.status_code == 404
    assert respuesta.json() == {
        "codigo": "usuario_no_encontrado",
        "mensaje": "El usuario no existe.",
        "detalles": None,
    }
    assert mailoutbox == []
    assert not AvisoCorreo.objects.exists()


def test_get_con_la_clave_responde_405(client, db):
    respuesta = client.get(URL, HTTP_X_CLAVE_SERVICIO=CLAVE_PRUEBA)

    assert respuesta.status_code == 405
    assert respuesta.json()["codigo"] == "method_not_allowed"
