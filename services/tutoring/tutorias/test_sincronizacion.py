"""Pruebas de HU-19: el comando sincronizar_copias (tutorias/sincronizacion.py).

Corren contra PostgreSQL. Identidad y Catalogo no estan: ServiciosFalsos
reemplaza llamadas.abrir y responde como ellos, con lo que registra cada
prueba. Los datos de Tutorias se crean directo en la base, con su
actualizado_en en fechas pasadas distintas, y el comando se corre con
call_command, sin argumentos, como lo corre el programador (HU-37).
"""

import io
import json
import urllib.error
import urllib.parse
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from . import llamadas, sincronizacion
from .models import (
    AsignaturaRef,
    BloqueDisponibilidad,
    EjecucionTarea,
    EstadoBloque,
    EstadoReserva,
    Modalidad,
    PerfilTutor,
    Reserva,
    UsuarioRef,
)

CLAVE = "clave-de-prueba"
TUTORES = "/api/tutoring/v1/tutores"
RUTA_USUARIOS = "/api/identity/v1/internal/usuarios"
RUTA_ASIGNATURAS = "/api/catalog/v1/asignaturas"
CARRERA = uuid.uuid4()
OTRA_CARRERA = uuid.uuid4()
SEDE = uuid.uuid4()
OTRA_SEDE = uuid.uuid4()
# Los bloques de las reservas son de manana a mediodia (UTC).
MANANA = (timezone.now() + timedelta(days=1)).replace(
    hour=12, minute=0, second=0, microsecond=0
)


# ------------------------------------------------------------ Identidad y Catalogo


class Respuesta(io.BytesIO):
    """Lo que entrega llamadas.abrir() con un 2xx."""

    def __init__(self, cuerpo):
        super().__init__(json.dumps(cuerpo).encode())
        self.status = 200


def error_http(codigo, cuerpo):
    texto = json.dumps(cuerpo).encode()
    return urllib.error.HTTPError("http://x", codigo, "error", {}, io.BytesIO(texto))


def caido():
    return urllib.error.URLError(ConnectionRefusedError(111, "refused"))


