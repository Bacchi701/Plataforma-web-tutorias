"""Administracion de usuarios: GET y PATCH /admin/usuarios (HU-31)."""

import re
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from django.core.management import call_command
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from .models import RefreshToken, Usuario
from .tokens import ALGORITMO, emitir_acceso, leer_clave, verificar_acceso

BASE = "/api/identity/v1"
LISTA = f"{BASE}/admin/usuarios"
CLAVE = "clave-segura-1"
CARRERA = "20000000-0000-4000-8000-000000000001"
SEDE = "30000000-0000-4000-8000-000000000011"
# Cada cuenta se crea un dia despues de la anterior. Los microsegundos prueban
# que creado_en sale sin fraccion de segundo.
INICIO = datetime(2026, 9, 9, 12, 0, 0, 123456, tzinfo=UTC)
CLAVES_DE_UNA_CUENTA = [
    "id",
    "email",
    "nombre",
    "apellido",
    "carrera_id",
    "sede_id",
    "nivel",
    "email_verificado",
    "activo",
    "es_admin",
    "creado_en",
]
EN_UTC_CON_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
NO_ES_ADMINISTRADOR = {
    "codigo": "no_es_administrador",
    "mensaje": "Esta sección es solo para administradores.",
    "detalles": None,
}
CUERPO_INVALIDO = {
    "codigo": "activo_invalido",
    "mensaje": "Envía solo el campo activo, con true o false.",
    "detalles": None,
}
BUSQUEDA_INVALIDA = "Escribe hasta 80 caracteres para buscar a un usuario."
FILTRO_INVALIDO = "El filtro activo tiene que ser true o false."
PAGINA_INVALIDA = "La página tiene que ser un número entero desde 1."
LIMITE_INVALIDO = "El límite tiene que ser un número entero de 1 a 100."


# Como en test_perfil.py: claves RS256 de prueba en tmp_path y un hash rapido.
@pytest.fixture(autouse=True)
def entorno(settings, tmp_path):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    settings.JWT_CLAVE_PRIVADA = str(tmp_path / "jwt_private.pem")
    settings.JWT_CLAVE_PUBLICA = str(tmp_path / "jwt_public.pem")
    call_command("generar_claves_jwt")
    leer_clave.cache_clear()
    yield
    leer_clave.cache_clear()


def crear_cuenta(email, nombre, apellido, dias, **campos):
    """Una cuenta verificada, con la clave CLAVE, creada INICIO + dias."""
    return Usuario.objects.create_user(
        email,
        CLAVE,
        nombre=nombre,
        apellido=apellido,
        email_verificado=True,
        creado_en=INICIO + timedelta(days=dias),
        **campos,
    )


@pytest.fixture
def cuentas(db):
    """El administrador y cinco cuentas, de la mas antigua a la mas nueva.

    Hay dos Camila: en el panel, el correo es lo que las distingue.
    """
    return {
        "admin": crear_cuenta(
            "admin.demo@duocuc.cl", "Admin", "Demo", 0, es_admin=True
        ),
        "valentina": crear_cuenta(
            "valentina.demo@duocuc.cl",
            "Valentina",
            "Soto",
            1,
            carrera_id=CARRERA,
            sede_id=SEDE,
            nivel=6,
        ),
        "matias": crear_cuenta("matias.demo@duocuc.cl", "Matías", "Fuentes", 2),
        "camila": crear_cuenta(
            "camila.demo@duocuc.cl",
            "Camila",
            "Rojas",
            3,
            carrera_id=CARRERA,
            sede_id=SEDE,
            nivel=2,
        ),
        "camila_vidal": crear_cuenta(
            "camila.vidal.demo@duocuc.cl", "Camila", "Vidal", 4
        ),
        "josefa": crear_cuenta(
            "josefa.demo@duocuc.cl", "Josefa", "Morales", 5, activo=False
        ),
    }


def con_sesion(usuario):
    return {"HTTP_AUTHORIZATION": f"Bearer {emitir_acceso(usuario)}"}


def listar(client, usuario, **parametros):
    return client.get(LISTA, parametros, **con_sesion(usuario))


def cambiar(client, usuario, cuenta_id, cuerpo):
    return client.patch(
        f"{LISTA}/{cuenta_id}",
        cuerpo,
        content_type="application/json",
        **con_sesion(usuario),
    )


def entrar(cliente, cuenta):
    """POST /login de verdad: la cookie de renovacion queda en ese cliente."""
    return cliente.post(
        f"{BASE}/login",
        {"email": cuenta.email, "password": CLAVE},
        content_type="application/json",
    )


