import os
import re
import uuid
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import pytest
from django.urls import URLPattern, URLResolver, get_resolver

from .models import Asignatura, Carrera, Malla, MallaAsignatura, Sede

ID_CARRERA_CON_MALLA = "20000000-0000-4000-8000-000000000001"
ID_CARRERA_SIN_MALLA = "20000000-0000-4000-8000-000000000002"
ID_CARRERA_INACTIVA = "20000000-0000-4000-8000-000000000003"
ID_CARRERA_INEXISTENTE = "20000000-0000-4000-8000-000000000099"

# El 503 de /estado requiere la base caída y no se provoca en esta suite.
NO_PROBADAS = {
    ("/estado", "GET", 503): "Requiere que la base de datos no responda.",
}

CASOS = [
    ("GET", "/carreras", "/carreras", 200),
    (
        "GET",
        "/carreras/{carrera_id}",
        f"/carreras/{ID_CARRERA_CON_MALLA}",
        200,
    ),
    (
        "GET",
        "/carreras/{carrera_id}",
        f"/carreras/{ID_CARRERA_INEXISTENTE}",
        404,
    ),
    (
        "GET",
        "/carreras/{carrera_id}/asignaturas",
        f"/carreras/{ID_CARRERA_CON_MALLA}/asignaturas",
        200,
    ),
    (
        "GET",
        "/carreras/{carrera_id}/asignaturas",
        f"/carreras/{ID_CARRERA_SIN_MALLA}/asignaturas",
        200,
    ),
    (
        "GET",
        "/carreras/{carrera_id}/asignaturas",
        f"/carreras/{ID_CARRERA_INACTIVA}/asignaturas",
        404,
    ),
    ("GET", "/asignaturas", "/asignaturas", 200),
    ("GET", "/asignaturas", "/asignaturas?buscar=programacion", 200),
    ("GET", "/asignaturas", "/asignaturas?area=Programación", 200),
    ("GET", "/asignaturas", "/asignaturas?paginado=1", 200),
    ("GET", "/areas", "/areas", 200),
    ("GET", "/sedes", "/sedes", 200),
    ("GET", "/estado", "/estado", 200),
]


def _buscar_archivo_contrato() -> Path | None:
    ruta_env = os.environ.get("CONTRATO_CATALOGO")
    if ruta_env:
        candidato = Path(ruta_env)
        return candidato if candidato.is_file() else None

    actual = Path(__file__).resolve().parent
    for carpeta in (actual, *actual.parents):
        candidato = carpeta / "docs" / "api" / "catalog.yaml"
        if candidato.is_file():
            return candidato
    return None


def cargar_contrato() -> dict:
    instrucciones = (
        "Para correr test_contrato.py en el contenedor: "
        "docker compose cp docs/api/catalog.yaml catalog:/tmp/catalog.yaml "
        "y pasa -e CONTRATO_CATALOGO=/tmp/catalog.yaml con PyYAML instalado."
    )
    try:
        import yaml
    except ImportError:
        mensaje = f"Falta PyYAML para leer el contrato OpenAPI. {instrucciones}"
        if os.environ.get("CI"):
            pytest.fail(mensaje)
        pytest.skip(mensaje)

    ruta = _buscar_archivo_contrato()
    if ruta is None:
        mensaje = f"No se encontró docs/api/catalog.yaml. {instrucciones}"
        if os.environ.get("CI"):
            pytest.fail(mensaje)
        pytest.skip(mensaje)

    with ruta.open("r", encoding="utf-8") as archivo:
        return yaml.safe_load(archivo)


def _prefijo_servidor(contrato: dict) -> str:
    url = contrato["servers"][0]["url"]
    return urlparse(url).path.rstrip("/")


def _resolver_ref(contrato: dict, ref: str) -> dict:
    assert ref.startswith("#/"), f"Referencia externa no soportada: {ref}"
    actual = contrato
    for parte in ref[2:].split("/"):
        actual = actual[parte]
    return actual


