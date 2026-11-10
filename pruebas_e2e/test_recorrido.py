"""Recorrido completo de la plataforma, de extremo a extremo (HU-34, criterio 1).

Todo por el gateway, como lo haria una persona en el navegador: un tutor y un
estudiante nuevos se registran, verifican su correo con el enlace que llega a
la bandeja y completan su perfil; el tutor declara una asignatura y publica un
bloque; el estudiante lo encuentra y solicita la tutoria; el tutor la
confirma; el estudiante la paga (HU-23); el programador (HU-37) la pasa a
REALIZADA cuando termina el bloque (HU-29), y el estudiante la evalua (HU-25).
Despues, el tutor cancela otra tutoria ya pagada, que se reembolsa (HU-28,
parte B), y el estudiante retira una solicitud (HU-28, parte A). Los pasos 7,
9, 14 y 16 revisan los avisos por correo de HU-16 en la bandeja de Mailpit:
no son criterios de HU-34, y si fallan, los demas pasos siguen.

Cada paso es una funcion numerada, y pytest las corre en el orden del
archivo. Comparten el diccionario del fixture recorrido: cada paso deja ahi lo
que necesitan los siguientes y, si falta porque un paso anterior no termino,
el paso se salta y dice que falta. Asi el informe muestra donde se corto.
Cada paso imprime una linea con lo que hizo y cuanto tardo.

Necesita el sistema levantado con los datos de ejemplo y el programador
corriendo; no necesita la carga de 500 usuarios. Dura entre 4 y 9 minutos,
casi todo esperando el fin del bloque y al programador, que pasa cada 300
segundos. Deja dos cuentas e2e.*@duocuc.cl con sus reservas: volver a cargar
los datos de ejemplo las borra.
"""

import re
import time
from datetime import UTC, datetime, timedelta

import pytest

IDENTIDAD = "/api/identity/v1"
REGISTRO = f"{IDENTIDAD}/registro"
VERIFICAR = f"{IDENTIDAD}/verificar-correo"
LOGIN = f"{IDENTIDAD}/login"
YO = f"{IDENTIDAD}/yo"
CARRERAS = "/api/catalog/v1/carreras"
SEDES = "/api/catalog/v1/sedes"
TUTORIAS = "/api/tutoring/v1"
PERFILES = f"{TUTORIAS}/perfiles"
DISPONIBILIDAD = f"{TUTORIAS}/disponibilidad"
TUTORES = f"{TUTORIAS}/tutores"
RESERVAS = f"{TUTORIAS}/reservas"
PAGOS = "/api/payments/v1/pagos"

# Las dos cuentas nuevas. El correo lleva la hora de la corrida (paso 1).
CLAVE = "Recorrido-e2e-2026"
APELLIDO = "Recorrido"
# RN-01: con nivel 2, el tutor ensena las asignaturas del semestre 1.
NIVEL_TUTOR = 2
NIVEL_ESTUDIANTE = 1
TARIFA = 3000
DESCRIPCION = "Tutor del recorrido de extremo a extremo (HU-34)."
NOTA = "Quiero repasar antes de la prueba."
ENLACE = "https://meet.example.com/recorrido-e2e"
CALIFICACION = 5
COMENTARIO = "Explica claro y con ejemplos."

# El asunto sale de services/identity/cuentas/correos.py, y el token del
# enlace, como en token_del_correo de cuentas/test_registro.py.
ASUNTO_VERIFICACION = "Verifica tu correo · Plataforma de Tutorías"
TOKEN_DEL_ENLACE = re.compile(r"token=([\w-]+)")

# El bloque del recorrido empieza 2 minutos despues de publicarlo y dura 1. El
# programador pasa cada 300 segundos: se le espera hasta 330 despues del fin.
EMPIEZA_EN = timedelta(minutes=2)
DURA = timedelta(minutes=1)
ESPERA_PROGRAMADOR = timedelta(seconds=330)
PAUSA_PROGRAMADOR = 10
# Segundos que se espera el aviso de Pagos a Tutorias (HU-23).
ESPERA_PAGO = 10
PAUSA_PAGO = 0.5
# Los bloques de la cancelacion y del retiro: manana, de una hora y sin
# cruzarse entre ellos (RN-02).
CANCELACION_EN = timedelta(days=1)
RETIRO_EN = timedelta(days=1, hours=2)
UNA_HORA = timedelta(hours=1)