def correos(respuesta):
    assert respuesta.status_code == 200
    return [cuenta["email"] for cuenta in respuesta.json()["resultados"]]


def sin_revocar(cuenta):
    return RefreshToken.objects.filter(usuario=cuenta, revocado_en__isnull=True).count()


# ------------------------------------------------- criterio 1: la lista


@pytest.mark.django_db
def test_el_administrador_lista_las_cuentas_de_la_mas_nueva_a_la_mas_antigua(
    client, cuentas
):
    respuesta = listar(client, cuentas["admin"])

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert list(cuerpo) == ["total", "pagina", "total_paginas", "limite", "resultados"]
    assert cuerpo["total"] == 6
    assert cuerpo["pagina"] == 1
    assert cuerpo["total_paginas"] == 1
    assert cuerpo["limite"] == 50
    assert correos(respuesta) == [
        "josefa.demo@duocuc.cl",
        "camila.vidal.demo@duocuc.cl",
        "camila.demo@duocuc.cl",
        "matias.demo@duocuc.cl",
        "valentina.demo@duocuc.cl",
        "admin.demo@duocuc.cl",
    ]
    for cuenta in cuerpo["resultados"]:
        # Exactamente estas claves, en este orden: ni password ni ningun hash.
        assert list(cuenta) == CLAVES_DE_UNA_CUENTA
        assert EN_UTC_CON_Z.match(cuenta["creado_en"])
    for usuario in cuentas.values():
        assert usuario.password not in respuesta.content.decode()
    assert cuerpo["resultados"][2] == {
        "id": str(cuentas["camila"].id),
        "email": "camila.demo@duocuc.cl",
        "nombre": "Camila",
        "apellido": "Rojas",
        "carrera_id": CARRERA,
        "sede_id": SEDE,
        "nivel": 2,
        "email_verificado": True,
        "activo": True,
        "es_admin": False,
        "creado_en": "2026-09-12T12:00:00Z",
    }
    assert cuerpo["resultados"][5] == {
        "id": str(cuentas["admin"].id),
        "email": "admin.demo@duocuc.cl",
        "nombre": "Admin",
        "apellido": "Demo",
        "carrera_id": None,
        "sede_id": None,
        "nivel": None,
        "email_verificado": True,
        "activo": True,
        "es_admin": True,
        "creado_en": "2026-09-09T12:00:00Z",
    }
    assert cuerpo["resultados"][0]["activo"] is False


@pytest.mark.django_db
def test_buscar_por_nombre_o_apellido_sin_distinguir_mayusculas(client, cuentas):
    admin = cuentas["admin"]

    assert correos(listar(client, admin, buscar="rojas")) == ["camila.demo@duocuc.cl"]
    assert correos(listar(client, admin, buscar="ROJAS")) == ["camila.demo@duocuc.cl"]
    # Cada palabra tiene que aparecer: «camila» sola trae a las dos Camila.
    assert correos(listar(client, admin, buscar="camila")) == [
        "camila.vidal.demo@duocuc.cl",
        "camila.demo@duocuc.cl",
    ]
    assert correos(listar(client, admin, buscar="  camila   rojas ")) == [
        "camila.demo@duocuc.cl"
    ]
    # Las tildes si cuentan: identity_db no tiene la extension unaccent.
    assert correos(listar(client, admin, buscar="Matías")) == ["matias.demo@duocuc.cl"]
    assert correos(listar(client, admin, buscar="matias")) == []
    assert listar(client, admin, buscar="zzz").json() == {
        "total": 0,
        "pagina": 1,
        "total_paginas": 1,
        "limite": 50,
        "resultados": [],
    }


@pytest.mark.django_db
def test_el_filtro_activo_deja_solo_las_cuentas_en_ese_estado(client, cuentas):
    admin = cuentas["admin"]

    desactivadas = listar(client, admin, activo="false")
    activas = listar(client, admin, activo="true")

    assert correos(desactivadas) == ["josefa.demo@duocuc.cl"]
    assert desactivadas.json()["total"] == 1
    assert activas.json()["total"] == 5
    assert "josefa.demo@duocuc.cl" not in correos(activas)
    # Se combina con la busqueda.
    assert listar(client, admin, buscar="josefa", activo="true").json()["total"] == 0