def validar_esquema(
    valor, esquema: dict, contrato: dict, ubicacion: str = "$"
) -> list[str]:
    if "$ref" in esquema:
        esquema = _resolver_ref(contrato, esquema["$ref"])

    if valor is None:
        if esquema.get("nullable") is True:
            return []
        return [f"{ubicacion}: es null pero el esquema no es nullable"]

    if "oneOf" in esquema:
        aciertos = [
            alternativa
            for alternativa in esquema["oneOf"]
            if not validar_esquema(valor, alternativa, contrato, ubicacion)
        ]
        if len(aciertos) != 1:
            return [
                f"{ubicacion}: calzó con {len(aciertos)} alternativas de oneOf "
                "(se esperaba exactamente 1)"
            ]
        return []

    diferencias: list[str] = []
    tipo = esquema.get("type")

    if tipo == "object":
        if not isinstance(valor, dict):
            return [f"{ubicacion}: se esperaba object y llegó {type(valor).__name__}"]
        requeridos = esquema.get("required", [])
        for campo in requeridos:
            if campo not in valor:
                diferencias.append(f"{ubicacion}: falta el campo requerido '{campo}'")
        propiedades = esquema.get("properties", {})
        adicionales = esquema.get("additionalProperties")
        for clave, subvalor in valor.items():
            sub_ubicacion = f"{ubicacion}.{clave}"
            if clave in propiedades:
                diferencias.extend(
                    validar_esquema(
                        subvalor, propiedades[clave], contrato, sub_ubicacion
                    )
                )
            elif isinstance(adicionales, dict):
                diferencias.extend(
                    validar_esquema(subvalor, adicionales, contrato, sub_ubicacion)
                )
            elif adicionales is not True:
                diferencias.append(f"{sub_ubicacion}: clave no declarada en properties")

    elif tipo == "array":
        if not isinstance(valor, list):
            return [f"{ubicacion}: se esperaba array y llegó {type(valor).__name__}"]
        esquema_item = esquema.get("items", {})
        for indice, elemento in enumerate(valor):
            diferencias.extend(
                validar_esquema(
                    elemento, esquema_item, contrato, f"{ubicacion}[{indice}]"
                )
            )

    elif tipo == "string":
        if not isinstance(valor, str):
            return [f"{ubicacion}: se esperaba string y llegó {type(valor).__name__}"]
        formato = esquema.get("format")
        if formato == "uuid":
            try:
                uuid.UUID(valor)
            except ValueError:
                diferencias.append(f"{ubicacion}: '{valor}' no tiene formato uuid")
        elif formato == "date":
            try:
                date.fromisoformat(valor)
            except ValueError:
                diferencias.append(f"{ubicacion}: '{valor}' no tiene formato date")

    elif tipo == "integer":
        if isinstance(valor, bool) or not isinstance(valor, int):
            return [f"{ubicacion}: se esperaba integer y llegó {type(valor).__name__}"]

    elif tipo == "number":
        if isinstance(valor, bool) or not isinstance(valor, int | float):
            return [f"{ubicacion}: se esperaba number y llegó {type(valor).__name__}"]

    elif tipo == "boolean":
        if not isinstance(valor, bool):
            return [f"{ubicacion}: se esperaba boolean y llegó {type(valor).__name__}"]

    if "enum" in esquema and valor not in esquema["enum"]:
        diferencias.append(f"{ubicacion}: '{valor}' no está en enum {esquema['enum']}")

    return diferencias


@pytest.fixture
def datos_catalogo():
    con_malla = Carrera.objects.create(
        id=uuid.UUID(ID_CARRERA_CON_MALLA),
        codigo="ING-PRU",
        nombre="Ingeniería de Prueba",
        escuela="Escuela de Prueba",
        activa=True,
    )
    Carrera.objects.create(
        id=uuid.UUID(ID_CARRERA_SIN_MALLA),
        codigo="SIN-MALLA",
        nombre="Carrera Sin Malla",
        escuela="Escuela de Prueba",
        activa=True,
    )
    Carrera.objects.create(
        id=uuid.UUID(ID_CARRERA_INACTIVA),
        codigo="INACTIVA",
        nombre="Carrera Desactivada",
        escuela="Escuela de Prueba",
        activa=False,
    )

    antigua = Malla.objects.create(
        carrera=con_malla,
        version="2020",
        vigente_desde=date(2020, 3, 1),
        vigente_hasta=date(2024, 2, 29),
    )
    vigente = Malla.objects.create(
        carrera=con_malla,
        version="2024",
        vigente_desde=date(2024, 3, 1),
        vigente_hasta=None,
    )

    pro = Asignatura.objects.create(
        sigla="PRO1101",
        nombre="Programación de Algoritmos",
        area="Programación",
        creditos=8,
        activa=True,
    )
    bdd = Asignatura.objects.create(
        sigla="BDD1101",
        nombre="Base de Datos",
        area=None,
        creditos=None,
        activa=True,
    )
    web = Asignatura.objects.create(
        sigla="WEB2101",
        nombre="Desarrollo Web",
        area="Desarrollo",
        creditos=6,
        activa=True,
    )
    Asignatura.objects.create(
        sigla="INA9999",
        nombre="Asignatura Inactiva",
        area="Otra",
        creditos=4,
        activa=False,
    )

    MallaAsignatura.objects.create(malla=vigente, asignatura=pro, semestre=1)
    MallaAsignatura.objects.create(malla=vigente, asignatura=bdd, semestre=1)
    MallaAsignatura.objects.create(malla=vigente, asignatura=web, semestre=2)
    MallaAsignatura.objects.create(malla=antigua, asignatura=web, semestre=1)

    Sede.objects.create(
        codigo="SAN-JOAQUIN",
        nombre="San Joaquín",
        region="Metropolitana",
        activa=True,
    )
    Sede.objects.create(
        codigo="ONLINE",
        nombre="Sede Online",
        region=None,
        activa=True,
    )
    Sede.objects.create(
        codigo="CERRADA",
        nombre="Sede Cerrada",
        region="Metropolitana",
        activa=False,
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("metodo", "ruta_contrato", "ruta_pedida", "estado_esperado"),
    CASOS,
)
def test_cada_respuesta_calza_con_el_contrato(
    client, datos_catalogo, metodo, ruta_contrato, ruta_pedida, estado_esperado
):
    contrato = cargar_contrato()
    prefijo = _prefijo_servidor(contrato)

    operacion = contrato["paths"][ruta_contrato][metodo.lower()]
    respuestas = operacion["responses"]
    assert str(estado_esperado) in respuestas

    respuesta = getattr(client, metodo.lower())(f"{prefijo}{ruta_pedida}")
    assert respuesta.status_code == estado_esperado

    esquema = respuestas[str(estado_esperado)]["content"]["application/json"]["schema"]
    diferencias = validar_esquema(respuesta.json(), esquema, contrato)
    assert diferencias == []