# Lo que cada paso deja en el recorrido, para decir que falta si no esta.
DEJA = {
    "tutor": "la cuenta del tutor (paso 1)",
    "estudiante": "la cuenta del estudiante (paso 1)",
    "semestre_1": "la malla de la carrera (paso 2)",
    "asignatura": "la asignatura declarada (paso 3)",
    "bloque": "el bloque publicado (paso 4)",
    "reserva": "la solicitud (paso 6)",
    "confirmada": "la tutoría confirmada (paso 8)",
    "realizada": "la tutoría realizada (paso 11)",
    "cancelada": "la tutoría cancelada (paso 13)",
    "retirada": "la solicitud retirada (paso 15)",
}


@pytest.fixture(scope="module")
def recorrido():
    """Lo que cada paso deja para los siguientes, para todo el archivo."""
    return {}


# ------------------------------------------------------------ formato


def duracion(segundos):
    """2,4 s, o desde un minuto, 3 min 41 s."""
    if round(segundos, 1) < 60:
        return f"{segundos:.1f} s".replace(".", ",")
    minutos, resto = divmod(round(segundos), 60)
    return f"{minutos} min {resto} s"


def en_utc(instante):
    """ISO 8601 en UTC y con Z, como las fechas de la API."""
    return instante.strftime("%Y-%m-%dT%H:%M:%SZ")


def hora(instante):
    return instante.strftime("%H:%M:%S")


def pesos(monto):
    """3000 -> $3.000."""
    return f"${monto:,}".replace(",", ".")


def en_lista(partes):
    """a; a y b; a, b y c."""
    if len(partes) == 1:
        return partes[0]
    return f"{', '.join(partes[:-1])} y {partes[-1]}"


class Paso:
    """Un paso del recorrido: lo que necesita de los anteriores y su linea."""

    def __init__(self, numero, recorrido):
        self.numero = numero
        self.recorrido = recorrido
        self.inicio = time.monotonic()
        # Con -v, pytest escribe el nombre de la prueba sin cambiar de linea.
        self.salto = "\n"

    def decir(self, texto):
        # Con flush: la salida va a un tubo (docker run y tee), y sin flush se
        # veria recien al final de la corrida.
        print(f"{self.salto}Paso {self.numero}: {texto}", flush=True)
        self.salto = ""

    def necesita(self, *claves):
        """Lo que dejaron los pasos anteriores. Si algo falta, el paso se salta."""
        faltan = [DEJA[clave] for clave in claves if clave not in self.recorrido]
        if faltan:
            motivo = f"falta {en_lista(faltan)}."
            self.decir(f"se salta: {motivo}")
            pytest.skip(f"Se salta: {motivo}")
        return [self.recorrido[clave] for clave in claves]

    def listo(self, texto):
        """La linea del paso: lo que hizo y cuanto tardo."""
        self.decir(f"{texto} ({duracion(time.monotonic() - self.inicio)})")


# ------------------------------------------------------------ ayudantes


def pedir(cliente, esperado, metodo, ruta, cuerpo=None, token=None):
    """El JSON de la respuesta, que tiene que llegar con el estado esperado."""
    estado, respuesta, _ = cliente.pedir(metodo, ruta, cuerpo, token)
    assert estado == esperado, f"{metodo} {ruta} respondió {estado}: {respuesta}"
    return respuesta


def esperar_correo(bandeja, cuenta, asunto):
    """El correo mas nuevo para esa cuenta con ese asunto."""
    correo = bandeja.esperar(cuenta["correo"], asunto)
    assert correo is not None, (
        f"No llegó a la bandeja «{asunto}» para {cuenta['correo']}. Revisa que "
        "tut_mailpit esté Up (docker compose ps) y lo que dicen "
        "docker compose logs --tail=30 tutoring identity."
    )
    return correo


