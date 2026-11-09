"""RNF-02: la busqueda de tutores responde en menos de 2 segundos con 500
usuarios de prueba (HU-34, criterio 2).

Necesita los datos de ejemplo y, despues, la carga de 500 usuarios de
scripts/cargar_usuarios_prueba.ps1 (o .sh): 300 tutores con dos asignaturas
cada uno. Mide por el gateway las tres formas de GET /api/tutoring/v1/tutores
(services/tutoring/tutorias/busqueda.py), que salen de tutoring_db sin llamar
a otro servicio:
- por asignatura: todos los tutores de MAT1101, la que mas tiene en la carga
  (201), sin tope;
- sin parametros: los 24 mejor evaluados (MAXIMO_DESTACADOS);
- por nombre: ?buscar= con el primer apellido de la carga, hasta 48.

Cada busqueda se pide 2 veces de calentamiento, que no cuentan, y 20 veces que
se miden. La tabla de tiempos que imprime va a la evidencia del portafolio.
"""

import statistics
import urllib.parse

import pytest

TUTORES = "/api/tutoring/v1/tutores"
USUARIOS = "/api/identity/v1/admin/usuarios"
# La asignatura con mas tutores de la carga: 201 de los 300.
MAT1101 = "40000000-0000-4000-8000-000000000001"
MINIMO_DE_TUTORES = 200
# El primer apellido de las listas de data/seeds/carga: lo llevan 20 tutores.
APELLIDO = "González"
CARGA_PENDIENTE = (
    "Carga primero los 500 usuarios de prueba: scripts/cargar_usuarios_prueba.ps1"
)
CUENTAS_DE_LA_CARGA = 500
ADMIN = "admin.demo@duocuc.cl"
CLAVE = "Tutorias2026"

CALENTAMIENTO = 2
MEDICIONES = 20
# RNF-02, en segundos.
LIMITE = 2

BUSQUEDAS = [
    ("Por asignatura (MAT1101)", f"{TUTORES}?asignatura={MAT1101}"),
    ("Sin parámetros (destacados)", TUTORES),
    (
        f"Por nombre (?buscar={APELLIDO})",
        f"{TUTORES}?" + urllib.parse.urlencode({"buscar": APELLIDO}),
    ),
]


def medir(cliente, ruta):
    """Los segundos de cada medicion y cuantos tutores trajo la ultima.

    Antes van las peticiones de calentamiento, que no se cuentan. Cada
    respuesta tiene que ser un 200.
    """
    tiempos = []
    for numero in range(CALENTAMIENTO + MEDICIONES):
        estado, tutores, segundos = cliente.pedir("GET", ruta)
        assert estado == 200, f"GET {ruta} respondió {estado}: {tutores}"
        if numero >= CALENTAMIENTO:
            tiempos.append(segundos)
    return tiempos, len(tutores)


def percentil_95(tiempos):
    """Con interpolacion lineal, como PERCENTIL.INC de Excel."""
    return statistics.quantiles(tiempos, n=20, method="inclusive")[-1]


def en_ms(segundos):
    """Milisegundos con un decimal y coma decimal: 0.0453 -> "45,3"."""
    return f"{segundos * 1000:.1f}".replace(".", ",")


def tabla(url_gateway, filas):
    """La tabla de tiempos: una linea por busqueda."""
    lineas = [
        "",
        f"RNF-02: búsqueda de tutores por el gateway ({url_gateway})",
        f"{MEDICIONES} mediciones de cada búsqueda, después de {CALENTAMIENTO} "
        "de calentamiento. Tiempos en milisegundos.",
        "",
        f"{'Búsqueda':<32}{'Tutores':>8}{'Mediana':>10}"
        f"{'Percentil 95':>14}{'Máximo':>10}",
    ]
    for nombre, tutores, tiempos in filas:
        lineas.append(
            f"{nombre:<32}{tutores:>8}{en_ms(statistics.median(tiempos)):>10}"
            f"{en_ms(percentil_95(tiempos)):>14}{en_ms(max(tiempos)):>10}"
        )
    lineas.append("")
    lineas.append(f"Límite de RNF-02: {LIMITE} segundos para cada petición.")
    return "\n".join(lineas)


def test_busqueda_de_tutores_bajo_dos_segundos(cliente):
    """Las tres busquedas responden 200 y su maximo queda bajo 2 segundos."""
    por_asignatura = BUSQUEDAS[0][1]
    estado, tutores, _ = cliente.pedir("GET", por_asignatura)
    if estado != 200 or not isinstance(tutores, list):
        pytest.fail(f"GET {por_asignatura} respondió {estado}: {tutores}")
    if len(tutores) < MINIMO_DE_TUTORES:
        pytest.fail(
            f"{CARGA_PENDIENTE} (por MAT1101 la búsqueda trae {len(tutores)}, y "
            f"con la carga trae {MINIMO_DE_TUTORES} o más)."
        )

    filas = []
    for nombre, ruta in BUSQUEDAS:
        tiempos, cantidad = medir(cliente, ruta)
        filas.append((nombre, cantidad, tiempos))
    print(tabla(cliente.url_base, filas))

    lentas = [nombre for nombre, _, tiempos in filas if max(tiempos) >= LIMITE]
    assert not lentas, f"No cumplen RNF-02 (menos de {LIMITE} segundos): {lentas}"


def test_cuentas_de_la_carga(cliente):
    """Con la sesion del administrador, Identidad tiene 500 cuentas o mas.

    Es el unico inicio de sesion de este archivo: el gateway deja cinco por
    minuto. Usa la lista de cuentas de HU-31; si develop todavia no la trae,
    la prueba se salta.
    """
    estado, sesion, _ = cliente.pedir(
        "POST", "/api/identity/v1/login", {"email": ADMIN, "password": CLAVE}
    )
    assert estado == 200, (
        f"POST /api/identity/v1/login con {ADMIN} respondió {estado}: {sesion}. "
        "Si es 503, es el límite del gateway (cinco por minuto): espera un "
        "minuto y vuelve a correr la prueba."
    )

    ruta = f"{USUARIOS}?limite=1"
    estado, cuentas, _ = cliente.pedir("GET", ruta, token=sesion["token_acceso"])
    if estado == 404:
        pytest.skip(f"HU-31 todavía no está en develop: GET {USUARIOS} responde 404")
    assert estado == 200, f"GET {ruta} respondió {estado}: {cuentas}"

    total = cuentas["total"]
    print(
        f"\nCuentas en Identidad: {total} "
        f"(la carga de prueba suma {CUENTAS_DE_LA_CARGA})."
    )
    assert total >= CUENTAS_DE_LA_CARGA, CARGA_PENDIENTE