def test_cada_respuesta_documentada_tiene_su_caso():
    contrato = cargar_contrato()
    documentadas: set[tuple[str, str, int]] = set()
    for ruta, metodos in contrato["paths"].items():
        for metodo, operacion in metodos.items():
            if not isinstance(operacion, dict) or "responses" not in operacion:
                continue
            for codigo, detalle in operacion["responses"].items():
                if "$ref" in detalle:
                    detalle = _resolver_ref(contrato, detalle["$ref"])
                contenido = detalle.get("content", {})
                if "application/json" in contenido:
                    documentadas.add((ruta, metodo.upper(), int(codigo)))

    probadas = {(ruta, metodo, estado) for metodo, ruta, _, estado in CASOS}
    assert documentadas - set(NO_PROBADAS) == probadas


def _extraer_rutas_django(patrones, prefijo_acumulado: str = "") -> list[str]:
    rutas: list[str] = []
    for p in patrones:
        segmento = str(p.pattern)
        if isinstance(p, URLResolver):
            rutas.extend(
                _extraer_rutas_django(p.url_patterns, prefijo_acumulado + segmento)
            )
        elif isinstance(p, URLPattern):
            rutas.append("/" + (prefijo_acumulado + segmento).lstrip("/"))
    return rutas


def test_las_rutas_publicas_estan_en_el_contrato():
    contrato = cargar_contrato()
    prefijo = _prefijo_servidor(contrato)
    prefijo_con_barra = prefijo + "/"

    rutas_django = _extraer_rutas_django(get_resolver().url_patterns)
    rutas_publicas: set[str] = set()
    for ruta in rutas_django:
        if not ruta.startswith(prefijo_con_barra):
            continue
        relativa = ruta[len(prefijo) :]
        if relativa.startswith("/internal/"):
            continue
        normalizada = re.sub(r"<(?:[^:>]+:)?([^>]+)>", r"{\1}", relativa)
        rutas_publicas.add(normalizada)

    rutas_contrato = set(contrato["paths"].keys())
    assert all(not r.startswith("/internal") for r in rutas_contrato)
    assert rutas_publicas == rutas_contrato


def test_los_ejemplos_calzan_con_su_esquema():
    contrato = cargar_contrato()
    for ruta, metodos in contrato["paths"].items():
        for metodo, operacion in metodos.items():
            if not isinstance(operacion, dict) or "responses" not in operacion:
                continue
            for codigo, detalle in operacion["responses"].items():
                if "$ref" in detalle:
                    detalle = _resolver_ref(contrato, detalle["$ref"])
                json_media = detalle.get("content", {}).get("application/json")
                if not json_media:
                    continue
                esquema = json_media["schema"]
                if "example" in json_media:
                    difs = validar_esquema(
                        json_media["example"],
                        esquema,
                        contrato,
                        f"{metodo.upper()} {ruta} ({codigo}) example",
                    )
                    assert difs == []
                for nombre_ej, obj_ej in json_media.get("examples", {}).items():
                    if "$ref" in obj_ej:
                        obj_ej = _resolver_ref(contrato, obj_ej["$ref"])
                    difs = validar_esquema(
                        obj_ej["value"],
                        esquema,
                        contrato,
                        f"{metodo.upper()} {ruta} ({codigo}) examples.{nombre_ej}",
                    )
                    assert difs == []


@pytest.mark.django_db
def test_la_busqueda_trae_las_cabeceras_documentadas(client, datos_catalogo):
    contrato = cargar_contrato()
    prefijo = _prefijo_servidor(contrato)
    cabeceras_doc = contrato["paths"]["/asignaturas"]["get"]["responses"]["200"][
        "headers"
    ]

    respuesta = client.get(f"{prefijo}/asignaturas")
    assert respuesta.status_code == 200
    for nombre_cabecera in cabeceras_doc:
        assert nombre_cabecera in respuesta.headers
        int(respuesta.headers[nombre_cabecera])