def carrera_con_semestre_1(cliente):
    """La primera carrera de GET /carreras con asignaturas en el semestre 1.

    Devuelve la carrera y las asignaturas de ese semestre de su malla vigente
    (GET /carreras/<id>/asignaturas), en el orden de Catalogo.
    """
    for carrera in pedir(cliente, 200, "GET", CARRERAS):
        ruta = f"{CARRERAS}/{carrera['id']}/asignaturas"
        for semestre in pedir(cliente, 200, "GET", ruta)["semestres"]:
            if semestre["semestre"] == 1 and semestre["asignaturas"]:
                return carrera, semestre["asignaturas"]
    pytest.fail(
        f"Ninguna carrera de GET {CARRERAS} tiene asignaturas en el semestre 1: "
        "carga los datos de ejemplo."
    )


def publicar_bloque(cliente, tutor, inicio, largo):
    """El tutor publica un bloque LIBRE; las fechas van en UTC y con Z."""
    fin = inicio + largo
    datos = {"inicio_en": en_utc(inicio), "fin_en": en_utc(fin)}
    bloque = pedir(cliente, 201, "POST", DISPONIBILIDAD, datos, tutor["token"])
    assert bloque["inicio_en"] == datos["inicio_en"], bloque
    assert bloque["fin_en"] == datos["fin_en"], bloque
    assert bloque["estado"] == "LIBRE", bloque
    return {"id": bloque["id"], "inicio": inicio, "fin": fin}


def solicitar(cliente, estudiante, bloque, asignatura, nota=None):
    """El estudiante solicita el bloque: SOLICITADA, por la tarifa del tutor."""
    datos = {"bloque_id": bloque["id"], "asignatura_id": asignatura["asignatura_id"]}
    if nota is not None:
        datos["nota"] = nota
    reserva = pedir(cliente, 201, "POST", RESERVAS, datos, estudiante["token"])
    assert reserva["estado"] == "SOLICITADA", reserva
    assert reserva["monto"] == TARIFA, reserva
    return reserva


def confirmar(cliente, tutor, reserva_id):
    """El tutor confirma la tutoria en linea, con el enlace (RN-07)."""
    datos = {"modalidad": "EN_LINEA", "lugar_o_enlace": ENLACE}
    ruta = f"{RESERVAS}/{reserva_id}/confirmar"
    reserva = pedir(cliente, 200, "POST", ruta, datos, tutor["token"])
    assert reserva["estado"] == "CONFIRMADA", reserva
    assert reserva["lugar_o_enlace"] == ENLACE, reserva
    return reserva


def pagar(cliente, estudiante, reserva_id):
    """El estudiante crea el pago (PENDIENTE) y simula que se aprueba (PAGADO)."""
    token = estudiante["token"]
    pago = pedir(cliente, 201, "POST", PAGOS, {"reserva_id": reserva_id}, token)
    assert pago["estado"] == "PENDIENTE", pago
    assert pago["monto"] == TARIFA, pago
    ruta = f"{PAGOS}/{pago['id']}/simular"
    pago = pedir(cliente, 200, "POST", ruta, {"resultado": "EXITOSO"}, token)
    assert pago["estado"] == "PAGADO", pago
    return pago


def esperar_estado_pago(cliente, estudiante, reserva_id, esperado):
    """La reserva, cuando ya muestra ese estado_pago: Pagos se lo avisa."""
    ruta = f"{RESERVAS}/{reserva_id}"
    limite = time.monotonic() + ESPERA_PAGO
    while True:
        reserva = pedir(cliente, 200, "GET", ruta, token=estudiante["token"])
        if reserva["estado_pago"] == esperado:
            return reserva
        if time.monotonic() >= limite:
            pytest.fail(
                f"GET {ruta} sigue con estado_pago {reserva['estado_pago']} "
                f"después de {ESPERA_PAGO} segundos: no llegó el aviso {esperado} "
                "de Pagos. Revisa docker compose logs --tail=30 payments."
            )
        time.sleep(PAUSA_PAGO)


def bloques_publicos(cliente, tutor):
    """Los bloques libres que muestra el perfil publico del tutor."""
    perfil = pedir(cliente, 200, "GET", f"{TUTORES}/{tutor['id']}")
    return [bloque["id"] for bloque in perfil["bloques"]]


# ------------------------------------------------------------ el recorrido


