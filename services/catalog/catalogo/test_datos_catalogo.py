"""Los CSV versionados en datos_catalogo cargan completos (HU-13, criterio 2).

La carga corre sin carpeta, como en la integración continua: lee
services/catalog/datos_catalogo. Las cantidades salen de los mismos CSV, así
que las pruebas siguen sirviendo si se agrega una carrera.
"""

import csv
import io
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

from .models import (
    Asignatura,
    Carrera,
    ImportacionCatalogo,
    ImportacionError,
    Malla,
    MallaAsignatura,
    Sede,
)

CARPETA = Path(settings.BASE_DIR) / "datos_catalogo"
TABLAS = (Sede, Carrera, Malla, Asignatura, MallaAsignatura)


def filas_csv(ruta: Path) -> list[dict[str, str]]:
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo))


def archivos_csv() -> list[str]:
    """Cada archivo que lee la carga, como queda en importacion_catalogo.archivo."""
    mallas = sorted((CARPETA / "mallas").glob("*.csv"))
    return ["sedes.csv", "carreras.csv"] + [f"mallas/{ruta.name}" for ruta in mallas]


def archivos_importados() -> list[str]:
    return sorted(ImportacionCatalogo.objects.values_list("archivo", flat=True))


def cargar() -> None:
    salida = io.StringIO()
    try:
        call_command("cargar_catalogo", stdout=salida)
    except CommandError as error:
        pytest.fail(f"{error}\n{salida.getvalue()}")


def ids_por_tabla() -> dict[str, list]:
    return {
        modelo._meta.db_table: sorted(modelo.objects.values_list("id", flat=True))
        for modelo in TABLAS
    }


@pytest.mark.django_db
def test_los_csv_versionados_cargan_sin_omitir_filas():
    cargar()

    assert archivos_importados() == sorted(archivos_csv())
    con_omitidas = ImportacionCatalogo.objects.filter(filas_omitidas__gt=0)
    assert list(con_omitidas.values_list("archivo", "filas_omitidas")) == []
    assert list(ImportacionError.objects.values_list("fila", "mensaje")) == []


@pytest.mark.django_db
def test_cada_carrera_del_csv_queda_con_su_malla_vigente_completa():
    cargar()

    carreras = filas_csv(CARPETA / "carreras.csv")
    codigos = [fila["codigo"].strip() for fila in carreras]
    assert Carrera.objects.filter(codigo__in=codigos, activa=True).count() >= 3
    for fila in carreras:
        codigo = fila["codigo"].strip()
        malla = Malla.objects.get(carrera__codigo=codigo, vigente_hasta__isnull=True)
        assert malla.version == fila["malla_version"].strip(), codigo
        filas_malla = filas_csv(CARPETA / "mallas" / f"{codigo}.csv")
        vinculos = MallaAsignatura.objects.filter(malla=malla)
        assert vinculos.count() == len(filas_malla), codigo


@pytest.mark.django_db
def test_quedan_las_sedes_de_sedes_csv():
    cargar()

    sedes = filas_csv(CARPETA / "sedes.csv")
    assert sorted(Sede.objects.values_list("codigo", flat=True)) == sorted(
        fila["codigo"].strip() for fila in sedes
    )


@pytest.mark.django_db
def test_cargar_dos_veces_no_cambia_las_tablas_y_suma_importaciones():
    cargar()
    ids_primera_carga = ids_por_tabla()
    assert archivos_importados() == sorted(archivos_csv())

    cargar()

    assert ids_por_tabla() == ids_primera_carga
    assert archivos_importados() == sorted(archivos_csv() * 2)