class ServiciosFalsos:
    """Responde como Identidad y como Catalogo, con lo que registra la prueba.

    - Identidad, GET /internal/usuarios?ids=: las cuentas registradas que
      vienen en ids. Sin la clave de settings responde 404, como
      ClaveDeServicio. Anota la clave y los ids de cada llamada.
    - Catalogo, GET /asignaturas?paginado=1: las asignaturas registradas,
      por sigla y en paginas de ?limite=, como buscar_asignaturas.
    - Catalogo, GET /carreras/<id>/asignaturas: la malla de la carrera, o 404
      not_found si no esta registrada. Anota la carrera de cada llamada.
    - caer_desde = {"identity": n} hace que Identidad falle (URLError) desde
      su llamada n; con 1, desde la primera. Lo mismo con "catalog". Una
      carrera en mallas_caidas hace fallar solo su malla.
    """

    def __init__(self, settings):
        self.settings = settings
        self.cuentas = {}  # usuario_id -> el usuario, como lo da Identidad
        self.catalogo = {}  # asignatura_id -> (sigla, nombre)
        self.mallas = {}  # carrera_id -> {semestre: [asignatura_id, ...]}
        self.caer_desde = {}
        self.mallas_caidas = set()
        self.llamadas = {"identity": 0, "catalog": 0}
        self.claves = []
        self.ids_pedidos = []
        self.mallas_pedidas = []

    def cuenta(self, usuario, **cambios):
        """Registra su cuenta: igual a la copia y con nivel 5, salvo los cambios."""
        cuerpo = {
            "id": usuario.usuario_id,
            "nombre": usuario.nombre,
            "apellido": usuario.apellido,
            "carrera_id": usuario.carrera_id,
            "nivel": 5,
            "sede_id": usuario.sede_id,
            "activo": usuario.activo,
            **cambios,
        }
        # Como JSON: los identificadores van como texto.
        self.cuentas[usuario.usuario_id] = {
            campo: str(valor) if isinstance(valor, uuid.UUID) else valor
            for campo, valor in cuerpo.items()
        }

    def en_catalogo(self, copia, sigla=None, nombre=None):
        """Registra la asignatura de esa copia: igual a ella, salvo lo que cambie."""
        self.catalogo[copia.asignatura_id] = (
            sigla or copia.sigla,
            nombre or copia.nombre,
        )

    def abrir(self, peticion):
        partes = urllib.parse.urlsplit(peticion.full_url)
        consulta = urllib.parse.parse_qs(partes.query)
        servicio = "identity" if partes.path == RUTA_USUARIOS else "catalog"
        if servicio == "identity":
            self.claves.append(peticion.get_header("X-clave-servicio"))
            ids = consulta["ids"][0].split(",")
            self.ids_pedidos.append([uuid.UUID(texto) for texto in ids])
        elif partes.path != RUTA_ASIGNATURAS:
            carrera = partes.path.split("/carreras/")[1].split("/")[0]
            self.mallas_pedidas.append(uuid.UUID(carrera))
        self.llamadas[servicio] += 1
        desde = self.caer_desde.get(servicio)
        if desde is not None and self.llamadas[servicio] >= desde:
            raise caido()
        if servicio == "identity":
            return self.identidad(peticion)
        if partes.path == RUTA_ASIGNATURAS:
            return self.listar_asignaturas(consulta)
        return self.malla(self.mallas_pedidas[-1])

    def identidad(self, peticion):
        clave = peticion.get_header("X-clave-servicio")
        if not clave or clave != self.settings.CLAVE_SERVICIO:
            raise error_http(
                404,
                {
                    "codigo": "ruta_no_encontrada",
                    "mensaje": "Ruta no encontrada.",
                    "detalles": None,
                },
            )
        pedidos = set(self.ids_pedidos[-1])
        return Respuesta(
            [self.cuentas[i] for i in sorted(pedidos) if i in self.cuentas]
        )

    def asignatura_json(self, asignatura_id):
        sigla, nombre = self.catalogo.get(asignatura_id, ("SIG0000", "Asignatura"))
        return {
            "id": str(asignatura_id),
            "sigla": sigla,
            "nombre": nombre,
            "area": "",
            "creditos": 6,
        }

    def listar_asignaturas(self, consulta):
        limite = int(consulta["limite"][0])
        numero = int(consulta["pagina"][0])
        por_sigla = sorted(self.catalogo, key=lambda clave: self.catalogo[clave][0])
        todas = [self.asignatura_json(asignatura_id) for asignatura_id in por_sigla]
        resultados = todas[(numero - 1) * limite : numero * limite]
        if consulta.get("paginado") != ["1"]:
            return Respuesta(resultados)
        return Respuesta(
            {
                "total": len(todas),
                "pagina": numero,
                "total_paginas": max(1, (len(todas) + limite - 1) // limite),
                "limite": limite,
                "resultados": resultados,
            }
        )

    def malla(self, carrera_id):
        if carrera_id in self.mallas_caidas:
            raise caido()
        if carrera_id not in self.mallas:
            raise error_http(
                404,
                {
                    "codigo": "not_found",
                    "mensaje": "No existe una carrera activa con ese identificador.",
                    "detalles": None,
                },
            )
        semestres = [
            {
                "semestre": semestre,
                "asignaturas": [self.asignatura_json(a) for a in asignaturas],
            }
            for semestre, asignaturas in sorted(self.mallas[carrera_id].items())
        ]
        return Respuesta(
            {
                "carrera": {"id": str(carrera_id), "nombre": "Carrera de prueba"},
                "malla": {"version": "2024", "vigente_desde": "2024-03-01"},
                "semestres": semestres,
            }
        )


@pytest.fixture
def servicios(monkeypatch, settings):
    settings.URL_IDENTIDAD = "http://identity:8000"
    settings.URL_CATALOGO = "http://catalog:8000"
    settings.CLAVE_SERVICIO = CLAVE
    falsos = ServiciosFalsos(settings)
    monkeypatch.setattr(llamadas, "abrir", falsos.abrir)
    return falsos


# ------------------------------------------------------------ datos de Tutorias


def hace(dias):
    return timezone.now() - timedelta(days=dias)


def copia_de_usuario(nombre, dias=1, **campos):
    """Una fila de usuario_ref, refrescada por ultima vez hace tantos dias."""
    datos = {"carrera_id": CARRERA, "sede_id": SEDE, **campos}
    return UsuarioRef.objects.create(
        usuario_id=uuid.uuid4(),
        nombre=nombre,
        apellido="Demo",
        actualizado_en=hace(dias),
        **datos,
    )


def copia_de_asignatura(sigla, nombre, dias=1):
    """Una fila de asignatura_ref, refrescada por ultima vez hace tantos dias."""
    return AsignaturaRef.objects.create(
        asignatura_id=uuid.uuid4(),
        sigla=sigla,
        nombre=nombre,
        actualizado_en=hace(dias),
    )


def perfil_de(usuario, asignatura, activo=True):
    return PerfilTutor.objects.create(
        usuario=usuario, asignatura=asignatura, tarifa=0, activo=activo
    )


def malla_de_prueba(servicios):
    """La malla de CARRERA: una asignatura de primer semestre y otra de tercero."""
    primero = copia_de_asignatura("PGY1101", "Programación de Algoritmos")
    tercero = copia_de_asignatura("POO1101", "Programación Orientada a Objetos")
    servicios.en_catalogo(primero)
    servicios.en_catalogo(tercero)
    servicios.mallas[CARRERA] = {
        1: [primero.asignatura_id],
        3: [tercero.asignatura_id],
    }
    return primero, tercero


def reservas_sobre(tutor, estudiante, asignatura):
    """Una solicitud SOLICITADA y una reserva CONFIRMADA sobre esa asignatura.

    Cada una en su bloque, sin solaparse (ex_bloque_sin_solape); la confirmada
    con modalidad, lugar y confirmada_en (ck_reserva_confirmada_completa). El
    estudiante no es el tutor (trg_reserva_no_auto).
    """
    libre = BloqueDisponibilidad.objects.create(
        usuario=tutor, inicio_en=MANANA, fin_en=MANANA + timedelta(hours=1)
    )
    ocupado = BloqueDisponibilidad.objects.create(
        usuario=tutor,
        inicio_en=MANANA + timedelta(hours=2),
        fin_en=MANANA + timedelta(hours=3),
        estado=EstadoBloque.OCUPADO,
    )
    Reserva.objects.create(
        bloque=libre, solicitante_usuario=estudiante, asignatura=asignatura
    )
    Reserva.objects.create(
        bloque=ocupado,
        solicitante_usuario=estudiante,
        asignatura=asignatura,
        estado=EstadoReserva.CONFIRMADA,
        modalidad=Modalidad.EN_LINEA,
        lugar_o_enlace="https://meet.example.com/prueba",
        confirmada_en=timezone.now(),
    )


# ------------------------------------------------------------ el comando


def correr():
    """call_command sin argumentos (criterio 5). Devuelve lo que escribio."""
    salida = io.StringIO()
    call_command("sincronizar_copias", stdout=salida)
    return salida.getvalue()


def correr_con_error():
    """Corre el comando, que termina con CommandError. Devuelve (salida, error)."""
    salida = io.StringIO()
    with pytest.raises(CommandError) as error:
        call_command("sincronizar_copias", stdout=salida)
    return salida.getvalue(), str(error.value)


def ultima_fila():
    return EjecucionTarea.objects.order_by("-id").first()


def activos(*perfiles):
    return [PerfilTutor.objects.get(pk=perfil.pk).activo for perfil in perfiles]


def nombres_en_la_busqueda(client, asignatura):
    respuesta = client.get(TUTORES, {"asignatura": str(asignatura.asignatura_id)})
    assert respuesta.status_code == 200
    return [tutor["nombre"] for tutor in respuesta.json()]


# ------------------------------------------------------------ criterio 1


@pytest.mark.django_db
def test_sin_copias_no_llama_a_nadie_y_deja_su_fila(servicios):
    salida = correr()

    assert salida == (
        "sincronizar_copias: 0 copias sincronizadas, 0 perfiles desactivados.\n"
    )
    assert servicios.llamadas == {"identity": 0, "catalog": 0}
    fila = ultima_fila()
    assert (fila.comando, fila.refs_sincronizadas, fila.error) == (
        "sincronizar_copias",
        0,
        None,
    )
    assert fila.terminada_en is not None


@pytest.mark.django_db
def test_c1_las_copias_quedan_como_dicen_identidad_y_catalogo(servicios):
    camila = copia_de_usuario(
        "Cami", dias=3, carrera_id=OTRA_CARRERA, sede_id=OTRA_SEDE
    )
    servicios.cuenta(
        camila, nombre="Camila", apellido="Rojas", carrera_id=CARRERA, sede_id=SEDE
    )
    bdd = copia_de_asignatura("BDD0000", "Base de datos antigua", dias=3)
    servicios.en_catalogo(bdd, sigla="BDY1101", nombre="Base de Datos")
    antes = timezone.now()

    salida = correr()

    camila.refresh_from_db()
    assert (camila.nombre, camila.apellido, camila.carrera_id, camila.sede_id) == (
        "Camila",
        "Rojas",
        CARRERA,
        SEDE,
    )
    assert camila.activo is True
    assert camila.actualizado_en >= antes
    bdd.refresh_from_db()
    assert (bdd.sigla, bdd.nombre) == ("BDY1101", "Base de Datos")
    assert bdd.actualizado_en >= antes
    assert salida == (
        "sincronizar_copias: 2 copias sincronizadas, 0 perfiles desactivados.\n"
    )


@pytest.mark.django_db
def test_c1_por_lotes_primero_las_copias_mas_antiguas(servicios, monkeypatch):
    monkeypatch.setattr(sincronizacion, "TAMANO_LOTE", 2)
    # Cinco usuarios, creados en otro orden que el de su ultimo refresco.
    por_dias = {
        dias: copia_de_usuario(f"U{dias}", dias=dias) for dias in (3, 9, 1, 7, 5)
    }
    for usuario in por_dias.values():
        servicios.cuenta(usuario)

    correr()

    def ids(*dias):
        return {por_dias[cuantos].usuario_id for cuantos in dias}

    assert [set(pedidos) for pedidos in servicios.ids_pedidos] == [
        ids(9, 7),
        ids(5, 3),
        ids(1),
    ]


@pytest.mark.django_db
def test_c1_si_identidad_cae_en_el_segundo_lote_no_pide_los_siguientes(
    servicios, monkeypatch
):
    monkeypatch.setattr(sincronizacion, "TAMANO_LOTE", 2)
    por_dias = {
        dias: copia_de_usuario(f"U{dias}", dias=dias) for dias in (5, 4, 3, 2, 1)
    }
    for dias, usuario in por_dias.items():
        servicios.cuenta(usuario, nombre=f"Nuevo {dias}")
    servicios.caer_desde["identity"] = 2

    correr_con_error()

    assert len(servicios.ids_pedidos) == 2
    filas = {
        dias: UsuarioRef.objects.get(pk=usuario.pk)
        for dias, usuario in por_dias.items()
    }
    assert {dias: fila.nombre for dias, fila in filas.items()} == {
        5: "Nuevo 5",
        4: "Nuevo 4",
        3: "U3",
        2: "U2",
        1: "U1",
    }
    # Siguen siendo las mas antiguas: la proxima ejecucion empieza por ellas.
    for dias in (3, 2, 1):
        assert filas[dias].actualizado_en == por_dias[dias].actualizado_en


@pytest.mark.django_db
def test_c1_las_asignaturas_se_leen_de_todas_las_paginas(servicios):
    # 200 asignaturas que Tutorias no copia llenan la primera pagina; las dos
    # copias, con siglas que van al final, quedan en la segunda.
    for numero in range(200):
        servicios.catalogo[uuid.uuid4()] = (f"AAA{numero:04d}", f"Otra {numero}")
    copias = [copia_de_asignatura(f"ZZZ110{numero}", "Antigua") for numero in (1, 2)]
    servicios.en_catalogo(copias[0], nombre="Nueva 1")
    servicios.en_catalogo(copias[1], nombre="Nueva 2")

    salida = correr()

    assert [AsignaturaRef.objects.get(pk=copia.pk).nombre for copia in copias] == [
        "Nueva 1",
        "Nueva 2",
    ]
    assert servicios.llamadas["catalog"] == 2
    assert salida.startswith("sincronizar_copias: 2 copias sincronizadas")


@pytest.mark.django_db
def test_c1_una_asignatura_que_catalogo_no_trae_no_cambia(servicios):
    retirada = copia_de_asignatura("ANT1101", "Asignatura retirada", dias=4)

    salida = correr()

    fila = AsignaturaRef.objects.get(pk=retirada.pk)
    assert (fila.sigla, fila.nombre) == ("ANT1101", "Asignatura retirada")
    assert fila.actualizado_en == retirada.actualizado_en
    assert salida.startswith("sincronizar_copias: 0 copias sincronizadas")


@pytest.mark.django_db
def test_identidad_recibe_la_clave_de_servicio_en_cada_lote(servicios, monkeypatch):
    monkeypatch.setattr(sincronizacion, "TAMANO_LOTE", 1)
    for nombre in ("Uno", "Dos"):
        servicios.cuenta(copia_de_usuario(nombre))

    correr()

    assert servicios.claves == [CLAVE, CLAVE]


# ------------------------------------------------------------ criterio 2 (RN-08)


@pytest.mark.django_db
def test_c2_una_cuenta_desactivada_sale_de_la_busqueda_y_vuelve_al_activarla(
    client, servicios
):
    bdd = copia_de_asignatura("BDY1101", "Base de Datos")
    servicios.en_catalogo(bdd)
    servicios.mallas[CARRERA] = {1: [bdd.asignatura_id]}
    valentina = copia_de_usuario("Valentina")
    perfil = perfil_de(valentina, bdd)
    servicios.cuenta(valentina, nivel=4)
    assert nombres_en_la_busqueda(client, bdd) == ["Valentina"]

    servicios.cuentas[valentina.usuario_id]["activo"] = False
    correr()

    assert UsuarioRef.objects.get(pk=valentina.pk).activo is False
    assert nombres_en_la_busqueda(client, bdd) == []
    # Su perfil sigue activo: la busqueda la deja fuera por usuario_ref.activo.
    assert activos(perfil) == [True]

    servicios.cuentas[valentina.usuario_id]["activo"] = True
    correr()

    assert UsuarioRef.objects.get(pk=valentina.pk).activo is True
    assert nombres_en_la_busqueda(client, bdd) == ["Valentina"]


@pytest.mark.django_db
def test_c2_un_usuario_que_identidad_no_devuelve_queda_desactivado(servicios):
    sin_cuenta = copia_de_usuario("Tomás", dias=2)
    antes = timezone.now()

    correr()

    fila = UsuarioRef.objects.get(pk=sin_cuenta.pk)
    assert fila.activo is False
    assert fila.actualizado_en >= antes
    # Lo demas de la copia queda como estaba.
    assert (fila.nombre, fila.carrera_id, fila.sede_id) == ("Tomás", CARRERA, SEDE)


# ------------------------------------------------------------ criterio 3 (RN-01)


@pytest.mark.django_db
def test_c3_al_bajar_de_nivel_solo_se_desactiva_el_perfil_que_deja_de_cumplir(
    servicios,
):
    primero, tercero = malla_de_prueba(servicios)
    tutor = copia_de_usuario("Matías")
    del_primero, del_tercero = perfil_de(tutor, primero), perfil_de(tutor, tercero)
    estudiante = copia_de_usuario("Diego")
    servicios.cuenta(estudiante, nivel=2)
    reservas_sobre(tutor, estudiante, tercero)
    servicios.cuenta(tutor, nivel=5)
    correr()
    assert activos(del_primero, del_tercero) == [True, True]
    reservas = list(Reserva.objects.order_by("id").values())
    bloques = list(BloqueDisponibilidad.objects.order_by("id").values())
    antes = timezone.now()

    # Ahora cursa el tercer semestre: cumple con la del 1 y ya no con la del 3.
    servicios.cuentas[tutor.usuario_id]["nivel"] = 3
    salida = correr()

    assert activos(del_primero, del_tercero) == [True, False]
    assert PerfilTutor.objects.get(pk=del_tercero.pk).actualizado_en >= antes
    assert salida.endswith(", 1 perfil desactivado.\n")
    assert ultima_fila().perfiles_desactivados == 1
    # La solicitud y la reserva sobre esa asignatura no cambian.
    assert list(Reserva.objects.order_by("id").values()) == reservas
    assert list(BloqueDisponibilidad.objects.order_by("id").values()) == bloques


@pytest.mark.django_db
def test_c3_si_cambia_a_una_carrera_sin_la_asignatura_su_perfil_se_desactiva(
    servicios,
):
    primero, _ = malla_de_prueba(servicios)
    administracion = copia_de_asignatura("ADM1101", "Fundamentos de Administración")
    servicios.en_catalogo(administracion)
    servicios.mallas[OTRA_CARRERA] = {1: [administracion.asignatura_id]}
    tutora = copia_de_usuario("Fernanda")
    perfil = perfil_de(tutora, primero)
    servicios.cuenta(tutora, carrera_id=OTRA_CARRERA)

    correr()

    assert activos(perfil) == [False]
    assert UsuarioRef.objects.get(pk=tutora.pk).carrera_id == OTRA_CARRERA
    assert servicios.mallas_pedidas == [OTRA_CARRERA]


@pytest.mark.django_db
def test_c3_si_catalogo_no_tiene_su_carrera_sus_perfiles_se_desactivan(servicios):
    primero, tercero = malla_de_prueba(servicios)
    tutora = copia_de_usuario("Josefa", carrera_id=OTRA_CARRERA)
    perfiles = [perfil_de(tutora, primero), perfil_de(tutora, tercero)]
    servicios.cuenta(tutora)

    salida = correr()

    assert activos(*perfiles) == [False, False]
    assert salida.endswith(", 2 perfiles desactivados.\n")
    # Catalogo respondio (404 not_found): no es un error de la ejecucion.
    assert ultima_fila().error is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "faltante",
    [{"nivel": None}, {"carrera_id": None}],
    ids=["sin_nivel", "sin_carrera"],
)
def test_c3_si_identidad_no_trae_su_nivel_o_su_carrera_se_desactivan(
    servicios, faltante
):
    primero, _ = malla_de_prueba(servicios)
    tutora = copia_de_usuario("Camila")
    perfil = perfil_de(tutora, primero)
    servicios.cuenta(tutora, **faltante)

    correr()

    assert activos(perfil) == [False]