@pytest.mark.django_db
def test_las_paginas_y_sus_bordes(client, cuentas):
    admin = cuentas["admin"]

    primera = listar(client, admin, limite="2")
    tercera = listar(client, admin, pagina="3", limite="2")
    mas_alla = listar(client, admin, pagina="4", limite="2")

    assert correos(primera) == ["josefa.demo@duocuc.cl", "camila.vidal.demo@duocuc.cl"]
    assert primera.json()["total"] == 6
    assert primera.json()["total_paginas"] == 3
    assert primera.json()["limite"] == 2
    assert correos(tercera) == ["valentina.demo@duocuc.cl", "admin.demo@duocuc.cl"]
    assert tercera.json()["pagina"] == 3
    # Una pagina mas alla de la ultima: 200 con resultados vacio.
    assert correos(mas_alla) == []
    assert mas_alla.json()["pagina"] == 4
    assert mas_alla.json()["total"] == 6
    assert correos(listar(client, admin, pagina="9" * 30)) == []
    # Los bordes que se aceptan.
    assert correos(listar(client, admin, limite="1")) == ["josefa.demo@duocuc.cl"]
    assert listar(client, admin, limite="100").json()["limite"] == 100
    assert correos(listar(client, admin, buscar="a" * 80)) == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    "parametros, codigo, mensaje",
    [
        ({"buscar": "a" * 81}, "busqueda_invalida", BUSQUEDA_INVALIDA),
        ({"buscar": "rojas\x00"}, "busqueda_invalida", BUSQUEDA_INVALIDA),
        ({"activo": "si"}, "activo_invalido", FILTRO_INVALIDO),
        ({"activo": "True"}, "activo_invalido", FILTRO_INVALIDO),
        ({"activo": ""}, "activo_invalido", FILTRO_INVALIDO),
        ({"pagina": "0"}, "pagina_invalida", PAGINA_INVALIDA),
        ({"pagina": "abc"}, "pagina_invalida", PAGINA_INVALIDA),
        ({"limite": "0"}, "limite_invalido", LIMITE_INVALIDO),
        ({"limite": "101"}, "limite_invalido", LIMITE_INVALIDO),
    ],
    ids=[
        "buscar_81",
        "buscar_nulo",
        "activo_si",
        "activo_mayuscula",
        "activo_vacio",
        "pagina_0",
        "pagina_abc",
        "limite_0",
        "limite_101",
    ],
)
def test_un_parametro_invalido_responde_400(
    client, cuentas, parametros, codigo, mensaje
):
    respuesta = listar(client, cuentas["admin"], **parametros)

    assert respuesta.status_code == 400
    assert respuesta.json() == {"codigo": codigo, "mensaje": mensaje, "detalles": None}


def consultas_de_la_lista(client, cabecera):
    with CaptureQueriesContext(connection) as consultas:
        respuesta = client.get(LISTA, **cabecera)
    assert respuesta.status_code == 200
    return len(consultas), respuesta.json()["total"]


@pytest.mark.django_db
def test_la_lista_hace_las_mismas_consultas_con_3_y_con_10_cuentas(client):
    admin = crear_cuenta("admin.demo@duocuc.cl", "Admin", "Demo", 0, es_admin=True)
    for numero in range(1, 3):
        crear_cuenta(f"cuenta{numero}.demo@duocuc.cl", "Cuenta", str(numero), numero)
    cabecera = con_sesion(admin)
    con_3 = consultas_de_la_lista(client, cabecera)

    for numero in range(3, 10):
        crear_cuenta(f"cuenta{numero}.demo@duocuc.cl", "Cuenta", str(numero), numero)
    con_10 = consultas_de_la_lista(client, cabecera)

    assert (con_3[1], con_10[1]) == (3, 10)
    # La del token, la que cuenta y la que trae la pagina.
    assert con_3[0] == con_10[0] == 3


# ------------------------------------ criterio 2: desactivar cierra las sesiones


