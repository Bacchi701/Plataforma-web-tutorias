"""Pruebas de las rutas internas de Identidad (internas.py, Pilar 2 §5.4)."""

import uuid

import pytest

from .models import Usuario

BASE = "/api/identity/v1/internal"
CLAVE_PRUEBA = "clave-de-prueba"
CARRERA_ID = uuid.uuid4()
SEDE_ID = uuid.uuid4()


@pytest.fixture(autouse=True)
def clave_servicio(settings):
    settings.CLAVE_SERVICIO = CLAVE_PRUEBA


@pytest.fixture
def usuario(db):
    return Usuario.objects.create_user(
        "ana.demo@duocuc.cl",
        "clave-segura-1",
        nombre="Ana",
        apellido="Demo",
        carrera_id=CARRERA_ID,
        nivel=4,
        sede_id=SEDE_ID,
        email_verificado=True,
        activo=True,
    )


def test_con_clave_correcta_responde_200_y_los_siete_campos(client, usuario):
    respuesta = client.get(
        f"{BASE}/usuarios/{usuario.id}",
        HTTP_X_CLAVE_SERVICIO=CLAVE_PRUEBA,
    )

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos == {
        "id": str(usuario.id),
        "nombre": "Ana",
        "apellido": "Demo",
        "carrera_id": str(CARRERA_ID),
        "nivel": 4,
        "sede_id": str(SEDE_ID),
        "activo": True,
    }
    assert "email" not in datos
    assert "password" not in datos
    assert "es_admin" not in datos