@pytest.mark.django_db
def test_c3_si_catalogo_no_responde_ningun_perfil_cambia_y_queda_el_error(
    servicios,
):
    primero, tercero = malla_de_prueba(servicios)
    tutor = copia_de_usuario("Matías")
    perfiles = [perfil_de(tutor, primero), perfil_de(tutor, tercero)]
    # En primer semestre no cumpliria con ninguna, pero Catalogo cae despues
    # de su primera llamada, la lista de asignaturas: la malla no responde.
    servicios.cuenta(tutor, nivel=1)
    servicios.caer_desde["catalog"] = 2

    salida, error = correr_con_error()

    assert activos(*perfiles) == [True, True]
    assert error.startswith("perfiles: ServicioNoDisponible: ")
    assert "Catálogo" in error
    assert ultima_fila().error == error
    assert salida == (
        "sincronizar_copias: 3 copias sincronizadas, 0 perfiles desactivados.\n"
    )


@pytest.mark.django_db
def test_c3_si_catalogo_no_responde_por_una_carrera_las_demas_siguen(servicios):
    primero, _ = malla_de_prueba(servicios)
    servicios.mallas[OTRA_CARRERA] = {1: [primero.asignatura_id]}
    servicios.mallas_caidas.add(OTRA_CARRERA)
    uno = copia_de_usuario("Uno")
    otro = copia_de_usuario("Otro", carrera_id=OTRA_CARRERA)
    del_uno, del_otro = perfil_de(uno, primero), perfil_de(otro, primero)
    # Los dos pasan a primer semestre: ninguno cumpliria RN-01.
    servicios.cuenta(uno, nivel=1)
    servicios.cuenta(otro, nivel=1)

    _, error = correr_con_error()

    assert activos(del_uno, del_otro) == [False, True]
    assert error.startswith("perfiles: ServicioNoDisponible: ")
    assert set(servicios.mallas_pedidas) == {CARRERA, OTRA_CARRERA}


