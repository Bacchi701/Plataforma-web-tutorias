"""Carga idempotente del catalogo academico desde archivos CSV (HU-07)."""

import csv
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from ...models import (
    Asignatura,
    Carrera,
    ImportacionCatalogo,
    ImportacionError,
    Malla,
    MallaAsignatura,
    Sede,
    TipoImportacion,
)

# No se cambia nunca: el anexo A pide uuid v4, y aquí va uuid5 para que los ids
# sean los mismos en todos los clones y en cada recarga, y las copias de lectura
# de Tutorías y los datos de ejemplo sigan apuntando a lo mismo. El modelo no cambia.
ESPACIO = uuid.uuid5(
    uuid.NAMESPACE_URL,
    "https://github.com/Bacchi701/Plataforma-web-tutorias/catalogo",
)

PATRON_CODIGO = re.compile(r"^[A-Z0-9-]+$")
PATRON_FECHA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")

ENCABEZADOS_SEDES = (
    ["codigo", "nombre", "region", "activa"],
    ["codigo", "nombre", "region", "activa", "id"],
)
ENCABEZADOS_CARRERAS = (
    ["codigo", "nombre", "escuela", "activa", "malla_version", "vigente_desde"],
    [
        "codigo",
        "nombre",
        "escuela",
        "activa",
        "malla_version",
        "vigente_desde",
        "id",
    ],
)
ENCABEZADOS_MALLA = (["semestre", "sigla", "nombre", "creditos", "area"],)


class _ErrorFila(Exception):
    """Fallo de validación en una fila individual del CSV."""


class _RechazoArchivo(Exception):
    """Fallo que obliga a rechazar el archivo CSV completo."""


@dataclass
class _ResumenArchivo:
    archivo: str
    tipo: str
    leidas: int = 0
    creadas: int = 0
    actualizadas: int = 0
    quitadas: int = 0
    omitidas: int = 0
    rechazado: bool = False
    errores: list[tuple[int, str]] = field(default_factory=list)


@dataclass
class _CarreraEnCarga:
    carrera: Carrera
    malla_version: str
    vigente_desde: date


def _largo_maximo(modelo, campo: str) -> int:
    return modelo._meta.get_field(campo).max_length


def _recortar_mensaje(mensaje: str) -> str:
    max_largo = _largo_maximo(ImportacionError, "mensaje")
    return mensaje[:max_largo]


def _leer_csv(
    ruta: Path, encabezados_validos: tuple[list[str], ...]
) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """Lee el CSV con utf-8-sig, valida el encabezado y devuelve las filas no vacías."""
    esperado_str = ",".join(encabezados_validos[0])
    try:
        with ruta.open("r", encoding="utf-8-sig", newline="") as archivo_csv:
            lector = csv.reader(archivo_csv)
            encabezado: list[str] | None = None
            filas: list[tuple[int, list[str]]] = []
            for fila in lector:
                celdas = [c.strip() for c in fila]
                if not celdas or all(c == "" for c in celdas):
                    continue
                if encabezado is None:
                    encabezado = celdas
                else:
                    filas.append((lector.line_num, celdas))
    except UnicodeDecodeError as exc:
        raise _RechazoArchivo(
            "El archivo no está codificado en UTF-8. "
            "Excel, en configuración chilena, guarda los CSV en otra codificación y "
            "separados por punto y coma: hay que volver a la versión del repositorio."
        ) from exc

    if encabezado is None:
        raise _RechazoArchivo(
            f'El archivo está vacío; se esperaba el encabezado "{esperado_str}". '
            "Excel, en configuración chilena, guarda los CSV separados por punto y "
            "coma y cambia las fechas: hay que volver a la versión del repositorio."
        )

    if encabezado not in encabezados_validos:
        recibido_str = ",".join(encabezado)
        raise _RechazoArchivo(
            f'Encabezado inválido: se esperaba "{esperado_str}" y trae '
            f'"{recibido_str}". Excel, en configuración chilena, guarda los CSV '
            "separados por punto y coma y cambia las fechas: hay que volver a la "
            "versión del repositorio."
        )

    return encabezado, filas


def _contar_filas_datos_brutas(ruta: Path) -> int:
    """Cuenta filas no vacías después de la primera cuando falla el encabezado."""
    try:
        with ruta.open("r", encoding="utf-8-sig", newline="") as archivo_csv:
            lector = csv.reader(archivo_csv)
            no_vacias = [
                fila
                for fila in lector
                if fila and any(celda.strip() != "" for celda in fila)
            ]
            return max(0, len(no_vacias) - 1)
    except Exception:
        return 0