def test_cuenta_desactivada_responde_200_con_activo_false(client, usuario):
    usuario.activo = False
    usuario.save()

    respuesta = client.get(
        f"{BASE}/usuarios/{usuario.id}",
        HTTP_X_CLAVE_SERVICIO=CLAVE_PRUEBA,
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["activo"] is False


@pytest.mark.parametrize(
    "cabeceras",
    [
        {},
        {"HTTP_X_CLAVE_SERVICIO": "clave-equivocada"},
        {"HTTP_X_CLAVE_SERVICIO": "clave-con-é"},
        {"HTTP_X_CLAVE_SERVICIO": ""},
    ],
    ids=["sin_cabecera", "clave_equivocada", "con_tilde", "cabecera_vacia"],
)
def test_sin_clave_valida_responde_404_ruta_no_encontrada(client, usuario, cabeceras):
    respuesta = client.get(f"{BASE}/usuarios/{usuario.id}", **cabeceras)

    assert respuesta.status_code == 404
    assert respuesta.json()["codigo"] == "ruta_no_encontrada"


def test_con_clave_servicio_vacia_en_settings_responde_404(client, usuario, settings):
    settings.CLAVE_SERVICIO = ""

    respuesta = client.get(
        f"{BASE}/usuarios/{usuario.id}",
        HTTP_X_CLAVE_SERVICIO=CLAVE_PRUEBA,
    )
    assert respuesta.status_code == 404
    assert respuesta.json()["codigo"] == "ruta_no_encontrada"

    respuesta_vacia = client.get(
        f"{BASE}/usuarios/{usuario.id}",
        HTTP_X_CLAVE_SERVICIO="",
    )
    assert respuesta_vacia.status_code == 404
    assert respuesta_vacia.json()["codigo"] == "ruta_no_encontrada"


def test_usuario_que_no_existe_responde_404_usuario_no_encontrado(client, db):
    inexistente = uuid.uuid4()
    respuesta = client.get(
        f"{BASE}/usuarios/{inexistente}",
        HTTP_X_CLAVE_SERVICIO=CLAVE_PRUEBA,
    )

    assert respuesta.status_code == 404
    assert respuesta.json()["codigo"] == "usuario_no_encontrado"


def test_authorization_sin_clave_de_servicio_responde_404(client, usuario):
    respuesta = client.get(
        f"{BASE}/usuarios/{usuario.id}",
        HTTP_AUTHORIZATION="Bearer token-cualquiera",
    )

    assert respuesta.status_code == 404
    assert respuesta.json()["codigo"] == "ruta_no_encontrada"


# ------------------------------------------ GET /internal/usuarios?ids= (HU-19)

VARIOS = f"{BASE}/usuarios"


def otra_cuenta(nombre, **campos):
    """Una cuenta mas. Sin clave: set_password(None) no calcula ningun hash."""
    return Usuario.objects.create_user(
        f"{nombre.lower()}.demo@duocuc.cl",
        None,
        nombre=nombre,
        apellido="Demo",
        **campos,
    )


def pedir_varios(client, ids=None, clave=CLAVE_PRUEBA):
    """GET /internal/usuarios, con ?ids= si se pasa y con la clave si no es None."""
    parametros = {} if ids is None else {"ids": ids}
    cabeceras = {} if clave is None else {"HTTP_X_CLAVE_SERVICIO": clave}
    return client.get(VARIOS, parametros, **cabeceras)


def juntos(*ids):
    return ",".join(str(usuario_id) for usuario_id in ids)


def test_varios_responde_los_siete_campos_ordenados_por_id(client, usuario):
    bea = otra_cuenta("Bea")

    respuesta = pedir_varios(client, juntos(usuario.id, bea.id))

    assert respuesta.status_code == 200
    esperados = {
        str(usuario.id): {
            "id": str(usuario.id),
            "nombre": "Ana",
            "apellido": "Demo",
            "carrera_id": str(CARRERA_ID),
            "nivel": 4,
            "sede_id": str(SEDE_ID),
            "activo": True,
        },
        # Sin perfil completo: carrera, nivel y sede van en null.
        str(bea.id): {
            "id": str(bea.id),
            "nombre": "Bea",
            "apellido": "Demo",
            "carrera_id": None,
            "nivel": None,
            "sede_id": None,
            "activo": True,
        },
    }
    assert respuesta.json() == [esperados[id_] for id_ in sorted(esperados)]
    for datos in respuesta.json():
        assert "email" not in datos
        assert "password" not in datos
        assert "es_admin" not in datos


def test_varios_no_trae_los_ids_que_no_existen(client, usuario):
    respuesta = pedir_varios(client, juntos(uuid.uuid4(), usuario.id, uuid.uuid4()))

    assert respuesta.status_code == 200
    assert [datos["id"] for datos in respuesta.json()] == [str(usuario.id)]


def test_varios_con_ids_que_no_existen_responde_una_lista_vacia(client, db):
    respuesta = pedir_varios(client, juntos(uuid.uuid4(), uuid.uuid4()))

    assert respuesta.status_code == 200
    assert respuesta.json() == []


def test_varios_trae_la_cuenta_desactivada_con_activo_false(client, usuario):
    usuario.activo = False
    usuario.save()

    respuesta = pedir_varios(client, str(usuario.id))

    assert respuesta.status_code == 200
    [datos] = respuesta.json()
    assert datos["activo"] is False


def test_varios_cuenta_una_vez_un_id_repetido_e_ignora_espacios_y_partes_vacias(
    client, usuario
):
    respuesta = pedir_varios(client, f" {usuario.id} ,,{usuario.id},  ,")

    assert respuesta.status_code == 200
    assert [datos["id"] for datos in respuesta.json()] == [str(usuario.id)]


@pytest.mark.parametrize(
    "clave", [None, "clave-equivocada", ""], ids=["sin_clave", "otra_clave", "vacia"]
)
def test_varios_sin_la_clave_responde_404_ruta_no_encontrada(client, usuario, clave):
    respuesta = pedir_varios(client, str(usuario.id), clave=clave)

    assert respuesta.status_code == 404
    assert respuesta.json()["codigo"] == "ruta_no_encontrada"


@pytest.mark.parametrize(
    "ids",
    [None, "", " , ,", "no-es-un-uuid", f"{uuid.uuid4()},12345"],
    ids=["sin_ids", "vacio", "solo_comas", "invalido", "uno_invalido"],
)
def test_varios_sin_ids_validos_responde_400_ids_invalidos(client, db, ids):
    respuesta = pedir_varios(client, ids)

    assert respuesta.status_code == 400
    assert respuesta.json() == {
        "codigo": "ids_invalidos",
        "mensaje": "Indica los usuarios en ?ids=, separados por comas.",
        "detalles": None,
    }


def test_varios_acepta_100_ids_distintos_y_rechaza_101(client, db):
    cien = [uuid.uuid4() for _ in range(100)]

    aceptada = pedir_varios(client, juntos(*cien))
    # 101 partes, pero un id repetido cuenta una vez: siguen siendo 100.
    con_repetido = pedir_varios(client, juntos(*cien, cien[0]))
    rechazada = pedir_varios(client, juntos(*cien, uuid.uuid4()))

    assert (aceptada.status_code, aceptada.json()) == (200, [])
    assert (con_repetido.status_code, con_repetido.json()) == (200, [])
    assert rechazada.status_code == 400
    assert rechazada.json() == {
        "codigo": "demasiados_ids",
        "mensaje": "Pide hasta 100 usuarios por llamada.",
        "detalles": None,
    }


def test_varios_hace_una_sola_consulta(client, usuario, django_assert_num_queries):
    otras = [otra_cuenta(nombre) for nombre in ("Bea", "Cata", "Dani")]
    ids = juntos(usuario.id, *(otra.id for otra in otras))

    with django_assert_num_queries(1):
        respuesta = pedir_varios(client, ids)

    assert respuesta.status_code == 200
    assert len(respuesta.json()) == 4
