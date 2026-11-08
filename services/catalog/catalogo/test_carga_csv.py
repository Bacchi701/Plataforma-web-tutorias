import io
import uuid
from datetime import date
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

from .management.commands.cargar_catalogo import ESPACIO
from .models import (
    Asignatura,
    Carrera,
    ImportacionCatalogo,
    ImportacionError,
    Malla,
    MallaAsignatura,
    Sede,
    TipoImportacion,
)

BASE = "/api/catalog/v1"


def escribir_csv(ruta: Path, lineas: list[str], encoding: str = "utf-8") -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("\n".join(lineas) + "\n", encoding=encoding)


def correr_carga(carpeta: Path | str | None = None) -> str:
    salida = io.StringIO()
    if carpeta is None:
        call_command("cargar_catalogo", stdout=salida)
    else:
        call_command("cargar_catalogo", str(carpeta), stdout=salida)
    return salida.getvalue()


@pytest.fixture
def carpeta_valida(tmp_path: Path) -> Path:
    escribir_csv(
        tmp_path / "sedes.csv",
        [
            "codigo,nombre,region,activa",
            "SAN-JOAQUIN,San Joaquín,Metropolitana,true",
            "VALPARAISO,Valparaíso,Valparaíso,true",
        ],
    )
    escribir_csv(
        tmp_path / "carreras.csv",
        [
            "codigo,nombre,escuela,activa,malla_version,vigente_desde",
            "ING-PRU,Ingeniería de Prueba,Escuela de Prueba,true,2026,2026-03-01",
        ],
    )
    escribir_csv(
        tmp_path / "mallas" / "ING-PRU.csv",
        [
            "semestre,sigla,nombre,creditos,area",
            "1,MAT1110,Matemática Aplicada,6,Matemáticas",
            "1,PRO1101,Programación de Algoritmos,8,Programación",
            "2,BDD2101,Base de Datos,6,Datos",
        ],
    )
    return tmp_path


@pytest.mark.django_db
def test_criterio_2_carga_sedes_carrera_y_malla_vigente_por_semestre(
    client, carpeta_valida
):
    correr_carga(carpeta_valida)

    assert Sede.objects.count() == 2
    carrera = Carrera.objects.get(codigo="ING-PRU")
    malla = Malla.objects.get(carrera=carrera)
    assert malla.version == "2026"
    assert malla.vigente_desde == date(2026, 3, 1)
    assert malla.vigente_hasta is None
    assert MallaAsignatura.objects.filter(malla=malla).count() == 3

    respuesta = client.get(f"{BASE}/carreras/{carrera.id}/asignaturas")
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["malla"]["version"] == "2026"
    assert [s["semestre"] for s in cuerpo["semestres"]] == [1, 2]
    assert [a["sigla"] for a in cuerpo["semestres"][0]["asignaturas"]] == [
        "MAT1110",
        "PRO1101",
    ]
    assert [a["sigla"] for a in cuerpo["semestres"][1]["asignaturas"]] == ["BDD2101"]

    importaciones = list(ImportacionCatalogo.objects.order_by("id"))
    assert [
        (i.archivo, i.tipo, i.filas_leidas, i.filas_creadas, i.filas_omitidas)
        for i in importaciones
    ] == [
        ("sedes.csv", TipoImportacion.SEDES, 2, 2, 0),
        ("carreras.csv", TipoImportacion.CARRERAS, 1, 1, 0),
        ("mallas/ING-PRU.csv", TipoImportacion.MALLA, 3, 3, 0),
    ]
    assert ImportacionError.objects.count() == 0


