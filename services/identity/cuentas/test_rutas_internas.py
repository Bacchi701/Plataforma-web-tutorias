"""Las rutas internas de Identidad, con y sin la clave (HU-17, criterio 2).

Del lado de Identidad: las tres rutas que llama Tutorias, internal/usuarios/<id>
(F1), internal/usuarios?ids= (HU-19) e internal/avisos (HU-16), responden solo
con la clave de servicio. Cada una ya tiene sus pruebas en test_internas.py y
test_avisos.py; estas recorren cuentas/urls.py y prueban igual todas las rutas
internal/, tambien las que se agreguen despues: una ruta interna nueva sin
ClaveDeServicio falla aqui sin escribir nada mas.

La clave se fija con el fixture settings, nunca desde el entorno: en la
integracion continua CLAVE_SERVICIO no existe.
"""

import re
import uuid

import pytest
from django.core.management import call_command

from .internas import ClaveDeServicio
from .models import Usuario
from .tokens import emitir_acceso, leer_clave
from .urls import urlpatterns

BASE = "/api/identity/v1/"
CLAVE_PRUEBA = "clave-de-prueba"
RUTA_NO_ENCONTRADA = {
    "codigo": "ruta_no_encontrada",
    "mensaje": "Ruta no encontrada.",
    "detalles": None,
}
# Cada ruta interna, tal como la declara cuentas/urls.py, con su vista.
VISTAS = {
    str(patron.pattern): patron.callback
    for patron in urlpatterns
    if str(patron.pattern).startswith("internal/")
}
RUTAS = list(VISTAS)


@pytest.fixture(autouse=True)
def clave_servicio(settings):
    settings.CLAVE_SERVICIO = CLAVE_PRUEBA


def metodo_de(ruta):
    """El primer metodo que acepta la vista de esa ruta, sin OPTIONS."""
    metodos = VISTAS[ruta].cls.http_method_names
    return sorted(metodo for metodo in metodos if metodo != "options")[0]


def pedir(client, ruta, **cabeceras):
    """Pide la ruta con su primer metodo y un uuid nuevo en cada <uuid:...>.

    internal/usuarios va con ?ids= y un uuid nuevo. Un metodo con cuerpo manda
    un objeto JSON vacio.
    """
    url = BASE + re.sub(r"<uuid:\w+>", lambda _: str(uuid.uuid4()), ruta)
    metodo = metodo_de(ruta)
    if metodo == "get":
        parametros = {"ids": str(uuid.uuid4())} if ruta == "internal/usuarios" else {}
        return client.get(url, parametros, **cabeceras)
    pedido = getattr(client, metodo)
    return pedido(url, {}, content_type="application/json", **cabeceras)


def test_estan_las_tres_rutas_internas_de_f1_hu19_y_hu16():
    assert {
        "internal/usuarios/<uuid:usuario_id>",
        "internal/usuarios",
        "internal/avisos",
    } <= set(RUTAS)


@pytest.mark.parametrize("ruta", RUTAS)
def test_la_vista_no_lee_el_token_y_pide_la_clave_de_servicio(ruta):
    vista = VISTAS[ruta].cls

    assert vista.authentication_classes == []
    assert ClaveDeServicio in vista.permission_classes


# (cabeceras de la peticion, CLAVE_SERVICIO en settings)
SIN_LA_CLAVE = {
    "sin_la_cabecera": ({}, CLAVE_PRUEBA),
    "con_otra_clave": ({"HTTP_X_CLAVE_SERVICIO": "otra-clave"}, CLAVE_PRUEBA),
    "clave_servicio_vacia": ({"HTTP_X_CLAVE_SERVICIO": CLAVE_PRUEBA}, ""),
}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "cabeceras, en_settings", list(SIN_LA_CLAVE.values()), ids=list(SIN_LA_CLAVE)
)
@pytest.mark.parametrize("ruta", RUTAS)
def test_sin_la_clave_la_ruta_responde_404(
    client, settings, ruta, cabeceras, en_settings
):
    settings.CLAVE_SERVICIO = en_settings

    respuesta = pedir(client, ruta, **cabeceras)

    assert respuesta.status_code == 404
    assert respuesta.json() == RUTA_NO_ENCONTRADA


@pytest.fixture
def token_de_administrador(settings, tmp_path, db):
    """Un token de acceso de verdad, de una cuenta con es_admin.

    Las claves RS256 de prueba van en tmp_path, como en test_perfil.py.
    """
    settings.JWT_CLAVE_PRIVADA = str(tmp_path / "jwt_private.pem")
    settings.JWT_CLAVE_PUBLICA = str(tmp_path / "jwt_public.pem")
    call_command("generar_claves_jwt")
    leer_clave.cache_clear()
    admin = Usuario.objects.create_user(
        "admin.demo@duocuc.cl",
        None,
        nombre="Admin",
        apellido="Demo",
        email_verificado=True,
        es_admin=True,
    )
    yield emitir_acceso(admin)
    leer_clave.cache_clear()


@pytest.mark.django_db
@pytest.mark.parametrize("ruta", RUTAS)
def test_con_el_token_de_un_administrador_y_sin_la_clave_responde_404(
    client, token_de_administrador, ruta
):
    respuesta = pedir(
        client, ruta, HTTP_AUTHORIZATION=f"Bearer {token_de_administrador}"
    )

    assert respuesta.status_code == 404
    assert respuesta.json() == RUTA_NO_ENCONTRADA


@pytest.mark.django_db
@pytest.mark.parametrize("ruta", RUTAS)
def test_con_la_clave_la_ruta_ya_no_se_esconde(client, ruta):
    respuesta = pedir(client, ruta, HTTP_X_CLAVE_SERVICIO=CLAVE_PRUEBA)

    # 200, 400 o 404 usuario_no_encontrado, segun la ruta: lo que no puede
    # responder es ruta_no_encontrada.
    cuerpo = respuesta.json()
    assert respuesta.status_code < 500
    codigo = cuerpo.get("codigo") if isinstance(cuerpo, dict) else None
    assert codigo != "ruta_no_encontrada"
    if ruta == "internal/usuarios":
        assert (respuesta.status_code, cuerpo) == (200, [])