@pytest.mark.django_db
def test_desactivar_revoca_sus_sesiones_y_ya_no_puede_entrar(client, cuentas):
    admin = cuentas["admin"]
    camila = cuentas["camila"]
    valentina = cuentas["valentina"]
    # Dos sesiones abiertas de Camila, cada una con su cookie, y una de Valentina.
    computador, celular, de_valentina = Client(), Client(), Client()
    assert entrar(computador, camila).status_code == 200
    assert entrar(celular, camila).status_code == 200
    assert entrar(de_valentina, valentina).status_code == 200
    # Y una sesion que Camila ya habia cerrado.
    cerrada_en = INICIO + timedelta(days=21)
    cerrada = RefreshToken.objects.create(
        usuario=camila,
        token_hash="c" * 64,
        creado_en=INICIO + timedelta(days=20),
        expira_en=INICIO + timedelta(days=27),
        revocado_en=cerrada_en,
    )

    respuesta = cambiar(client, admin, camila.id, {"activo": False})

    assert respuesta.status_code == 200
    assert list(respuesta.json()) == [*CLAVES_DE_UNA_CUENTA, "sesiones_revocadas"]
    assert respuesta.json()["activo"] is False
    assert respuesta.json()["sesiones_revocadas"] == 2
    assert Usuario.objects.get(id=camila.id).activo is False
    assert sin_revocar(camila) == 0
    assert RefreshToken.objects.get(id=cerrada.id).revocado_en == cerrada_en
    # No puede volver a entrar ni renovar la sesion.
    otra_vez = entrar(Client(), camila)
    assert otra_vez.status_code == 403
    assert otra_vez.json()["codigo"] == "cuenta_desactivada"
    renovar = celular.post(f"{BASE}/refresh")
    assert renovar.status_code == 401
    assert renovar.json()["codigo"] == "sesion_invalida"
    # Las sesiones de otras cuentas no cambian.
    assert sin_revocar(valentina) == 1
    assert de_valentina.post(f"{BASE}/refresh").status_code == 200


@pytest.mark.django_db
def test_activarla_le_deja_volver_a_entrar_sin_revivir_sus_sesiones(client, cuentas):
    admin, camila = cuentas["admin"], cuentas["camila"]
    celular = Client()
    assert entrar(celular, camila).status_code == 200
    assert cambiar(client, admin, camila.id, {"activo": False}).status_code == 200
    renovaciones = RefreshToken.objects.count()

    respuesta = cambiar(client, admin, camila.id, {"activo": True})

    assert respuesta.status_code == 200
    assert respuesta.json()["activo"] is True
    assert respuesta.json()["sesiones_revocadas"] == 0
    assert Usuario.objects.get(id=camila.id).activo is True
    # No se crea ninguna sesion, y la que se revoco sigue revocada.
    assert RefreshToken.objects.count() == renovaciones
    assert celular.post(f"{BASE}/refresh").status_code == 401
    assert entrar(Client(), camila).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize(
    "nombre, activo",
    [("josefa", False), ("camila", True)],
    ids=["ya_desactivada", "ya_activa"],
)
def test_si_ya_estaba_en_ese_estado_no_cambia_nada(client, cuentas, nombre, activo):
    cuenta = cuentas[nombre]
    antes = Usuario.objects.values().get(id=cuenta.id)

    respuesta = cambiar(client, cuentas["admin"], cuenta.id, {"activo": activo})

    assert respuesta.status_code == 200
    assert respuesta.json()["activo"] is activo
    assert respuesta.json()["sesiones_revocadas"] == 0
    assert Usuario.objects.values().get(id=cuenta.id) == antes


# ------------------------------- criterio 3: solo con la marca de administrador


@pytest.mark.django_db
def test_sin_la_marca_de_administrador_responde_403_y_nada_cambia(client, cuentas):
    valentina, camila = cuentas["valentina"], cuentas["camila"]
    antes = list(Usuario.objects.values().order_by("id"))

    lista = listar(client, valentina)
    cambio = cambiar(client, valentina, camila.id, {"activo": False})

    assert (lista.status_code, lista.json()) == (403, NO_ES_ADMINISTRADOR)
    assert (cambio.status_code, cambio.json()) == (403, NO_ES_ADMINISTRADOR)
    assert list(Usuario.objects.values().order_by("id")) == antes


@pytest.mark.django_db
def test_sin_un_token_valido_responde_401(client, cuentas):
    camila = cuentas["camila"]
    ruta = f"{LISTA}/{camila.id}"
    falso = {"HTTP_AUTHORIZATION": "Bearer abc.def.ghi"}
    cuerpo = {"activo": False}

    sin_token = [
        client.get(LISTA),
        client.patch(ruta, cuerpo, content_type="application/json"),
    ]
    con_token_falso = [
        client.get(LISTA, **falso),
        client.patch(ruta, cuerpo, content_type="application/json", **falso),
    ]

    for respuesta in sin_token:
        assert respuesta.status_code == 401
        assert respuesta.json()["codigo"] == "not_authenticated"
    for respuesta in con_token_falso:
        assert respuesta.status_code == 401
        assert respuesta.json()["codigo"] == "token_invalido"
    assert Usuario.objects.get(id=camila.id).activo is True