@pytest.mark.django_db
def test_c3_un_perfil_ya_desactivado_no_se_cuenta_ni_se_reactiva(servicios):
    primero, tercero = malla_de_prueba(servicios)
    tutora = copia_de_usuario("Valentina")
    desactivado = perfil_de(tutora, primero, activo=False)
    tambien = perfil_de(tutora, tercero, activo=False)
    antes = PerfilTutor.objects.get(pk=desactivado.pk).actualizado_en
    # Con nivel 5 cumple RN-01 en las dos, pero no se reactivan solas.
    servicios.cuenta(tutora, nivel=5)

    salida = correr()

    assert activos(desactivado, tambien) == [False, False]
    assert PerfilTutor.objects.get(pk=desactivado.pk).actualizado_en == antes
    assert salida.endswith(", 0 perfiles desactivados.\n")


@pytest.mark.django_db
def test_c3_la_malla_de_cada_carrera_se_pide_una_vez_por_ejecucion(servicios):
    primero, tercero = malla_de_prueba(servicios)
    for nombre in ("Uno", "Dos", "Tres"):
        tutor = copia_de_usuario(nombre)
        perfil_de(tutor, primero)
        perfil_de(tutor, tercero)
        servicios.cuenta(tutor)

    correr()

    assert servicios.mallas_pedidas == [CARRERA]
    assert PerfilTutor.objects.filter(activo=False).count() == 0