@pytest.mark.django_db
def test_criterio_3_omite_fila_con_semestre_13_y_registra_error(tmp_path):
    escribir_csv(
        tmp_path / "carreras.csv",
        [
            "codigo,nombre,escuela,activa,malla_version,vigente_desde",
            "ING-PRU,Ingeniería de Prueba,Escuela de Prueba,true,2026,2026-03-01",
        ],
    )
    escribir_csv(
        tmp_path / "mallas" / "ING-PRU.csv",
        [
            "semestre,sigla,nombre,creditos,area",
            "1,PRU1101,Asignatura válida,6,Área",
            "13,PRU9901,Asignatura inválida,4,Área",
        ],
    )

    correr_carga(tmp_path)

    imp_malla = ImportacionCatalogo.objects.get(tipo=TipoImportacion.MALLA)
    assert imp_malla.filas_leidas == 2
    assert imp_malla.filas_creadas == 1
    assert imp_malla.filas_omitidas == 1

    error = ImportacionError.objects.get(importacion=imp_malla)
    assert error.fila == 3
    assert "semestre" in error.mensaje.lower()
    assert "13" in error.mensaje
    assert MallaAsignatura.objects.count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("fila_invalida_malla", "texto_esperado"),
    [
        ("abc,PRU9901,Nombre,4,Area", "semestre"),
        ("1,,Nombre sin sigla,4,Area", "sigla"),
        ("1,SIGLADEMASIADOLARGA16,Nombre,4,Area", "sigla"),
        ("1,PRU9901,Nombre,31,Area", "créditos"),
        ("1,PRU1101,Sigla repetida,4,Area", "fila 2"),
    ],
)
def test_criterio_3_parametriza_motivos_invalidos_en_malla(
    tmp_path, fila_invalida_malla, texto_esperado
):
    escribir_csv(
        tmp_path / "carreras.csv",
        [
            "codigo,nombre,escuela,activa,malla_version,vigente_desde",
            "ING-PRU,Ingeniería de Prueba,Escuela de Prueba,true,2026,2026-03-01",
        ],
    )
    escribir_csv(
        tmp_path / "mallas" / "ING-PRU.csv",
        [
            "semestre,sigla,nombre,creditos,area",
            "1,PRU1101,Asignatura base,6,Area",
            fila_invalida_malla,
        ],
    )

    correr_carga(tmp_path)

    imp = ImportacionCatalogo.objects.get(tipo=TipoImportacion.MALLA)
    assert imp.filas_leidas == 2
    assert imp.filas_creadas == 1
    assert imp.filas_omitidas == 1
    error = ImportacionError.objects.get(importacion=imp)
    assert error.fila == 3
    assert texto_esperado in error.mensaje.lower()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("fila_invalida_carrera", "texto_esperado"),
    [
        ("CAR-INV,Carrera,Escuela,si,2026,2026-03-01,", "activa"),
        ("CAR-INV,Carrera,Escuela,true,2026,01-03-2024,", "vigente_desde"),
        ("CAR-INV,Carrera,Escuela,true,2026,2026-03-01,no-es-un-uuid", "uuid"),
    ],
)
def test_criterio_3_parametriza_motivos_invalidos_en_carreras(
    tmp_path, fila_invalida_carrera, texto_esperado
):
    escribir_csv(
        tmp_path / "carreras.csv",
        [
            "codigo,nombre,escuela,activa,malla_version,vigente_desde,id",
            "CAR-OK,Carrera Válida,Escuela,true,2026,2026-03-01,",
            fila_invalida_carrera,
        ],
    )

    correr_carga(tmp_path)

    imp = ImportacionCatalogo.objects.get(tipo=TipoImportacion.CARRERAS)
    assert imp.filas_leidas == 2
    assert imp.filas_creadas == 1
    assert imp.filas_omitidas == 1
    error = ImportacionError.objects.get(importacion=imp)
    assert error.fila == 3
    assert texto_esperado in error.mensaje.lower()


@pytest.mark.django_db
def test_carpeta_csv_de_prueba_carga_carrera_y_omite_fila_5():
    carpeta = Path(settings.BASE_DIR) / "catalogo" / "csv_de_prueba"
    correr_carga(carpeta)

    carrera = Carrera.objects.get(codigo="PRUEBA-CSV")
    malla = Malla.objects.get(carrera=carrera, vigente_hasta__isnull=True)
    vinculos = list(
        MallaAsignatura.objects.filter(malla=malla)
        .select_related("asignatura")
        .order_by("semestre", "asignatura__sigla")
    )
    assert [(v.semestre, v.asignatura.sigla) for v in vinculos] == [
        (1, "PRU1101"),
        (1, "PRU1102"),
        (2, "PRU2101"),
    ]

    imp_malla = ImportacionCatalogo.objects.get(tipo=TipoImportacion.MALLA)
    assert imp_malla.filas_leidas == 4
    assert imp_malla.filas_creadas == 3
    assert imp_malla.filas_omitidas == 1
    error = ImportacionError.objects.get(importacion=imp_malla)
    assert error.fila == 5