@pytest.mark.django_db
@pytest.mark.parametrize(
    "marca",
    [{}, {"es_admin": False}, {"es_admin": "true"}, {"es_admin": 1}],
    ids=["sin_es_admin", "es_admin_false", "es_admin_texto", "es_admin_1"],
)
def test_la_marca_sale_del_token_y_solo_vale_un_true(client, cuentas, settings, marca):
    admin = cuentas["admin"]
    # Las reclamaciones de emitir_acceso, sin es_admin o con otro valor.
    reclamaciones = verificar_acceso(emitir_acceso(admin))
    del reclamaciones["es_admin"]
    firmado = jwt.encode(
        {**reclamaciones, **marca},
        leer_clave(settings.JWT_CLAVE_PRIVADA),
        algorithm=ALGORITMO,
    )

    respuesta = client.get(LISTA, HTTP_AUTHORIZATION=f"Bearer {firmado}")

    # La cuenta es administradora en la base y con su token de verdad entra.
    assert listar(client, admin).status_code == 200
    assert (respuesta.status_code, respuesta.json()) == (403, NO_ES_ADMINISTRADOR)


@pytest.mark.django_db
def test_un_administrador_desactivado_recibe_401(client, cuentas):
    admin = cuentas["admin"]
    Usuario.objects.filter(id=admin.id).update(activo=False)

    respuesta = listar(client, admin)

    assert respuesta.status_code == 401
    assert respuesta.json()["codigo"] == "cuenta_inactiva"


# ------------------------------- criterio 4: el token de acceso hasta que vence


@pytest.mark.django_db
def test_el_token_de_la_cuenta_desactivada_sigue_firmado_pero_identidad_lo_rechaza(
    client, cuentas
):
    camila = cuentas["camila"]
    token = entrar(Client(), camila).json()["token_acceso"]
    cabecera = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
    assert client.get(f"{BASE}/yo", **cabecera).status_code == 200

    desactivada = cambiar(client, cuentas["admin"], camila.id, {"activo": False})

    assert desactivada.status_code == 200
    # La firma sigue valida hasta que vence: es lo unico que revisan Tutorias
    # y Pagos (Pilar 2, seccion 5.3).
    assert verificar_acceso(token)["sub"] == str(camila.id)
    yo = client.get(f"{BASE}/yo", **cabecera)
    assert yo.status_code == 401
    assert yo.json()["codigo"] == "cuenta_inactiva"


# ------------------------------------------------------------------ ademas


@pytest.mark.django_db
def test_una_cuenta_que_no_existe_responde_404(client, cuentas):
    respuesta = cambiar(client, cuentas["admin"], uuid.uuid4(), {"activo": False})

    assert respuesta.status_code == 404
    assert respuesta.json() == {
        "codigo": "usuario_no_encontrado",
        "mensaje": "El usuario no existe.",
        "detalles": None,
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    "cuerpo",
    [
        {},
        {"activo": "false"},
        {"activo": 0},
        {"activo": None},
        {"activo": False, "es_admin": True},
        [{"activo": False}],
    ],
    ids=["vacio", "texto", "cero", "null", "con_es_admin", "lista"],
)
def test_un_cuerpo_que_no_es_solo_activo_responde_400_y_no_cambia_nada(
    client, cuentas, cuerpo
):
    camila = cuentas["camila"]
    antes = Usuario.objects.values().get(id=camila.id)

    respuesta = cambiar(client, cuentas["admin"], camila.id, cuerpo)

    assert (respuesta.status_code, respuesta.json()) == (400, CUERPO_INVALIDO)
    assert Usuario.objects.values().get(id=camila.id) == antes


@pytest.mark.django_db
def test_post_a_la_lista_responde_405(client, cuentas):
    respuesta = client.post(
        LISTA, {}, content_type="application/json", **con_sesion(cuentas["admin"])
    )

    assert respuesta.status_code == 405
    assert respuesta.json()["codigo"] == "method_not_allowed"


@pytest.mark.django_db
def test_el_administrador_no_puede_desactivarse_a_si_mismo(client, cuentas):
    admin = cuentas["admin"]

    respuesta = cambiar(client, admin, admin.id, {"activo": False})

    assert respuesta.status_code == 409
    assert respuesta.json() == {
        "codigo": "cuenta_propia",
        "mensaje": "No puedes desactivar tu propia cuenta.",
        "detalles": None,
    }
    assert Usuario.objects.get(id=admin.id).activo is True
    # Sigue entrando a /admin.
    assert listar(client, admin).status_code == 200