def _validar_codigo(valor: str, nombre_campo: str, max_largo: int) -> str:
    if not valor:
        raise _ErrorFila(f"El campo {nombre_campo} es obligatorio.")
    codigo = valor.upper()
    if len(codigo) > max_largo:
        raise _ErrorFila(
            f'El {nombre_campo} "{codigo}" supera el largo máximo de '
            f"{max_largo} caracteres."
        )
    if not PATRON_CODIGO.match(codigo):
        raise _ErrorFila(
            f'El {nombre_campo} "{valor}" solo admite letras sin tilde, '
            "números y guiones."
        )
    return codigo


def _validar_texto(
    valor: str, nombre_campo: str, max_largo: int, obligatorio: bool = True
) -> str | None:
    if not valor:
        if obligatorio:
            raise _ErrorFila(f"El campo {nombre_campo} es obligatorio.")
        return None
    if len(valor) > max_largo:
        raise _ErrorFila(
            f'El campo {nombre_campo} "{valor}" supera el largo máximo de '
            f"{max_largo} caracteres."
        )
    return valor


def _validar_booleano(valor: str, nombre_campo: str = "activa") -> bool:
    limpio = valor.lower()
    if limpio == "true":
        return True
    if limpio == "false":
        return False
    raise _ErrorFila(
        f'El campo {nombre_campo} "{valor}" tiene que ser "true" o "false".'
    )


def _validar_fecha(valor: str, nombre_campo: str = "vigente_desde") -> date:
    if not valor or not PATRON_FECHA_ISO.match(valor):
        raise _ErrorFila(
            f'{nombre_campo} "{valor}" tiene que ir como AAAA-MM-DD, '
            "por ejemplo 2024-03-01."
        )
    try:
        return date.fromisoformat(valor)
    except ValueError as exc:
        raise _ErrorFila(
            f'{nombre_campo} "{valor}" tiene que ir como AAAA-MM-DD, '
            "por ejemplo 2024-03-01."
        ) from exc


def _validar_uuid_opcional(valor: str) -> uuid.UUID | None:
    if not valor:
        return None
    try:
        return uuid.UUID(valor)
    except ValueError as exc:
        raise _ErrorFila(f'El id "{valor}" no es un UUID válido.') from exc


def _validar_entero_rango(
    valor: str,
    nombre_etiqueta: str,
    minimo: int,
    maximo: int,
    obligatorio: bool = True,
) -> int | None:
    if not valor:
        if obligatorio:
            raise _ErrorFila(
                f'El {nombre_etiqueta} "" tiene que ser un número entero de '
                f"{minimo} a {maximo}."
            )
        return None
    try:
        numero = int(valor)
    except ValueError as exc:
        raise _ErrorFila(
            f'El {nombre_etiqueta} "{valor}" tiene que ser un número entero de '
            f"{minimo} a {maximo}."
        ) from exc
    if numero < minimo or numero > maximo:
        raise _ErrorFila(
            f'El {nombre_etiqueta} "{valor}" tiene que ser un número entero de '
            f"{minimo} a {maximo}."
        )
    return numero


def _registrar_importacion(resumen: _ResumenArchivo) -> None:
    importacion = ImportacionCatalogo.objects.create(
        archivo=resumen.archivo,
        tipo=resumen.tipo,
        filas_leidas=resumen.leidas,
        filas_creadas=resumen.creadas,
        filas_omitidas=resumen.omitidas,
        ejecutada_por=None,
    )
    if resumen.errores:
        ImportacionError.objects.bulk_create(
            [
                ImportacionError(
                    importacion=importacion,
                    fila=num_fila,
                    mensaje=_recortar_mensaje(motivo),
                )
                for num_fila, motivo in resumen.errores
            ]
        )