def test_01_registro_y_verificacion(cliente, bandeja, recorrido):
    """Dos cuentas nuevas, verificadas con el enlace del correo y con sesion.

    Son los unicos dos inicios de sesion del recorrido: el gateway deja cinco
    por minuto.
    """
    paso = Paso(1, recorrido)
    marca = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    cuentas = {}
    for rol, nombre in (("tutor", "Tutor"), ("estudiante", "Estudiante")):
        correo = f"e2e.{rol}.{marca}@duocuc.cl"
        datos = {
            "nombre": nombre,
            "apellido": APELLIDO,
            "email": correo,
            "password": CLAVE,
        }
        creada = pedir(cliente, 201, "POST", REGISTRO, datos)
        assert creada["correo_enviado"] is True, (
            f"POST {REGISTRO} no pudo enviar el correo de verificación a "
            f"{correo}: {creada}"
        )
        cuentas[rol] = {"id": creada["id"], "correo": correo}

    for cuenta in cuentas.values():
        mensaje = esperar_correo(bandeja, cuenta, ASUNTO_VERIFICACION)
        texto = bandeja.leer(mensaje["ID"])
        enlace = TOKEN_DEL_ENLACE.search(texto)
        assert enlace is not None, f"El correo no trae el enlace con el token:\n{texto}"
        pedir(cliente, 200, "POST", VERIFICAR, {"token": enlace.group(1)})
        datos = {"email": cuenta["correo"], "password": CLAVE}
        estado, sesion, _ = cliente.pedir("POST", LOGIN, datos)
        assert estado == 200, (
            f"POST {LOGIN} con {cuenta['correo']} respondió {estado}: {sesion}. "
            "Si es 429 o 503, es el límite del gateway (cinco por minuto): espera "
            "un minuto y vuelve a correr las pruebas."
        )
        cuenta["token"] = sesion["token_acceso"]

    recorrido.update(cuentas)
    paso.listo(
        f"el tutor {cuentas['tutor']['correo']} y el estudiante "
        f"{cuentas['estudiante']['correo']} se registran, verifican su correo "
        "con el enlace que llega a la bandeja e inician sesión"
    )


def test_02_perfil(cliente, recorrido):
    """Los dos en una carrera con asignaturas en el semestre 1 y en una sede."""
    paso = Paso(2, recorrido)
    tutor, estudiante = paso.necesita("tutor", "estudiante")
    carrera, semestre_1 = carrera_con_semestre_1(cliente)
    sedes = pedir(cliente, 200, "GET", SEDES)
    assert sedes, f"GET {SEDES} no trae ninguna sede: carga los datos de ejemplo."
    sede = sedes[0]

    for cuenta, nivel in ((tutor, NIVEL_TUTOR), (estudiante, NIVEL_ESTUDIANTE)):
        datos = {"carrera_id": carrera["id"], "sede_id": sede["id"], "nivel": nivel}
        yo = pedir(cliente, 200, "PATCH", YO, datos, cuenta["token"])
        assert {campo: yo[campo] for campo in datos} == datos, yo

    recorrido["semestre_1"] = semestre_1
    paso.listo(
        f"perfiles en {carrera['nombre']} ({carrera['codigo']}), sede "
        f"{sede['nombre']}: el tutor con nivel {NIVEL_TUTOR} y el estudiante con "
        f"nivel {NIVEL_ESTUDIANTE}"
    )


def test_03_declaracion(cliente, recorrido):
    """RN-01: con nivel 2, el tutor declara una asignatura del semestre 1."""
    paso = Paso(3, recorrido)
    tutor, semestre_1 = paso.necesita("tutor", "semestre_1")
    elegida = semestre_1[0]
    datos = {
        "asignatura_id": elegida["id"],
        "tarifa": TARIFA,
        "descripcion": DESCRIPCION,
    }
    perfil = pedir(cliente, 201, "POST", PERFILES, datos, tutor["token"])
    asignatura = perfil["asignatura"]
    assert asignatura["asignatura_id"] == elegida["id"], perfil
    assert perfil["tarifa"] == TARIFA, perfil
    assert perfil["activo"] is True, perfil

    recorrido["asignatura"] = asignatura
    paso.listo(
        f"el tutor declara {asignatura['sigla']} {asignatura['nombre']}, del "
        f"semestre 1, con tarifa {pesos(TARIFA)}"
    )


