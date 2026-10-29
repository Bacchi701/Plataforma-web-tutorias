"""Pruebas de HU-14 (declarar asignaturas con tarifa) y HU-41 (la copia del nombre).

Corren contra PostgreSQL, como test_bloques.py, y firman los tokens con su
propio par RSA. Identidad y Catalogo no estan: OtrosServicios reemplaza
llamadas.abrir y responde como ellos (GET /yo y la malla de la carrera), asi
que cada prueba recorre el camino completo de Tutorias.
"""

import io
import json
import urllib.error
import uuid
from datetime import timedelta
from decimal import Decimal

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.db import IntegrityError
from django.utils import timezone

from . import llamadas
from .autenticacion import leer_clave
from .bloques import Rechazo
from .models import (
    AsignaturaRef,
    BloqueDisponibilidad,
    PerfilTutor,
    Reserva,
    UsuarioRef,
)
from .perfiles import guardar_nuevo

URL = "/api/tutoring/v1/perfiles"
REFRESCAR = "/api/tutoring/v1/yo/refrescar"
DISPONIBILIDAD = "/api/tutoring/v1/disponibilidad"
TUTORES = "/api/tutoring/v1/tutores"
MANANA = (timezone.now() + timedelta(days=1)).replace(
    hour=12, minute=0, second=0, microsecond=0
)

CARRERA = uuid.uuid4()
SEDE = uuid.uuid4()
# La malla vigente de CARRERA: sigla -> (semestre, nombre).
MALLA = {
    "PGY1101": (1, "Programación de Algoritmos"),
    "MAT1101": (1, "Matemática General"),
    "BDY1101": (2, "Base de Datos"),
    "POO1101": (3, "Programación Orientada a Objetos"),
}
ID = {sigla: uuid.uuid4() for sigla in MALLA}


# ------------------------------------------------------------ token de acceso


