"""Perfil con carrera, nivel y sede: PATCH /yo (HU-10)."""

import uuid

import pytest
from django.core.management import call_command

from .models import Usuario
from .tokens import emitir_acceso, leer_clave

BASE = "/api/identity/v1"
CLAVE = "clave-segura-1"
# Identidad no le pregunta a Catalogo si existen (AD-15): basta con que sean uuid.
CARRERA = "20000000-0000-4000-8000-000000000001"
SEDE = "30000000-0000-4000-8000-000000000011"
OTRA_SEDE = "30000000-0000-4000-8000-000000000001"
PERFIL = {
    "nombre": "Ana",
    "apellido": "Demo",
    "carrera_id": CARRERA,
    "sede_id": SEDE,
    "nivel": 4,
}


# Copia de lo minimo de test_sesion.py, que tiene sus fixtures en el mismo
# archivo y no en un conftest.py: claves RS256 de prueba y un hash rapido.
@pytest.fixture(autouse=True)
def entorno(settings, tmp_path):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    settings.JWT_CLAVE_PRIVADA = str(tmp_path / "jwt_private.pem")
    settings.JWT_CLAVE_PUBLICA = str(tmp_path / "jwt_public.pem")
    call_command("generar_claves_jwt")
    leer_clave.cache_clear()
    yield
    leer_clave.cache_clear()


def crear_usuario(**perfil):
    return Usuario.objects.create_user(
        "ana.demo@duocuc.cl",
        CLAVE,
        nombre="Ana",
        apellido="Demo",
        email_verificado=True,
        **perfil,
    )


@pytest.fixture
def nuevo(db):
    """Recien registrado: sin carrera, sede ni nivel."""
    return crear_usuario()


@pytest.fixture
def completo(db):
    return crear_usuario(carrera_id=CARRERA, sede_id=SEDE, nivel=4)


def con_sesion(usuario):
    return {"HTTP_AUTHORIZATION": f"Bearer {emitir_acceso(usuario)}"}


def guardar(client, usuario, datos):
    return client.patch(
        f"{BASE}/yo", datos, content_type="application/json", **con_sesion(usuario)
    )


@pytest.mark.django_db
def test_sin_token_no_se_cambia_el_perfil(client, completo):
    sin_token = client.patch(
        f"{BASE}/yo", {"nivel": 5}, content_type="application/json"
    )
    falso = client.patch(
        f"{BASE}/yo",
        {"nivel": 5},
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer abc.def.ghi",
    )

    assert sin_token.status_code == 401
    assert sin_token.json()["codigo"] == "not_authenticated"
    assert falso.status_code == 401
    assert falso.json()["codigo"] == "token_invalido"
    assert Usuario.objects.get().nivel == 4


@pytest.mark.django_db
def test_completa_el_perfil_y_get_yo_lo_devuelve(client, nuevo):
    respuesta = guardar(client, nuevo, {**PERFIL, "nombre": "  Ana María "})

    assert respuesta.status_code == 200
    yo = client.get(f"{BASE}/yo", **con_sesion(nuevo))
    assert yo.json() == {
        "id": str(nuevo.id),
        "email": "ana.demo@duocuc.cl",
        "nombre": "Ana María",
        "apellido": "Demo",
        "carrera_id": CARRERA,
        "nivel": 4,
        "sede_id": SEDE,
        "es_admin": False,
    }
    assert respuesta.json() == yo.json()
    # Carrera y sede quedan como identificadores, sin FK a catalog_db (AD-15).
    guardado = Usuario.objects.get()
    assert (guardado.carrera_id, guardado.sede_id) == (
        uuid.UUID(CARRERA),
        uuid.UUID(SEDE),
    )


@pytest.mark.django_db
def test_con_el_perfil_completo_acepta_cambios_parciales(client, completo):
    respuesta = guardar(client, completo, {"sede_id": OTRA_SEDE, "nivel": 5})

    assert respuesta.status_code == 200
    guardado = Usuario.objects.get()
    assert (guardado.sede_id, guardado.nivel) == (uuid.UUID(OTRA_SEDE), 5)
    assert (guardado.carrera_id, guardado.nombre) == (uuid.UUID(CARRERA), "Ana")


@pytest.mark.django_db
@pytest.mark.parametrize("nivel", [1, 12])
def test_el_nivel_acepta_de_1_a_12(client, completo, nivel):
    assert guardar(client, completo, {"nivel": nivel}).status_code == 200
    assert Usuario.objects.get().nivel == nivel


@pytest.mark.django_db
@pytest.mark.parametrize("nivel", [0, 13, 2.5])
def test_un_nivel_fuera_de_1_a_12_se_rechaza(client, completo, nivel):
    respuesta = guardar(client, completo, {"nivel": nivel})

    assert respuesta.status_code == 400
    assert respuesta.json() == {
        "codigo": "invalid",
        "mensaje": "La petición tiene datos inválidos.",
        "detalles": {"nivel": ["El nivel debe ser un número entero de 1 a 12."]},
    }
    assert Usuario.objects.get().nivel == 4


@pytest.mark.django_db
@pytest.mark.parametrize("campo", ["carrera_id", "sede_id"])
def test_la_carrera_y_la_sede_tienen_que_ser_uuid(client, completo, campo):
    antes = Usuario.objects.values().get()

    respuesta = guardar(client, completo, {campo: "ingenieria-en-informatica"})

    assert respuesta.status_code == 400
    assert list(respuesta.json()["detalles"]) == [campo]
    assert Usuario.objects.values().get() == antes


@pytest.mark.django_db
@pytest.mark.parametrize(
    "campo, valor, mensaje",
    [
        ("carrera_id", None, "Elige tu carrera."),
        ("sede_id", None, "Elige tu sede."),
        ("nivel", None, "Elige tu nivel, de 1 a 12."),
        ("nombre", "   ", "Escribe tu nombre."),
        ("apellido", "", "Escribe tu apellido."),
    ],
)
def test_un_campo_obligatorio_vacio_se_rechaza(client, completo, campo, valor, mensaje):
    antes = Usuario.objects.values().get()

    respuesta = guardar(client, completo, {**PERFIL, "nivel": 5, campo: valor})

    assert respuesta.status_code == 400
    assert respuesta.json()["detalles"] == {campo: [mensaje]}
    assert Usuario.objects.values().get() == antes


@pytest.mark.django_db
def test_un_perfil_incompleto_no_se_guarda_a_medias(client, nuevo):
    antes = Usuario.objects.values().get()

    respuesta = guardar(client, nuevo, {"nivel": 3})

    assert respuesta.status_code == 400
    assert respuesta.json()["detalles"] == {
        "carrera_id": ["Elige tu carrera."],
        "sede_id": ["Elige tu sede."],
    }
    assert Usuario.objects.values().get() == antes


@pytest.mark.django_db
@pytest.mark.parametrize(
    "campo, valor",
    [
        ("email", "otra.persona@duocuc.cl"),
        ("es_admin", True),
        ("activo", False),
        ("email_verificado", False),
    ],
)
def test_no_deja_cambiar_el_correo_ni_los_permisos(client, completo, campo, valor):
    antes = Usuario.objects.values().get()

    # El resto de la peticion es valido, pero no se guarda nada.
    respuesta = guardar(client, completo, {**PERFIL, "nivel": 5, campo: valor})

    assert respuesta.status_code == 400
    assert respuesta.json()["detalles"] == {
        campo: ["Este campo no se puede cambiar desde el perfil."]
    }
    assert Usuario.objects.values().get() == antes