@pytest.mark.django_db
def test_sin_argumento_lee_datos_catalogo_y_carga_11_sedes():
    correr_carga()

    assert Sede.objects.count() == 11
    san_joaquin = Sede.objects.get(codigo="SAN-JOAQUIN")
    assert san_joaquin.id == uuid.UUID("30000000-0000-4000-8000-000000000011")

    imp_sedes = ImportacionCatalogo.objects.get(
        archivo="sedes.csv", tipo=TipoImportacion.SEDES
    )
    assert imp_sedes.filas_leidas == 11
    assert imp_sedes.filas_creadas == 11
    assert imp_sedes.filas_omitidas == 0


@pytest.mark.django_db
def test_repetir_la_carga_es_idempotente_y_conserva_ids(carpeta_valida):
    correr_carga(carpeta_valida)

    ids_sedes = set(Sede.objects.values_list("id", flat=True))
    ids_carreras = set(Carrera.objects.values_list("id", flat=True))
    ids_mallas = set(Malla.objects.values_list("id", flat=True))
    ids_asignaturas = set(Asignatura.objects.values_list("id", flat=True))
    ids_vinculos = set(MallaAsignatura.objects.values_list("id", flat=True))

    salida_segunda = correr_carga(carpeta_valida)

    assert set(Sede.objects.values_list("id", flat=True)) == ids_sedes
    assert set(Carrera.objects.values_list("id", flat=True)) == ids_carreras
    assert set(Malla.objects.values_list("id", flat=True)) == ids_mallas
    assert set(Asignatura.objects.values_list("id", flat=True)) == ids_asignaturas
    assert set(MallaAsignatura.objects.values_list("id", flat=True)) == ids_vinculos

    assert "0 creadas" in salida_segunda
    assert ImportacionCatalogo.objects.count() == 6
    ultimas_tres = list(ImportacionCatalogo.objects.order_by("id")[3:])
    assert all(i.filas_creadas == 0 for i in ultimas_tres)


@pytest.mark.django_db
def test_nueva_version_de_malla_cierra_la_anterior_y_valida_fechas(tmp_path):
    escribir_csv(
        tmp_path / "carreras.csv",
        [
            "codigo,nombre,escuela,activa,malla_version,vigente_desde",
            "ING-PRU,Ingeniería de Prueba,Escuela,true,2024,2024-03-01",
        ],
    )
    escribir_csv(
        tmp_path / "mallas" / "ING-PRU.csv",
        [
            "semestre,sigla,nombre,creditos,area",
            "1,MAT1110,Matemática,6,Matemáticas",
            "1,PRO1101,Programación,8,Programación",
        ],
    )
    correr_carga(tmp_path)

    escribir_csv(
        tmp_path / "carreras.csv",
        [
            "codigo,nombre,escuela,activa,malla_version,vigente_desde",
            "ING-PRU,Ingeniería de Prueba,Escuela,true,2026,2026-03-01",
        ],
    )
    escribir_csv(
        tmp_path / "mallas" / "ING-PRU.csv",
        [
            "semestre,sigla,nombre,creditos,area",
            "1,MAT1110,Matemática,6,Matemáticas",
        ],
    )
    correr_carga(tmp_path)

    malla_2024 = Malla.objects.get(version="2024")
    malla_2026 = Malla.objects.get(version="2026")
    assert malla_2024.vigente_hasta == date(2026, 2, 28)
    assert MallaAsignatura.objects.filter(malla=malla_2024).count() == 2
    assert malla_2026.vigente_hasta is None
    assert MallaAsignatura.objects.filter(malla=malla_2026).count() == 1

    for fecha_invalida in ("2026-02-15", "2026-03-01", "2026-03-02"):
        escribir_csv(
            tmp_path / "carreras.csv",
            [
                "codigo,nombre,escuela,activa,malla_version,vigente_desde",
                f"ING-PRU,Ingeniería de Prueba,Escuela,true,2027,{fecha_invalida}",
            ],
        )
        with pytest.raises(CommandError):
            correr_carga(tmp_path)

        assert not Malla.objects.filter(version="2027").exists()
        vigente = Malla.objects.get(vigente_hasta__isnull=True)
        assert vigente.version == "2026"
        ultima_imp = ImportacionCatalogo.objects.filter(
            tipo=TipoImportacion.MALLA
        ).latest("id")
        assert ultima_imp.filas_creadas == 0
        assert ultima_imp.filas_omitidas == 1
        err = ImportacionError.objects.get(importacion=ultima_imp)
        assert err.fila == 1