# ------------------------------------------------------------ criterio 4 (A-09)


@pytest.mark.django_db
def test_c4_cada_ejecucion_deja_su_fila_con_lo_que_hizo(servicios):
    primero, tercero = malla_de_prueba(servicios)
    tutor = copia_de_usuario("Matías")
    perfil_de(tutor, primero)
    perfil_de(tutor, tercero)
    servicios.cuenta(tutor, nivel=3)
    servicios.cuenta(copia_de_usuario("Diego"))

    correr()
    correr()

    filas = list(EjecucionTarea.objects.order_by("id"))
    assert [fila.comando for fila in filas] == ["sincronizar_copias"] * 2
    # Dos usuarios y dos asignaturas en cada una; el perfil, solo la primera.
    assert [(f.refs_sincronizadas, f.perfiles_desactivados) for f in filas] == [
        (4, 1),
        (4, 0),
    ]
    for fila in filas:
        assert fila.error is None
        assert fila.terminada_en is not None
        assert fila.terminada_en >= fila.iniciada_en
        # Las columnas de cerrar_y_expirar (HU-29) quedan en 0.
        assert (fila.solicitudes_expiradas, fila.reservas_cerradas) == (0, 0)


@pytest.mark.django_db
def test_c4_con_identidad_caida_termina_con_error_y_sincroniza_las_asignaturas(
    servicios,
):
    cami = copia_de_usuario("Cami", dias=2)
    servicios.cuenta(cami, nombre="Camila")
    bdd = copia_de_asignatura("BDD0000", "Base de datos antigua")
    servicios.en_catalogo(bdd, sigla="BDY1101", nombre="Base de Datos")
    servicios.caer_desde["identity"] = 1

    salida, error = correr_con_error()

    fila = ultima_fila()
    assert fila.error.startswith("usuarios: ServicioNoDisponible: ")
    assert "servicio de Identidad" in fila.error
    assert fila.error == error
    assert fila.terminada_en is not None
    # El paso de asignaturas igual se hizo; la copia del usuario quedo igual.
    assert AsignaturaRef.objects.get(pk=bdd.pk).nombre == "Base de Datos"
    assert UsuarioRef.objects.get(pk=cami.pk).nombre == "Cami"
    assert fila.refs_sincronizadas == 1
    assert salida == (
        "sincronizar_copias: 1 copia sincronizada, 0 perfiles desactivados.\n"
    )