def test_04_disponibilidad(cliente, recorrido):
    """Un bloque que empieza en 2 minutos y dura 1, en UTC y con Z."""
    paso = Paso(4, recorrido)
    tutor, _ = paso.necesita("tutor", "asignatura")
    inicio = (datetime.now(UTC) + EMPIEZA_EN).replace(microsecond=0)
    bloque = publicar_bloque(cliente, tutor, inicio, DURA)

    recorrido["bloque"] = bloque
    paso.listo(
        f"el tutor publica un bloque de {hora(bloque['inicio'])} a "
        f"{hora(bloque['fin'])} UTC"
    )


def test_05_busqueda(cliente, recorrido):
    """La busqueda por la asignatura trae al tutor, y su perfil, el bloque."""
    paso = Paso(5, recorrido)
    tutor, asignatura, bloque = paso.necesita("tutor", "asignatura", "bloque")
    ruta = f"{TUTORES}?asignatura={asignatura['asignatura_id']}"
    tutores = pedir(cliente, 200, "GET", ruta)
    del_recorrido = [t for t in tutores if t["usuario_id"] == tutor["id"]]
    assert len(del_recorrido) == 1, (
        f"GET {ruta} trae {len(tutores)} tutores, sin el del recorrido "
        f"({tutor['id']})."
    )
    assert del_recorrido[0]["tarifa"] == TARIFA, del_recorrido[0]
    publicos = bloques_publicos(cliente, tutor)
    assert bloque["id"] in publicos, f"El perfil no muestra el bloque: {publicos}"

    paso.listo(
        f"la búsqueda por {asignatura['sigla']} trae {len(tutores)} tutores, "
        f"entre ellos el del recorrido con tarifa {pesos(TARIFA)}, y su perfil "
        "público muestra el bloque"
    )


def test_06_solicitud(cliente, recorrido):
    """El estudiante solicita ese bloque y esa asignatura, con una nota."""
    paso = Paso(6, recorrido)
    estudiante, asignatura, bloque = paso.necesita("estudiante", "asignatura", "bloque")
    reserva = solicitar(cliente, estudiante, bloque, asignatura, NOTA)
    assert reserva["nota"] == NOTA, reserva

    recorrido["reserva"] = reserva["id"]
    paso.listo(
        "el estudiante solicita el bloque, con una nota: la reserva "
        f"{reserva['id']} queda SOLICITADA, por {pesos(reserva['monto'])}"
    )


def test_07_aviso_de_solicitud(bandeja, recorrido):
    """HU-16: al tutor le llega el aviso de la solicitud, con la nota."""
    paso = Paso(7, recorrido)
    tutor, asignatura, _ = paso.necesita("tutor", "asignatura", "reserva")
    asunto = f"Nueva solicitud de tutoría: {asignatura['nombre']}"
    correo = esperar_correo(bandeja, tutor, asunto)
    assert NOTA in bandeja.leer(correo["ID"]), f"«{asunto}» no trae la nota."

    paso.listo(f"llega al tutor «{asunto}», con la nota")


def test_08_confirmacion(cliente, recorrido):
    """El tutor confirma en linea; el bloque sale de su perfil publico."""
    paso = Paso(8, recorrido)
    tutor, bloque, reserva_id = paso.necesita("tutor", "bloque", "reserva")
    confirmar(cliente, tutor, reserva_id)
    recorrido["confirmada"] = reserva_id
    publicos = bloques_publicos(cliente, tutor)
    assert bloque["id"] not in publicos, "El perfil público sigue mostrando el bloque."

    paso.listo(
        f"el tutor la confirma en línea, con el enlace {ENLACE}: queda "
        "CONFIRMADA, y el bloque ya no aparece en su perfil público"
    )


def test_09_aviso_de_confirmacion(bandeja, recorrido):
    """HU-16: al estudiante le llega la confirmacion, con el enlace."""
    paso = Paso(9, recorrido)
    estudiante, asignatura, _ = paso.necesita("estudiante", "asignatura", "confirmada")
    asunto = f"Tu tutoría de {asignatura['nombre']} está confirmada"
    correo = esperar_correo(bandeja, estudiante, asunto)
    assert ENLACE in bandeja.leer(correo["ID"]), f"«{asunto}» no trae el enlace."

    paso.listo(f"llega al estudiante «{asunto}», con el enlace")