class Command(BaseCommand):
    help = "Carga sedes, carreras y mallas curriculares desde archivos CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "carpeta",
            nargs="?",
            default=None,
            help=(
                "Carpeta con sedes.csv, carreras.csv y mallas/. "
                "Por defecto, settings.BASE_DIR / 'datos_catalogo'."
            ),
        )

    def handle(self, *args, **opciones):
        if opciones["carpeta"]:
            carpeta = Path(opciones["carpeta"])
            if not carpeta.is_absolute() and not carpeta.exists():
                candidata = Path(settings.BASE_DIR) / carpeta
                if candidata.exists():
                    carpeta = candidata
        else:
            carpeta = Path(settings.BASE_DIR) / "datos_catalogo"

        if not carpeta.exists() or not carpeta.is_dir():
            raise CommandError(f"No existe la carpeta de catálogo: {carpeta}")

        resumenes: list[_ResumenArchivo] = []
        avisos: list[str] = []

        ruta_sedes = carpeta / "sedes.csv"
        if ruta_sedes.is_file():
            resumenes.append(self._cargar_sedes(ruta_sedes))
        else:
            avisos.append("Falta el archivo sedes.csv: se omite la carga de sedes.")

        carreras_en_carga: dict[str, _CarreraEnCarga] = {}
        ruta_carreras = carpeta / "carreras.csv"
        if ruta_carreras.is_file():
            resumen_carreras, carreras_en_carga = self._cargar_carreras(ruta_carreras)
            resumenes.append(resumen_carreras)
        else:
            avisos.append(
                "Falta el archivo carreras.csv: se omite la carga de carreras."
            )

        carpeta_mallas = carpeta / "mallas"
        if carpeta_mallas.is_dir():
            archivos_mallas = sorted(carpeta_mallas.glob("*.csv"))
            if not archivos_mallas:
                avisos.append("La carpeta mallas/ no contiene archivos .csv.")
            for ruta_malla in archivos_mallas:
                resumenes.append(
                    self._cargar_malla(ruta_malla, carreras_en_carga, avisos)
                )
        else:
            avisos.append("Falta la carpeta mallas/: se omite la carga de mallas.")

        self._imprimir_resumen(resumenes, avisos)

        if any(r.rechazado for r in resumenes):
            raise CommandError(
                "Uno o más archivos fueron rechazados enteros durante la carga."
            )

        self.stdout.write(self.style.SUCCESS("Listo."))

    def _cargar_sedes(self, ruta: Path) -> _ResumenArchivo:
        resumen = _ResumenArchivo(archivo="sedes.csv", tipo=TipoImportacion.SEDES)
        max_codigo = _largo_maximo(Sede, "codigo")
        max_nombre = _largo_maximo(Sede, "nombre")
        max_region = _largo_maximo(Sede, "region")

        try:
            encabezado, filas = _leer_csv(ruta, ENCABEZADOS_SEDES)
            resumen.leidas = len(filas)
            tiene_id = len(encabezado) == 5

            with transaction.atomic():
                vistos: dict[str, int] = {}
                for num_fila, celdas in filas:
                    try:
                        with transaction.atomic():
                            if len(celdas) != len(encabezado):
                                raise _ErrorFila(
                                    f"La fila tiene {len(celdas)} columnas; "
                                    f"se esperaban {len(encabezado)}."
                                )
                            codigo_raw, nombre_raw, region_raw, activa_raw = celdas[:4]
                            id_raw = celdas[4] if tiene_id else ""

                            codigo = _validar_codigo(codigo_raw, "codigo", max_codigo)
                            if codigo in vistos:
                                raise _ErrorFila(
                                    f"El código {codigo} ya está en la fila "
                                    f"{vistos[codigo]} de este archivo."
                                )
                            vistos[codigo] = num_fila

                            nombre = _validar_texto(
                                nombre_raw, "nombre", max_nombre, obligatorio=True
                            )
                            region = _validar_texto(
                                region_raw, "region", max_region, obligatorio=False
                            )
                            activa = _validar_booleano(activa_raw, "activa")
                            id_csv = _validar_uuid_opcional(id_raw)

                            if id_csv is not None:
                                otra = (
                                    Sede.objects.filter(id=id_csv)
                                    .exclude(codigo=codigo)
                                    .first()
                                )
                                if otra is not None:
                                    raise _ErrorFila(
                                        f'El id "{id_csv}" ya es de otra sede '
                                        f"({otra.codigo})."
                                    )

                            existente = Sede.objects.filter(codigo=codigo).first()
                            if existente is None:
                                nuevo_id = id_csv or uuid.uuid5(
                                    ESPACIO, "sede:" + codigo
                                )
                                colision = (
                                    Sede.objects.filter(id=nuevo_id)
                                    .exclude(codigo=codigo)
                                    .first()
                                )
                                if colision is not None:
                                    raise _ErrorFila(
                                        f'El id "{nuevo_id}" ya es de otra sede '
                                        f"({colision.codigo})."
                                    )
                                Sede.objects.create(
                                    id=nuevo_id,
                                    codigo=codigo,
                                    nombre=nombre,
                                    region=region,
                                    activa=activa,
                                )
                                resumen.creadas += 1
                            else:
                                existente.nombre = nombre
                                existente.region = region
                                existente.activa = activa
                                existente.save()
                                resumen.actualizadas += 1
                    except _ErrorFila as exc:
                        resumen.omitidas += 1
                        resumen.errores.append((num_fila, str(exc)))
                    except IntegrityError as exc:
                        resumen.omitidas += 1
                        resumen.errores.append(
                            (num_fila, f"Restricción de base de datos: {exc}")
                        )
        except _RechazoArchivo as exc:
            if resumen.leidas == 0:
                resumen.leidas = _contar_filas_datos_brutas(ruta)
            resumen.creadas = 0
            resumen.actualizadas = 0
            resumen.omitidas = resumen.leidas
            resumen.rechazado = True
            resumen.errores = [(1, str(exc))]

        _registrar_importacion(resumen)
        return resumen

    def _cargar_carreras(
        self, ruta: Path
    ) -> tuple[_ResumenArchivo, dict[str, _CarreraEnCarga]]:
        resumen = _ResumenArchivo(archivo="carreras.csv", tipo=TipoImportacion.CARRERAS)
        carreras_en_carga: dict[str, _CarreraEnCarga] = {}

        max_codigo = _largo_maximo(Carrera, "codigo")
        max_nombre = _largo_maximo(Carrera, "nombre")
        max_escuela = _largo_maximo(Carrera, "escuela")
        max_version = _largo_maximo(Malla, "version")

        try:
            encabezado, filas = _leer_csv(ruta, ENCABEZADOS_CARRERAS)
            resumen.leidas = len(filas)
            tiene_id = len(encabezado) == 7

            with transaction.atomic():
                vistos: dict[str, int] = {}
                for num_fila, celdas in filas:
                    try:
                        with transaction.atomic():
                            if len(celdas) != len(encabezado):
                                raise _ErrorFila(
                                    f"La fila tiene {len(celdas)} columnas; "
                                    f"se esperaban {len(encabezado)}."
                                )
                            (
                                codigo_raw,
                                nombre_raw,
                                escuela_raw,
                                activa_raw,
                                version_raw,
                                vigente_raw,
                            ) = celdas[:6]
                            id_raw = celdas[6] if tiene_id else ""

                            codigo = _validar_codigo(codigo_raw, "codigo", max_codigo)
                            if codigo in vistos:
                                raise _ErrorFila(
                                    f"El código {codigo} ya está en la fila "
                                    f"{vistos[codigo]} de este archivo."
                                )
                            vistos[codigo] = num_fila

                            nombre = _validar_texto(
                                nombre_raw, "nombre", max_nombre, obligatorio=True
                            )
                            escuela = _validar_texto(
                                escuela_raw, "escuela", max_escuela, obligatorio=True
                            )
                            activa = _validar_booleano(activa_raw, "activa")
                            malla_version = _validar_texto(
                                version_raw,
                                "malla_version",
                                max_version,
                                obligatorio=True,
                            )
                            vigente_desde = _validar_fecha(vigente_raw, "vigente_desde")
                            id_csv = _validar_uuid_opcional(id_raw)

                            if id_csv is not None:
                                otra = (
                                    Carrera.objects.filter(id=id_csv)
                                    .exclude(codigo=codigo)
                                    .first()
                                )
                                if otra is not None:
                                    raise _ErrorFila(
                                        f'El id "{id_csv}" ya es de otra carrera '
                                        f"({otra.codigo})."
                                    )

                            existente = Carrera.objects.filter(codigo=codigo).first()
                            if existente is None:
                                nuevo_id = id_csv or uuid.uuid5(
                                    ESPACIO, "carrera:" + codigo
                                )
                                colision = (
                                    Carrera.objects.filter(id=nuevo_id)
                                    .exclude(codigo=codigo)
                                    .first()
                                )
                                if colision is not None:
                                    raise _ErrorFila(
                                        f'El id "{nuevo_id}" ya es de otra carrera '
                                        f"({colision.codigo})."
                                    )
                                carrera_obj = Carrera.objects.create(
                                    id=nuevo_id,
                                    codigo=codigo,
                                    nombre=nombre,
                                    escuela=escuela,
                                    activa=activa,
                                )
                                resumen.creadas += 1
                            else:
                                existente.nombre = nombre
                                existente.escuela = escuela
                                existente.activa = activa
                                existente.save()
                                carrera_obj = existente
                                resumen.actualizadas += 1

                            carreras_en_carga[codigo] = _CarreraEnCarga(
                                carrera=carrera_obj,
                                malla_version=malla_version,
                                vigente_desde=vigente_desde,
                            )
                    except _ErrorFila as exc:
                        resumen.omitidas += 1
                        resumen.errores.append((num_fila, str(exc)))
                    except IntegrityError as exc:
                        resumen.omitidas += 1
                        resumen.errores.append(
                            (num_fila, f"Restricción de base de datos: {exc}")
                        )
        except _RechazoArchivo as exc:
            if resumen.leidas == 0:
                resumen.leidas = _contar_filas_datos_brutas(ruta)
            resumen.creadas = 0
            resumen.actualizadas = 0
            resumen.omitidas = resumen.leidas
            resumen.rechazado = True
            resumen.errores = [(1, str(exc))]
            carreras_en_carga = {}

        _registrar_importacion(resumen)
        return resumen, carreras_en_carga

    def _cargar_malla(
        self,
        ruta: Path,
        carreras_en_carga: dict[str, _CarreraEnCarga],
        avisos: list[str],
    ) -> _ResumenArchivo:
        nombre_archivo = f"mallas/{ruta.name}"
        resumen = _ResumenArchivo(archivo=nombre_archivo, tipo=TipoImportacion.MALLA)
        codigo_carrera = ruta.stem.upper()

        max_sigla = _largo_maximo(Asignatura, "sigla")
        max_nombre = _largo_maximo(Asignatura, "nombre")
        max_area = _largo_maximo(Asignatura, "area")

        try:
            encabezado, filas = _leer_csv(ruta, ENCABEZADOS_MALLA)
            resumen.leidas = len(filas)

            if codigo_carrera not in carreras_en_carga:
                raise _RechazoArchivo(
                    f'La carrera "{codigo_carrera}" no está en carreras.csv '
                    "o su fila fue omitida."
                )

            info_carrera = carreras_en_carga[codigo_carrera]
            carrera = info_carrera.carrera
            version = info_carrera.malla_version
            vigente_desde = info_carrera.vigente_desde

            avisos_malla: list[str] = []

            with transaction.atomic():
                malla_existente = Malla.objects.filter(
                    carrera=carrera, version=version
                ).first()
                if (
                    malla_existente is not None
                    and malla_existente.vigente_hasta is not None
                ):
                    raise _RechazoArchivo(
                        f'La versión "{version}" de la carrera "{codigo_carrera}" '
                        "ya existe y está cerrada (vigente hasta "
                        f"{malla_existente.vigente_hasta}): "
                        "el comando no reabre mallas."
                    )

                if malla_existente is None:
                    vigente_actual = Malla.objects.filter(
                        carrera=carrera, vigente_hasta__isnull=True
                    ).first()
                    if vigente_actual is not None:
                        cierre = vigente_desde - timedelta(days=1)
                        if cierre <= vigente_actual.vigente_desde:
                            raise _RechazoArchivo(
                                f"No se puede cerrar la malla vigente "
                                f'"{vigente_actual.version}" (vigente_desde '
                                f"{vigente_actual.vigente_desde}) con vigente_hasta "
                                f'{cierre} para abrir la versión "{version}" '
                                f"(vigente_desde {vigente_desde}): incumple "
                                "ck_malla_vigencia."
                            )
                        vigente_actual.vigente_hasta = cierre
                        vigente_actual.save()

                    malla = Malla.objects.create(
                        carrera=carrera,
                        version=version,
                        vigente_desde=vigente_desde,
                        vigente_hasta=None,
                    )
                else:
                    malla = malla_existente
                    if malla.vigente_desde != vigente_desde:
                        malla.vigente_desde = vigente_desde
                        malla.save()

                vistos: dict[str, int] = {}
                asignaturas_validas: list[Asignatura] = []

                for num_fila, celdas in filas:
                    try:
                        with transaction.atomic():
                            if len(celdas) != len(encabezado):
                                raise _ErrorFila(
                                    f"La fila tiene {len(celdas)} columnas; "
                                    f"se esperaban {len(encabezado)}."
                                )
                            (
                                semestre_raw,
                                sigla_raw,
                                nombre_raw,
                                creditos_raw,
                                area_raw,
                            ) = celdas

                            semestre = _validar_entero_rango(
                                semestre_raw, "semestre", 1, 12, obligatorio=True
                            )
                            if not sigla_raw:
                                raise _ErrorFila("El campo sigla es obligatorio.")
                            sigla = sigla_raw.upper()
                            if len(sigla) > max_sigla:
                                raise _ErrorFila(
                                    f'La sigla "{sigla}" supera el largo máximo de '
                                    f"{max_sigla} caracteres."
                                )
                            if sigla in vistos:
                                raise _ErrorFila(
                                    f"La sigla {sigla} ya está en la fila "
                                    f"{vistos[sigla]} de este archivo."
                                )
                            vistos[sigla] = num_fila

                            nombre = _validar_texto(
                                nombre_raw, "nombre", max_nombre, obligatorio=True
                            )
                            creditos = _validar_entero_rango(
                                creditos_raw, "créditos", 1, 30, obligatorio=False
                            )
                            area = _validar_texto(
                                area_raw, "area", max_area, obligatorio=False
                            )

                            asignatura = Asignatura.objects.filter(sigla=sigla).first()
                            if asignatura is None:
                                asignatura = Asignatura.objects.create(
                                    id=uuid.uuid5(ESPACIO, "asignatura:" + sigla),
                                    sigla=sigla,
                                    nombre=nombre,
                                    creditos=creditos,
                                    area=area,
                                    activa=True,
                                )
                            else:
                                if asignatura.nombre != nombre:
                                    avisos_malla.append(
                                        f"Asignatura {sigla}: cambió el nombre de "
                                        f'"{asignatura.nombre}" a "{nombre}".'
                                    )
                                    asignatura.nombre = nombre
                                if creditos is not None:
                                    asignatura.creditos = creditos
                                if area is not None:
                                    asignatura.area = area
                                asignatura.save()

                            vinculo = MallaAsignatura.objects.filter(
                                malla=malla, asignatura=asignatura
                            ).first()
                            if vinculo is None:
                                MallaAsignatura.objects.create(
                                    malla=malla,
                                    asignatura=asignatura,
                                    semestre=semestre,
                                )
                                resumen.creadas += 1
                            else:
                                if vinculo.semestre != semestre:
                                    vinculo.semestre = semestre
                                    vinculo.save()
                                resumen.actualizadas += 1

                            asignaturas_validas.append(asignatura)
                    except _ErrorFila as exc:
                        resumen.omitidas += 1
                        resumen.errores.append((num_fila, str(exc)))
                    except IntegrityError as exc:
                        resumen.omitidas += 1
                        resumen.errores.append(
                            (num_fila, f"Restricción de base de datos: {exc}")
                        )

                if not asignaturas_validas:
                    raise _RechazoArchivo(
                        f'El archivo "{nombre_archivo}" no tiene ninguna fila válida: '
                        "una malla vigente nunca puede quedar vacía."
                    )

                if malla_existente is not None:
                    para_quitar = MallaAsignatura.objects.filter(malla=malla).exclude(
                        asignatura__in=asignaturas_validas
                    )
                    resumen.quitadas = para_quitar.count()
                    if resumen.quitadas:
                        para_quitar.delete()

            avisos.extend(avisos_malla)

        except _RechazoArchivo as exc:
            if resumen.leidas == 0:
                resumen.leidas = _contar_filas_datos_brutas(ruta)
            resumen.creadas = 0
            resumen.actualizadas = 0
            resumen.quitadas = 0
            resumen.omitidas = resumen.leidas
            resumen.rechazado = True
            resumen.errores = [(1, str(exc))]

        _registrar_importacion(resumen)
        return resumen

    def _imprimir_resumen(
        self, resumenes: list[_ResumenArchivo], avisos: list[str]
    ) -> None:
        for res in resumenes:
            estado = " [RECHAZADO]" if res.rechazado else ""
            if res.tipo == TipoImportacion.MALLA:
                linea = (
                    f"{res.archivo}{estado}: "
                    f"{res.leidas} leídas, "
                    f"{res.creadas} creadas, "
                    f"{res.actualizadas} actualizadas, "
                    f"{res.quitadas} quitadas, "
                    f"{res.omitidas} omitidas"
                )
            else:
                linea = (
                    f"{res.archivo}{estado}: "
                    f"{res.leidas} leídas, "
                    f"{res.creadas} creadas, "
                    f"{res.actualizadas} actualizadas, "
                    f"{res.omitidas} omitidas"
                )
            self.stdout.write(linea)
            for num_fila, motivo in res.errores:
                self.stdout.write(self.style.WARNING(f"  Fila {num_fila}: {motivo}"))

        for aviso in avisos:
            self.stdout.write(self.style.WARNING(f"Aviso: {aviso}"))