@pytest.mark.django_db
def test_misma_version_con_una_fila_menos_quita_de_malla_pero_conserva_asignatura(
    tmp_path,
):
    escribir_csv(
        tmp_path / "carreras.csv",
        [
            "codigo,nombre,escuela,activa,malla_version,vigente_desde",
            "ING-PRU,Ingeniería de Prueba,Escuela,true,2026,2026-03-01",
        ],
    )
    escribir_csv(
        tmp_path / "mallas" / "ING-PRU.csv",
        [
            "semestre,sigla,nombre,creditos,area",
            "1,MAT1110,Matemática,6,Matemáticas",
            "1,PRO1101,Programación,8,Programación",
        ],
    )
    correr_carga(tmp_path)

    escribir_csv(
        tmp_path / "mallas" / "ING-PRU.csv",
        [
            "semestre,sigla,nombre,creditos,area",
            "1,MAT1110,Matemática,6,Matemáticas",
        ],
    )
    correr_carga(tmp_path)

    malla = Malla.objects.get(version="2026")
    assert MallaAsignatura.objects.filter(malla=malla).count() == 1
    assert Asignatura.objects.filter(sigla="PRO1101").exists()


@pytest.mark.django_db
def test_sigla_en_dos_mallas_es_una_asignatura_y_area_vacia_no_borra_anterior(
    tmp_path,
):
    escribir_csv(
        tmp_path / "carreras.csv",
        [
            "codigo,nombre,escuela,activa,malla_version,vigente_desde",
            "CAR-A,Carrera A,Escuela,true,2026,2026-03-01",
            "CAR-B,Carrera B,Escuela,true,2026,2026-03-01",
        ],
    )
    escribir_csv(
        tmp_path / "mallas" / "CAR-A.csv",
        [
            "semestre,sigla,nombre,creditos,area",
            "1,MAT1110,Matemática Aplicada,6,Matemáticas",
        ],
    )
    escribir_csv(
        tmp_path / "mallas" / "CAR-B.csv",
        [
            "semestre,sigla,nombre,creditos,area",
            "2,MAT1110,Matemática Aplicada,,",
        ],
    )

    correr_carga(tmp_path)

    assert Asignatura.objects.filter(sigla="MAT1110").count() == 1
    asignatura = Asignatura.objects.get(sigla="MAT1110")
    assert asignatura.area == "Matemáticas"
    assert asignatura.creditos == 6
    assert MallaAsignatura.objects.filter(asignatura=asignatura).count() == 2


@pytest.mark.django_db
def test_id_explicito_se_respeta_y_sin_el_se_calcula_uuid5(tmp_path):
    id_fijo = uuid.UUID("11111111-2222-4333-8444-555555555555")
    escribir_csv(
        tmp_path / "sedes.csv",
        [
            "codigo,nombre,region,activa,id",
            f"SEDE-CON-ID,Sede Con ID,Metropolitana,true,{id_fijo}",
            "SEDE-SIN-ID,Sede Sin ID,Metropolitana,true,",
        ],
    )
    escribir_csv(
        tmp_path / "carreras.csv",
        [
            "codigo,nombre,escuela,activa,malla_version,vigente_desde",
            "CAR-UUID5,Carrera UUID5,Escuela,true,2026,2026-03-01",
        ],
    )
    escribir_csv(
        tmp_path / "mallas" / "CAR-UUID5.csv",
        [
            "semestre,sigla,nombre,creditos,area",
            "1,ASIG101,Asignatura UUID5,4,Area",
        ],
    )

    correr_carga(tmp_path)

    assert Sede.objects.get(codigo="SEDE-CON-ID").id == id_fijo
    assert Sede.objects.get(codigo="SEDE-SIN-ID").id == uuid.uuid5(
        ESPACIO, "sede:SEDE-SIN-ID"
    )
    assert Carrera.objects.get(codigo="CAR-UUID5").id == uuid.uuid5(
        ESPACIO, "carrera:CAR-UUID5"
    )
    assert Asignatura.objects.get(sigla="ASIG101").id == uuid.uuid5(
        ESPACIO, "asignatura:ASIG101"
    )