@pytest.mark.django_db
def test_c4_otra_falla_tambien_queda_anotada_y_sigue_el_paso_siguiente(
    servicios, monkeypatch
):
    def falla(ids):
        raise RuntimeError("falla de prueba")

    monkeypatch.setattr(sincronizacion, "usuarios_por_ids", falla)
    copia_de_usuario("Camila")
    bdd = copia_de_asignatura("BDD0000", "Base de datos antigua")
    servicios.en_catalogo(bdd, nombre="Base de Datos")

    _, error = correr_con_error()

    assert error == "usuarios: RuntimeError: falla de prueba"
    fila = ultima_fila()
    assert fila.error == "usuarios: RuntimeError: falla de prueba"
    assert fila.terminada_en is not None
    assert AsignaturaRef.objects.get(pk=bdd.pk).nombre == "Base de Datos"


@pytest.mark.django_db
def test_c4_un_error_de_mas_de_300_caracteres_queda_cortado(servicios, monkeypatch):
    def falla(ids):
        raise RuntimeError("x" * 400)

    monkeypatch.setattr(sincronizacion, "usuarios_por_ids", falla)
    copia_de_usuario("Camila")

    _, error = correr_con_error()

    completo = "usuarios: RuntimeError: " + "x" * 400
    assert error == completo
    assert ultima_fila().error == completo[:300]