def test_10_pago(cliente, recorrido):
    """El pago simulado; Pagos le avisa a Tutorias y la reserva lo muestra."""
    paso = Paso(10, recorrido)
    estudiante, reserva_id = paso.necesita("estudiante", "confirmada")
    pago = pagar(cliente, estudiante, reserva_id)
    esperar_estado_pago(cliente, estudiante, reserva_id, "PAGADO")

    paso.listo(
        f"el estudiante crea el pago {pago['id']} (PENDIENTE) y lo simula "
        "aprobado (PAGADO); la reserva ya muestra estado_pago PAGADO"
    )


def test_11_cierre_por_el_programador(cliente, recorrido):
    """Cuando termina el bloque, el programador pasa la tutoria a REALIZADA.

    Se consulta cada 10 segundos, hasta 330 despues del fin del bloque: el
    programador corre cerrar_y_expirar (HU-29) cada 300.
    """
    paso = Paso(11, recorrido)
    estudiante, bloque, reserva_id = paso.necesita("estudiante", "bloque", "confirmada")
    limite = bloque["fin"] + ESPERA_PROGRAMADOR
    paso.decir(
        f"espera el fin del bloque, a las {hora(bloque['fin'])} UTC, y al "
        f"programador, hasta las {hora(limite)} UTC."
    )
    falta = (bloque["fin"] - datetime.now(UTC)).total_seconds()
    if falta > 0:
        time.sleep(falta)

    ruta = f"{RESERVAS}/{reserva_id}"
    while True:
        reserva = pedir(cliente, 200, "GET", ruta, token=estudiante["token"])
        if reserva["estado"] == "REALIZADA":
            break
        assert reserva["estado"] == "CONFIRMADA", (
            "Mientras se esperaba al programador, la tutoría quedó "
            f"{reserva['estado']}."
        )
        restante = (limite - datetime.now(UTC)).total_seconds()
        if restante <= 0:
            pytest.fail(
                "La tutoría sigue CONFIRMADA "
                f"{ESPERA_PROGRAMADOR.total_seconds():.0f} segundos después del "
                "fin del bloque: el programador no la cerró. Revisa que esté "
                "corriendo (docker compose ps programador) y lo que hizo "
                "(docker compose logs --tail=50 programador)."
            )
        time.sleep(min(PAUSA_PROGRAMADOR, restante))

    recorrido["realizada"] = reserva_id
    despues = (datetime.now(UTC) - bloque["fin"]).total_seconds()
    paso.listo(
        f"el programador la cerró: está REALIZADA {duracion(despues)} después del "
        "fin del bloque"
    )


def test_12_evaluacion(cliente, recorrido):
    """El estudiante evalua con 5; el perfil del tutor muestra su reputacion."""
    paso = Paso(12, recorrido)
    estudiante, tutor, reserva_id = paso.necesita("estudiante", "tutor", "realizada")
    ruta = f"{RESERVAS}/{reserva_id}"
    datos = {"calificacion": CALIFICACION, "comentario": COMENTARIO}
    evaluacion = pedir(
        cliente, 201, "POST", f"{ruta}/evaluacion", datos, estudiante["token"]
    )
    assert evaluacion["calificacion"] == CALIFICACION, evaluacion
    reserva = pedir(cliente, 200, "GET", ruta, token=estudiante["token"])
    assert reserva["estado"] == "EVALUADA", reserva
    perfil = pedir(cliente, 200, "GET", f"{TUTORES}/{tutor['id']}")
    assert perfil["reputacion"] == {"promedio": 5, "total": 1}, perfil["reputacion"]

    paso.listo(
        f"el estudiante la evalúa con {CALIFICACION} y un comentario: queda "
        "EVALUADA, y el perfil público del tutor muestra 1 evaluación con "
        "promedio 5"
    )