@pytest.mark.django_db
def test_encabezado_con_punto_y_coma_rechaza_archivo_nombra_excel_y_carga_resto(
    tmp_path,
):
    escribir_csv(
        tmp_path / "sedes.csv",
        [
            "codigo;nombre;region;activa",
            "SAN-JOAQUIN;San Joaquín;Metropolitana;true",
        ],
    )
    escribir_csv(
        tmp_path / "carreras.csv",
        [
            "codigo,nombre,escuela,activa,malla_version,vigente_desde",
            "ING-PRU,Ingeniería de Prueba,Escuela,true,2026,2026-03-01",
        ],
    )

    with pytest.raises(CommandError):
        correr_carga(tmp_path)

    assert Sede.objects.count() == 0
    assert Carrera.objects.filter(codigo="ING-PRU").exists()

    imp_sedes = ImportacionCatalogo.objects.get(tipo=TipoImportacion.SEDES)
    assert imp_sedes.filas_leidas == 1
    assert imp_sedes.filas_creadas == 0
    assert imp_sedes.filas_omitidas == 1
    error = ImportacionError.objects.get(importacion=imp_sedes)
    assert error.fila == 1
    assert "Excel" in error.mensaje


@pytest.mark.django_db
def test_malla_cuya_carrera_no_esta_en_carreras_csv_se_rechaza_entera(tmp_path):
    escribir_csv(
        tmp_path / "carreras.csv",
        [
            "codigo,nombre,escuela,activa,malla_version,vigente_desde",
            "ING-OTRA,Otra Carrera,Escuela,true,2026,2026-03-01",
        ],
    )
    escribir_csv(
        tmp_path / "mallas" / "NO-EXISTE.csv",
        [
            "semestre,sigla,nombre,creditos,area",
            "1,PRU1101,Asignatura,4,Area",
        ],
    )

    with pytest.raises(CommandError):
        correr_carga(tmp_path)

    imp_malla = ImportacionCatalogo.objects.get(tipo=TipoImportacion.MALLA)
    assert imp_malla.archivo == "mallas/NO-EXISTE.csv"
    assert imp_malla.filas_leidas == 1
    assert imp_malla.filas_creadas == 0
    assert imp_malla.filas_omitidas == 1
    error = ImportacionError.objects.get(importacion=imp_malla)
    assert error.fila == 1
    assert "NO-EXISTE" in error.mensaje
    assert "carreras.csv" in error.mensaje


@pytest.mark.django_db
def test_sin_carreras_ni_mallas_carga_sedes_avisa_y_termina_sin_error(tmp_path):
    escribir_csv(
        tmp_path / "sedes.csv",
        [
            "codigo,nombre,region,activa",
            "SAN-JOAQUIN,San Joaquín,Metropolitana,true",
        ],
    )

    salida = correr_carga(tmp_path)

    assert Sede.objects.count() == 1
    assert "carreras.csv" in salida
    assert "mallas/" in salida
    assert "Listo." in salida


@pytest.mark.django_db
def test_archivo_guardado_con_bom_se_lee_igual(tmp_path):
    escribir_csv(
        tmp_path / "sedes.csv",
        [
            "codigo,nombre,region,activa",
            "SAN-JOAQUIN,San Joaquín,Metropolitana,true",
        ],
        encoding="utf-8-sig",
    )

    correr_carga(tmp_path)

    assert Sede.objects.filter(codigo="SAN-JOAQUIN").exists()
    imp = ImportacionCatalogo.objects.get(tipo=TipoImportacion.SEDES)
    assert imp.filas_creadas == 1
    assert imp.filas_omitidas == 0