@pytest.mark.django_db
def test_la_reputacion_no_cambia(servicios):
    tutora = copia_de_usuario(
        "Vale", dias=2, reputacion_promedio=Decimal("4.50"), reputacion_total=2
    )
    servicios.cuenta(tutora, nombre="Valentina")

    with CaptureQueriesContext(connection) as consultas:
        correr()

    fila = UsuarioRef.objects.get(pk=tutora.pk)
    assert fila.nombre == "Valentina"
    assert (fila.reputacion_promedio, fila.reputacion_total) == (Decimal("4.50"), 2)
    # Ninguna escritura toca las columnas de la reputacion.
    escrituras = [
        consulta["sql"]
        for consulta in consultas.captured_queries
        if consulta["sql"].startswith("UPDATE")
    ]
    assert any('"usuario_ref"' in sql for sql in escrituras)
    assert not any("reputacion" in sql for sql in escrituras)


# ------------------------------------------------------------ criterio 5 (R-18)


@pytest.mark.django_db
def test_c5_una_segunda_ejecucion_sin_cambios_no_desactiva_nada_mas(servicios):
    primero, tercero = malla_de_prueba(servicios)
    tutor = copia_de_usuario("Matías")
    perfil_de(tutor, primero)
    perfil_de(tutor, tercero)
    servicios.cuenta(tutor, nivel=3)

    primera = correr()
    segunda = correr()

    assert primera == (
        "sincronizar_copias: 3 copias sincronizadas, 1 perfil desactivado.\n"
    )
    assert segunda == (
        "sincronizar_copias: 3 copias sincronizadas, 0 perfiles desactivados.\n"
    )
    assert PerfilTutor.objects.filter(activo=True).count() == 1