def test_13_cancelacion_con_reembolso(cliente, recorrido):
    """HU-28, parte B: el tutor cancela una tutoria pagada y se reembolsa.

    Otra tutoria, en un bloque de manana: el estudiante la solicita, el tutor
    la confirma y el estudiante la paga. Cuando el tutor la cancela, Tutorias
    le pide el reembolso a Pagos y la respuesta ya trae REEMBOLSADO.
    """
    paso = Paso(13, recorrido)
    tutor, estudiante, asignatura = paso.necesita("tutor", "estudiante", "asignatura")
    inicio = (datetime.now(UTC) + CANCELACION_EN).replace(second=0, microsecond=0)
    bloque = publicar_bloque(cliente, tutor, inicio, UNA_HORA)
    reserva_id = solicitar(cliente, estudiante, bloque, asignatura)["id"]
    confirmar(cliente, tutor, reserva_id)
    pagar(cliente, estudiante, reserva_id)
    esperar_estado_pago(cliente, estudiante, reserva_id, "PAGADO")

    ruta = f"{RESERVAS}/{reserva_id}/cancelar"
    cancelada = pedir(cliente, 200, "POST", ruta, token=tutor["token"])
    recorrido["cancelada"] = reserva_id
    assert cancelada["estado"] == "CANCELADA", cancelada
    assert cancelada["estado_pago"] == "REEMBOLSADO", (
        f"La tutoría quedó cancelada con estado_pago {cancelada['estado_pago']}: "
        "el reembolso no se hizo. Revisa docker compose logs --tail=30 tutoring."
    )
    pago = pedir(
        cliente, 200, "GET", f"{PAGOS}?reserva={reserva_id}", token=estudiante["token"]
    )
    assert pago["estado"] == "REEMBOLSADO", pago
    ultimo = pago["intentos"][0]
    assert (ultimo["tipo"], ultimo["resultado"]) == ("REEMBOLSO", "EXITOSO"), pago
    publicos = bloques_publicos(cliente, tutor)
    assert bloque["id"] in publicos, "El bloque no volvió a quedar libre."

    paso.listo(
        "otra tutoría, confirmada y pagada: el tutor la cancela, queda "
        "CANCELADA y REEMBOLSADA en Tutorías y en Pagos, y su bloque vuelve a "
        "estar libre"
    )


def test_14_aviso_de_cancelacion(bandeja, recorrido):
    """HU-16: al estudiante le llega el aviso de la cancelacion."""
    paso = Paso(14, recorrido)
    estudiante, asignatura, _ = paso.necesita("estudiante", "asignatura", "cancelada")
    asunto = f"Se canceló la tutoría de {asignatura['nombre']}"
    esperar_correo(bandeja, estudiante, asunto)

    paso.listo(f"llega al estudiante «{asunto}»")


def test_15_retiro_de_solicitud(cliente, recorrido):
    """HU-28, parte A: el estudiante retira una solicitud sin respuesta.

    Queda CANCELADA, sin pago, y el bloque sigue libre: una solicitud nunca
    lo ocupo.
    """
    paso = Paso(15, recorrido)
    tutor, estudiante, asignatura = paso.necesita("tutor", "estudiante", "asignatura")
    inicio = (datetime.now(UTC) + RETIRO_EN).replace(second=0, microsecond=0)
    bloque = publicar_bloque(cliente, tutor, inicio, UNA_HORA)
    reserva_id = solicitar(cliente, estudiante, bloque, asignatura)["id"]

    ruta = f"{RESERVAS}/{reserva_id}/cancelar"
    retirada = pedir(cliente, 200, "POST", ruta, token=estudiante["token"])
    recorrido["retirada"] = reserva_id
    assert retirada["estado"] == "CANCELADA", retirada
    assert retirada["estado_pago"] is None, retirada
    publicos = bloques_publicos(cliente, tutor)
    assert bloque["id"] in publicos, "El bloque no sigue libre."

    paso.listo(
        "otra solicitud: el estudiante la retira antes de que el tutor "
        "responda; queda CANCELADA, sin pago, y el bloque sigue libre"
    )


def test_16_aviso_de_retiro(bandeja, recorrido):
    """HU-16: al tutor le llega el aviso de la solicitud retirada."""
    paso = Paso(16, recorrido)
    tutor, asignatura, _ = paso.necesita("tutor", "asignatura", "retirada")
    asunto = f"Se canceló la tutoría de {asignatura['nombre']}"
    esperar_correo(bandeja, tutor, asunto)

    paso.listo(f"llega al tutor «{asunto}»")