@pytest.fixture(scope="module")
def clave_de_identidad():
    """Hace de la clave privada de Identidad: firma los tokens de las pruebas."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def clave_publica(clave_de_identidad, settings, tmp_path):
    """Deja la clave publica en tmp_path y Tutorias la lee de ahi."""
    ruta = tmp_path / "jwt_public.pem"
    ruta.write_bytes(
        clave_de_identidad.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    settings.JWT_CLAVE_PUBLICA = str(ruta)
    leer_clave.cache_clear()
    yield ruta
    leer_clave.cache_clear()


@pytest.fixture
def cabecera(clave_de_identidad):
    """Authorization: Bearer con un token de Identidad para ese usuario."""

    def para(usuario_id):
        ahora = timezone.now()
        reclamaciones = {
            "sub": str(usuario_id),
            "es_admin": False,
            "iat": int(ahora.timestamp()),
            "exp": int((ahora + timedelta(minutes=30)).timestamp()),
            "iss": "identity",
        }
        token = jwt.encode(reclamaciones, clave_de_identidad, algorithm="RS256")
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    return para


# ------------------------------------------------------------ Identidad y Catalogo


class Respuesta(io.BytesIO):
    """Lo que entrega llamadas.abrir() con un 2xx."""

    def __init__(self, cuerpo):
        super().__init__(json.dumps(cuerpo).encode())
        self.status = 200


def error_http(codigo, cuerpo):
    texto = json.dumps(cuerpo).encode()
    return urllib.error.HTTPError("http://x", codigo, "error", {}, io.BytesIO(texto))


class OtrosServicios:
    """Responde como Identidad (GET /yo) y como Catalogo (la malla).

    Identidad reconoce al usuario por el sub del token, como cuentas/
    autenticacion.py; aqui no hace falta verificar la firma.
    """

    def __init__(self):
        self.cuentas = {}  # usuario_id -> cuerpo de GET /yo
        self.inactivas = set()
        self.caidos = set()  # "identity" o "catalog"
        self.pedidas = []  # (servicio, Authorization)

    def veces(self, servicio):
        return sum(1 for pedida, _ in self.pedidas if pedida == servicio)

    def abrir(self, peticion):
        servicio = "identity" if "/api/identity/" in peticion.full_url else "catalog"
        self.pedidas.append((servicio, peticion.get_header("Authorization")))
        if servicio in self.caidos:
            raise urllib.error.URLError(ConnectionRefusedError(111, "refused"))
        if servicio == "identity":
            return self.yo(peticion.get_header("Authorization"))
        return self.malla(peticion.full_url)

    def yo(self, autorizacion):
        token = autorizacion.split()[1]
        usuario_id = uuid.UUID(
            jwt.decode(token, options={"verify_signature": False})["sub"]
        )
        if usuario_id in self.inactivas or usuario_id not in self.cuentas:
            raise error_http(
                401,
                {
                    "codigo": "cuenta_inactiva",
                    "mensaje": "La cuenta no existe o está desactivada.",
                    "detalles": None,
                },
            )
        return Respuesta(self.cuentas[usuario_id])

    def malla(self, url):
        carrera_id = uuid.UUID(url.split("/carreras/")[1].split("/")[0])
        if carrera_id != CARRERA:
            raise error_http(
                404,
                {
                    "codigo": "not_found",
                    "mensaje": "No existe una carrera activa con ese identificador.",
                    "detalles": None,
                },
            )
        semestres = {}
        for sigla, (semestre, nombre) in MALLA.items():
            semestres.setdefault(semestre, []).append(
                {"id": str(ID[sigla]), "sigla": sigla, "nombre": nombre}
            )
        return Respuesta(
            {
                "carrera": {"id": str(CARRERA), "nombre": "Ingeniería en Informática"},
                "malla": {"version": "2024", "vigente_desde": "2024-03-01"},
                "semestres": [
                    {"semestre": numero, "asignaturas": asignaturas}
                    for numero, asignaturas in sorted(semestres.items())
                ],
            }
        )


@pytest.fixture
def servicios(monkeypatch):
    falsos = OtrosServicios()
    monkeypatch.setattr(llamadas, "abrir", falsos.abrir)
    return falsos


def cuenta(servicios, nombre="Camila", apellido="Soto", nivel=3, carrera=CARRERA):
    """Una cuenta activa en Identidad, todavia sin copia en Tutorias."""
    usuario_id = uuid.uuid4()
    servicios.cuentas[usuario_id] = {
        "id": str(usuario_id),
        "email": f"{nombre.lower()}.demo@duocuc.cl",
        "nombre": nombre,
        "apellido": apellido,
        "carrera_id": str(carrera) if carrera else None,
        "nivel": nivel,
        "sede_id": str(SEDE),
        "es_admin": False,
    }
    return usuario_id


# ------------------------------------------------------------ peticiones


def declarar(client, encabezado, sigla, tarifa=0, **otros):
    asignatura_id = str(ID[sigla]) if sigla in ID else sigla
    return client.post(
        URL,
        {"asignatura_id": asignatura_id, "tarifa": tarifa, **otros},
        content_type="application/json",
        **encabezado,
    )


def editar(client, encabezado, perfil_id, **cambios):
    return client.patch(
        f"{URL}/{perfil_id}", cambios, content_type="application/json", **encabezado
    )


def listar(client, encabezado, usuario_id):
    respuesta = client.get(f"{URL}?usuario={usuario_id}", **encabezado)
    assert respuesta.status_code == 200
    return [(p["asignatura"]["sigla"], p["activo"]) for p in respuesta.json()]


def error(respuesta):
    return respuesta.status_code, respuesta.json()["codigo"]


# ------------------------------------------------------------ criterio 1


@pytest.mark.django_db
def test_declara_una_asignatura_de_un_semestre_anterior(client, cabecera, servicios):
    camila = cuenta(servicios, nivel=3)

    respuesta = declarar(
        client, cabecera(camila), "BDY1101", 5000, descripcion="  Consultas SQL.  "
    )

    assert respuesta.status_code == 201
    perfil = PerfilTutor.objects.get(usuario_id=camila)
    cuerpo = respuesta.json()
    assert cuerpo == {
        "id": str(perfil.id),
        "asignatura": {
            "asignatura_id": str(ID["BDY1101"]),
            "sigla": "BDY1101",
            "nombre": "Base de Datos",
        },
        "tarifa": 5000,
        "descripcion": "Consultas SQL.",
        "activo": True,
        "creado_en": cuerpo["creado_en"],
    }
    assert cuerpo["creado_en"].endswith("Z")
    assert (perfil.activo, perfil.tarifa) == (True, Decimal("5000"))
    assert listar(client, cabecera(camila), camila) == [("BDY1101", True)]


@pytest.mark.django_db
def test_lo_declarado_aparece_en_la_busqueda_y_en_el_perfil_publico(
    client, cabecera, servicios
):
    camila = cuenta(servicios, nombre="Camila", apellido="Soto")
    declarar(client, cabecera(camila), "PGY1101", 3000)

    busqueda = client.get(f"{TUTORES}?asignatura={ID['PGY1101']}").json()
    publico = client.get(f"{TUTORES}/{camila}").json()

    assert [(t["nombre"], t["tarifa"]) for t in busqueda] == [("Camila", 3000)]
    assert [a["sigla"] for a in publico["asignaturas"]] == ["PGY1101"]


# ------------------------------------------------------------ criterio 2 (RN-01)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "asignatura",
    ["POO1101", str(uuid.uuid4())],
    ids=["de_su_propio_semestre", "que_no_esta_en_su_malla"],
)
def test_rechaza_una_asignatura_que_rn01_no_habilita(
    client, cabecera, servicios, asignatura
):
    camila = cuenta(servicios, nivel=3)

    respuesta = declarar(client, cabecera(camila), asignatura)

    assert error(respuesta) == (400, "asignatura_no_habilitada")
    assert "semestres anteriores al que cursas (3)" in respuesta.json()["mensaje"]
    assert not PerfilTutor.objects.exists()
    assert not AsignaturaRef.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("sigla", ["PGY1101", "BDY1101"])
def test_en_primer_semestre_no_declara_ninguna(client, cabecera, servicios, sigla):
    diego = cuenta(servicios, nombre="Diego", nivel=1)

    respuesta = declarar(client, cabecera(diego), sigla)

    assert error(respuesta) == (400, "asignatura_no_habilitada")
    assert "(1)" in respuesta.json()["mensaje"]
    assert servicios.veces("catalog") == 0


@pytest.mark.django_db
def test_una_carrera_que_no_esta_en_el_catalogo_responde_400(
    client, cabecera, servicios
):
    camila = cuenta(servicios, carrera=uuid.uuid4())

    respuesta = declarar(client, cabecera(camila), "PGY1101")

    assert error(respuesta) == (400, "carrera_no_valida")
    assert not PerfilTutor.objects.exists()


# ------------------------------------------------------------ criterio 3 (RN-05)


@pytest.mark.django_db
def test_una_tarifa_0_queda_como_tutoria_gratuita(client, cabecera, servicios):
    camila = cuenta(servicios)

    respuesta = declarar(client, cabecera(camila), "PGY1101", 0)

    assert respuesta.status_code == 201
    assert respuesta.json()["tarifa"] == 0
    assert PerfilTutor.objects.get().tarifa == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    "tarifa",
    [-1, 1.5, "abc", "5000", True, None, 100_000_000],
    ids=["negativa", "decimal", "texto", "numero_en_texto", "true", "null", "enorme"],
)
def test_rechaza_una_tarifa_que_no_es_un_entero_desde_0_sin_llamar_a_nadie(
    client, cabecera, servicios, tarifa
):
    camila = cuenta(servicios)

    respuesta = declarar(client, cabecera(camila), "PGY1101", tarifa)

    assert error(respuesta) == (400, "tarifa_invalida")
    assert servicios.pedidas == []
    assert not UsuarioRef.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "cuerpo, codigo",
    [
        ({"tarifa": 0}, "asignatura_invalida"),
        ({"asignatura_id": "abc", "tarifa": 0}, "asignatura_invalida"),
        ({"asignatura_id": 7, "tarifa": 0}, "asignatura_invalida"),
        ({"asignatura_id": str(ID["PGY1101"])}, "tarifa_invalida"),
        (
            {
                "asignatura_id": str(ID["PGY1101"]),
                "tarifa": 0,
                "descripcion": "x" * 501,
            },
            "descripcion_invalida",
        ),
        (
            {"asignatura_id": str(ID["PGY1101"]), "tarifa": 0, "descripcion": 5},
            "descripcion_invalida",
        ),
        (
            {"asignatura_id": str(ID["PGY1101"]), "tarifa": 0, "descripcion": "a\x00b"},
            "descripcion_invalida",
        ),
        (
            {"asignatura_id": str(ID["PGY1101"]), "tarifa": 0, "descripcion": "\ud800"},
            "descripcion_invalida",
        ),
    ],
    ids=[
        "sin_asignatura",
        "asignatura_que_no_es_uuid",
        "asignatura_numero",
        "sin_tarifa",
        "descripcion_larga",
        "descripcion_numero",
        "descripcion_con_nulo",
        "descripcion_con_sustituto",
    ],
)
def test_valida_el_cuerpo_antes_de_llamar_a_otros_servicios(
    client, cabecera, servicios, cuerpo, codigo
):
    camila = cuenta(servicios)

    respuesta = client.post(
        URL, cuerpo, content_type="application/json", **cabecera(camila)
    )

    assert error(respuesta) == (400, codigo)
    assert servicios.pedidas == []


@pytest.mark.django_db
def test_una_descripcion_de_500_se_acepta_y_una_en_blanco_queda_en_null(
    client, cabecera, servicios
):
    camila = cuenta(servicios)
    encabezado = cabecera(camila)

    larga = declarar(client, encabezado, "PGY1101", descripcion="x" * 500)
    en_blanco = declarar(client, encabezado, "MAT1101", descripcion="   ")

    assert larga.status_code == 201
    assert len(larga.json()["descripcion"]) == 500
    assert en_blanco.json()["descripcion"] is None


# ------------------------------------------------------------ criterio 4 (AD-07)


@pytest.mark.django_db
def test_el_primer_contacto_crea_las_copias_con_una_llamada_a_cada_servicio(
    client, cabecera, servicios
):
    camila = cuenta(servicios, nombre="Camila", apellido="Soto")
    encabezado = cabecera(camila)
    assert not UsuarioRef.objects.exists()
    assert not AsignaturaRef.objects.exists()

    respuesta = declarar(client, encabezado, "PGY1101")

    assert respuesta.status_code == 201
    copia = UsuarioRef.objects.get(usuario_id=camila)
    assert (copia.nombre, copia.apellido, copia.carrera_id, copia.sede_id) == (
        "Camila",
        "Soto",
        CARRERA,
        SEDE,
    )
    assert copia.activo is True
    asignatura = AsignaturaRef.objects.get(asignatura_id=ID["PGY1101"])
    assert (asignatura.sigla, asignatura.nombre) == (
        "PGY1101",
        "Programación de Algoritmos",
    )
    # A Identidad va el mismo token de la peticion; a Catalogo, ninguno.
    assert servicios.pedidas == [
        ("identity", encabezado["HTTP_AUTHORIZATION"]),
        ("catalog", None),
    ]


@pytest.mark.django_db
def test_cada_contacto_pone_al_dia_la_copia_sin_tocar_la_reputacion(
    client, cabecera, servicios
):
    camila = cuenta(servicios, nombre="Camila", apellido="Soto")
    UsuarioRef.objects.create(
        usuario_id=camila,
        nombre="Cami",
        apellido="S.",
        reputacion_promedio=Decimal("4.50"),
        reputacion_total=2,
    )
    AsignaturaRef.objects.create(
        asignatura_id=ID["PGY1101"], sigla="PGY1101", nombre="Nombre antiguo"
    )

    respuesta = declarar(client, cabecera(camila), "PGY1101")

    assert respuesta.status_code == 201
    copia = UsuarioRef.objects.get(usuario_id=camila)
    assert (copia.nombre, copia.apellido, copia.carrera_id) == (
        "Camila",
        "Soto",
        CARRERA,
    )
    assert (copia.reputacion_promedio, copia.reputacion_total) == (Decimal("4.50"), 2)
    assert AsignaturaRef.objects.get().nombre == "Programación de Algoritmos"


# ------------------------------------------------------------ criterio 5 (A-04)


@pytest.mark.django_db
def test_cambiar_la_tarifa_o_desactivar_no_toca_las_reservas_creadas(
    client, cabecera, servicios
):
    camila = cuenta(servicios)
    encabezado = cabecera(camila)
    perfil_id = declarar(client, encabezado, "BDY1101", 5000).json()["id"]
    tutora = UsuarioRef.objects.get(usuario_id=camila)
    estudiante = UsuarioRef.objects.create(
        usuario_id=uuid.uuid4(), nombre="Diego", apellido="Demo"
    )
    bloque = BloqueDisponibilidad.objects.create(
        usuario=tutora, inicio_en=MANANA, fin_en=MANANA + timedelta(hours=1)
    )
    reserva = Reserva.objects.create(
        bloque=bloque,
        solicitante_usuario=estudiante,
        asignatura=AsignaturaRef.objects.get(asignatura_id=ID["BDY1101"]),
        monto=Decimal("5000"),
    )

    cambio = editar(client, encabezado, perfil_id, tarifa=8000)
    baja = editar(client, encabezado, perfil_id, activo=False)

    assert (cambio.status_code, cambio.json()["tarifa"]) == (200, 8000)
    assert (baja.status_code, baja.json()["activo"]) == (200, False)
    reserva.refresh_from_db()
    assert reserva.monto == Decimal("5000")
    # Cambiar la tarifa y desactivar no llaman a otros servicios.
    assert servicios.veces("identity") == 1
    assert servicios.veces("catalog") == 1


# ------------------------------------------------------------ criterio 6


@pytest.mark.django_db
@pytest.mark.parametrize(
    "faltante", [{"carrera": None}, {"nivel": None}], ids=["sin_carrera", "sin_nivel"]
)
def test_sin_carrera_o_sin_nivel_pide_completar_el_perfil(
    client, cabecera, servicios, faltante
):
    josefa = cuenta(servicios, nombre="Josefa", **faltante)

    respuesta = declarar(client, cabecera(josefa), "PGY1101")

    assert error(respuesta) == (400, "perfil_incompleto")
    assert respuesta.json()["mensaje"] == (
        "Completa tu carrera y tu nivel en Mi perfil antes de declarar asignaturas."
    )
    assert servicios.veces("catalog") == 0
    assert not PerfilTutor.objects.exists()


# ------------------------------------------------------------ repetidas y reactivacion


@pytest.mark.django_db
def test_la_misma_asignatura_activa_dos_veces_responde_409(client, cabecera, servicios):
    camila = cuenta(servicios)
    encabezado = cabecera(camila)

    primera = declarar(client, encabezado, "PGY1101", 0)
    segunda = declarar(client, encabezado, "PGY1101", 2000)

    assert primera.status_code == 201
    assert error(segunda) == (409, "asignatura_ya_declarada")
    assert PerfilTutor.objects.get().tarifa == 0


@pytest.mark.django_db
def test_declarar_otra_vez_una_desactivada_la_reactiva(client, cabecera, servicios):
    camila = cuenta(servicios)
    encabezado = cabecera(camila)
    perfil_id = declarar(client, encabezado, "PGY1101", 3000).json()["id"]
    editar(client, encabezado, perfil_id, activo=False)

    respuesta = declarar(client, encabezado, "PGY1101", 4000, descripcion="Con guías.")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert (cuerpo["id"], cuerpo["activo"]) == (perfil_id, True)
    assert (cuerpo["tarifa"], cuerpo["descripcion"]) == (4000, "Con guías.")
    assert PerfilTutor.objects.count() == 1


@pytest.mark.django_db
def test_si_la_base_rechaza_un_perfil_repetido_responde_409():
    """Dos envios a la vez: el segundo lo rechaza ux_perfil_usuario_asignatura."""
    usuario = UsuarioRef.objects.create(
        usuario_id=uuid.uuid4(), nombre="Camila", apellido="Soto"
    )
    asignatura = AsignaturaRef.objects.create(
        asignatura_id=uuid.uuid4(), sigla="PGY1101", nombre="Programación"
    )
    PerfilTutor.objects.create(usuario=usuario, asignatura=asignatura)

    with pytest.raises(Rechazo) as rechazo:
        guardar_nuevo(PerfilTutor(usuario=usuario, asignatura=asignatura))

    assert rechazo.value.status_code == 409
    assert rechazo.value.detail.code == "asignatura_ya_declarada"


@pytest.mark.django_db
def test_otro_rechazo_de_la_base_no_se_disfraza_de_repetido():
    usuario = UsuarioRef.objects.create(
        usuario_id=uuid.uuid4(), nombre="Camila", apellido="Soto"
    )
    asignatura = AsignaturaRef.objects.create(
        asignatura_id=uuid.uuid4(), sigla="PGY1101", nombre="Programación"
    )

    with pytest.raises(IntegrityError):
        guardar_nuevo(PerfilTutor(usuario=usuario, asignatura=asignatura, tarifa=-1))


# ------------------------------------------------------------ cuenta y servicios caidos


@pytest.mark.django_db
def test_una_cuenta_desactivada_no_declara_y_sale_de_la_busqueda(
    client, cabecera, servicios
):
    josefa = cuenta(servicios, nombre="Josefa")
    encabezado = cabecera(josefa)
    declarar(client, encabezado, "PGY1101")
    servicios.inactivas.add(josefa)

    respuesta = declarar(client, encabezado, "MAT1101")

    assert error(respuesta) == (403, "cuenta_inactiva")
    assert UsuarioRef.objects.get(usuario_id=josefa).activo is False
    assert client.get(f"{TUTORES}/{josefa}").status_code == 404
    assert PerfilTutor.objects.count() == 1


@pytest.mark.django_db
def test_con_identidad_caida_responde_503_sin_escribir_nada(
    client, cabecera, servicios
):
    camila = cuenta(servicios)
    servicios.caidos.add("identity")

    respuesta = declarar(client, cabecera(camila), "PGY1101")

    assert error(respuesta) == (503, "servicio_no_disponible")
    assert "servicio de Identidad" in respuesta.json()["mensaje"]
    assert not UsuarioRef.objects.exists()
    assert not AsignaturaRef.objects.exists()
    assert not PerfilTutor.objects.exists()


@pytest.mark.django_db
def test_con_catalogo_caido_responde_503_sin_asignatura_ni_perfil(
    client, cabecera, servicios
):
    camila = cuenta(servicios)
    servicios.caidos.add("catalog")

    respuesta = declarar(client, cabecera(camila), "PGY1101")

    assert error(respuesta) == (503, "servicio_no_disponible")
    assert "servicio de Catálogo" in respuesta.json()["mensaje"]
    # La copia del usuario puede quedar al dia (T-166); lo demas, no.
    assert UsuarioRef.objects.filter(usuario_id=camila).exists()
    assert not AsignaturaRef.objects.exists()
    assert not PerfilTutor.objects.exists()


@pytest.mark.django_db
def test_si_identidad_responde_por_otro_usuario_no_guarda_nada(
    client, cabecera, servicios
):
    camila = cuenta(servicios)
    servicios.cuentas[camila]["id"] = str(uuid.uuid4())

    respuesta = declarar(client, cabecera(camila), "PGY1101")

    assert error(respuesta) == (503, "servicio_no_disponible")
    assert not UsuarioRef.objects.exists()


@pytest.mark.django_db
def test_sin_token_responde_401(client, servicios):
    respuestas = [
        client.get(f"{URL}?usuario={uuid.uuid4()}"),
        client.post(
            URL,
            {"asignatura_id": str(ID["PGY1101"]), "tarifa": 0},
            content_type="application/json",
        ),
        client.patch(
            f"{URL}/{uuid.uuid4()}", {"tarifa": 1}, content_type="application/json"
        ),
        client.post(REFRESCAR),
    ]

    assert [r.status_code for r in respuestas] == [401, 401, 401, 401]
    assert servicios.pedidas == []


# ------------------------------------------------------------ GET /perfiles


@pytest.mark.django_db
def test_la_lista_propia_trae_todas_y_la_de_otro_solo_las_activas(
    client, cabecera, servicios
):
    camila = cuenta(servicios)
    encabezado = cabecera(camila)
    perfil_id = declarar(client, encabezado, "BDY1101", 5000).json()["id"]
    declarar(client, encabezado, "PGY1101", 0)
    editar(client, encabezado, perfil_id, activo=False)
    pedidas = len(servicios.pedidas)

    propia = listar(client, encabezado, camila)
    de_otro = listar(client, cabecera(uuid.uuid4()), camila)

    assert propia == [("BDY1101", False), ("PGY1101", True)]
    assert de_otro == [("PGY1101", True)]
    assert len(servicios.pedidas) == pedidas


@pytest.mark.django_db
def test_la_lista_de_otro_con_la_cuenta_desactivada_viene_vacia(
    client, cabecera, servicios
):
    camila = cuenta(servicios)
    declarar(client, cabecera(camila), "PGY1101")
    UsuarioRef.objects.filter(usuario_id=camila).update(activo=False)

    assert listar(client, cabecera(uuid.uuid4()), camila) == []
    assert listar(client, cabecera(camila), camila) == [("PGY1101", True)]


@pytest.mark.django_db
@pytest.mark.parametrize("consulta", ["", "?usuario=", "?usuario=abc"])
def test_la_lista_pide_un_usuario_valido(client, cabecera, consulta):
    respuesta = client.get(f"{URL}{consulta}", **cabecera(uuid.uuid4()))

    assert error(respuesta) == (400, "usuario_requerido")


# ------------------------------------------------------------ PATCH /perfiles/<id>


@pytest.mark.django_db
def test_no_se_edita_la_asignatura_de_otro_ni_una_que_no_existe(
    client, cabecera, servicios
):
    camila = cuenta(servicios)
    perfil_id = declarar(client, cabecera(camila), "PGY1101", 3000).json()["id"]
    intruso = cabecera(uuid.uuid4())

    ajena = editar(client, intruso, perfil_id, tarifa=1)
    inexistente = editar(client, cabecera(camila), uuid.uuid4(), tarifa=1)

    assert error(ajena) == (404, "not_found")
    assert error(inexistente) == (404, "not_found")
    assert PerfilTutor.objects.get().tarifa == 3000


@pytest.mark.django_db
@pytest.mark.parametrize(
    "cambios, codigo",
    [
        ({"tarifa": -5}, "tarifa_invalida"),
        ({"tarifa": "8000"}, "tarifa_invalida"),
        ({"tarifa": None}, "tarifa_invalida"),
        ({"activo": "no"}, "activo_invalido"),
        ({"descripcion": "x" * 501}, "descripcion_invalida"),
    ],
    ids=["tarifa_negativa", "tarifa_texto", "tarifa_null", "activo_texto", "larga"],
)
def test_editar_valida_lo_que_cambia(client, cabecera, servicios, cambios, codigo):
    camila = cuenta(servicios)
    encabezado = cabecera(camila)
    perfil_id = declarar(client, encabezado, "PGY1101", 3000).json()["id"]

    respuesta = editar(client, encabezado, perfil_id, **cambios)

    assert error(respuesta) == (400, codigo)
    perfil = PerfilTutor.objects.get()
    assert (perfil.tarifa, perfil.activo, perfil.descripcion) == (3000, True, None)


@pytest.mark.django_db
def test_editar_cambia_o_borra_la_descripcion(client, cabecera, servicios):
    camila = cuenta(servicios)
    encabezado = cabecera(camila)
    perfil_id = declarar(client, encabezado, "PGY1101").json()["id"]

    con_texto = editar(client, encabezado, perfil_id, descripcion="Guías resueltas.")
    en_null = editar(client, encabezado, perfil_id, descripcion=None)

    assert con_texto.json()["descripcion"] == "Guías resueltas."
    assert en_null.json()["descripcion"] is None


@pytest.mark.django_db
def test_reactivar_vuelve_a_validar_rn01(client, cabecera, servicios):
    camila = cuenta(servicios, nivel=3)
    encabezado = cabecera(camila)
    perfil_id = declarar(client, encabezado, "BDY1101", 5000).json()["id"]
    editar(client, encabezado, perfil_id, activo=False)

    # En Identidad, ahora dice que cursa el segundo semestre.
    servicios.cuentas[camila]["nivel"] = 2
    rechazada = editar(client, encabezado, perfil_id, activo=True)
    sigue_inactiva = PerfilTutor.objects.get().activo
    servicios.cuentas[camila]["nivel"] = 3
    aceptada = editar(client, encabezado, perfil_id, activo=True)

    assert error(rechazada) == (400, "asignatura_no_habilitada")
    assert "(2)" in rechazada.json()["mensaje"]
    assert sigue_inactiva is False
    assert (aceptada.status_code, aceptada.json()["activo"]) == (200, True)
    assert servicios.veces("identity") == 3


# ------------------------------------------------------------ de punta a punta (HU-15)


@pytest.mark.django_db
def test_despues_de_declarar_puede_publicar_un_bloque(client, cabecera, servicios):
    camila = cuenta(servicios)
    encabezado = cabecera(camila)
    bloque = {
        "inicio_en": MANANA.isoformat().replace("+00:00", "Z"),
        "fin_en": (MANANA + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    }

    antes = client.post(
        DISPONIBILIDAD, bloque, content_type="application/json", **encabezado
    )
    declarar(client, encabezado, "PGY1101")
    despues = client.post(
        DISPONIBILIDAD, bloque, content_type="application/json", **encabezado
    )

    assert [antes.status_code, despues.status_code] == [403, 201]


# ------------------------------------------------------------ HU-41: POST /yo/refrescar


@pytest.mark.django_db
def test_el_nombre_nuevo_llega_a_la_busqueda_y_al_perfil_publico(
    client, cabecera, servicios
):
    """Criterio 1: el usuario se cambio el nombre en Mi perfil y la pagina refresca."""
    camila = cuenta(servicios, nombre="Camila", apellido="Soto")
    encabezado = cabecera(camila)
    declarar(client, encabezado, "PGY1101")
    servicios.cuentas[camila].update(nombre="Camila Andrea", apellido="Rojas")

    respuesta = client.post(REFRESCAR, **encabezado)

    assert respuesta.status_code == 200
    assert respuesta.json() == {"actualizada": True}
    busqueda = client.get(f"{TUTORES}?asignatura={ID['PGY1101']}").json()
    publico = client.get(f"{TUTORES}/{camila}").json()
    assert [(t["nombre"], t["apellido"]) for t in busqueda] == [
        ("Camila Andrea", "Rojas")
    ]
    assert (publico["nombre"], publico["apellido"]) == ("Camila Andrea", "Rojas")


@pytest.mark.django_db
def test_refrescar_sin_copia_no_la_crea_ni_llama_a_identidad(
    client, cabecera, servicios
):
    """Criterio 2: la copia nace con el primer contacto (M-09)."""
    nueva = cuenta(servicios)

    respuesta = client.post(REFRESCAR, **cabecera(nueva))

    assert respuesta.status_code == 200
    assert respuesta.json() == {"actualizada": False}
    assert not UsuarioRef.objects.exists()
    assert servicios.pedidas == []


@pytest.mark.django_db
def test_refrescar_con_identidad_caida_deja_la_copia_como_estaba(
    client, cabecera, servicios
):
    """Criterio 3, del lado de Tutorias: si Identidad no responde, nada cambia."""
    camila = cuenta(servicios, nombre="Camila Andrea")
    UsuarioRef.objects.create(usuario_id=camila, nombre="Camila", apellido="Soto")
    servicios.caidos.add("identity")

    respuesta = client.post(REFRESCAR, **cabecera(camila))

    assert error(respuesta) == (503, "servicio_no_disponible")
    assert UsuarioRef.objects.get().nombre == "Camila"


@pytest.mark.django_db
def test_refrescar_una_cuenta_desactivada_la_saca_de_la_busqueda(
    client, cabecera, servicios
):
    camila = cuenta(servicios)
    encabezado = cabecera(camila)
    declarar(client, encabezado, "PGY1101")
    servicios.inactivas.add(camila)

    respuesta = client.post(REFRESCAR, **encabezado)

    assert error(respuesta) == (403, "cuenta_inactiva")
    assert client.get(f"{TUTORES}/{camila}").status_code == 404
