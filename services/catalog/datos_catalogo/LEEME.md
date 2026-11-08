# Datos del catálogo académico (`datos_catalogo`)

Esta carpeta contiene los archivos CSV que alimentan el catálogo académico mediante el comando `python manage.py cargar_catalogo`.

> **Aviso importante:** No abras ni guardes estos CSV con Excel: los cambia a punto y coma.

## ¿Qué hay en esta carpeta?

- `sedes.csv`: lista de sedes disponibles. Hoy proviene de los datos de ejemplo (`data/seeds/demo/catalog.sql`), que se declaran ficticios hasta que se confirme la lista oficial de sedes de Duoc UC y su fuente.
- `carreras.csv` y la subcarpeta `mallas/`: llegan con **HU-13**, con carreras reales transcritas de las mallas oficiales de Duoc UC.

## Formato de los archivos

Todos los archivos deben estar codificados en **UTF-8**, separados por **comas** (`,`) y con encabezado en la primera línea.

### 1. `sedes.csv`
Columnas: `codigo,nombre,region,activa` (y opcionalmente `id` al final).

```csv
codigo,nombre,region,activa,id
SAN-JOAQUIN,San Joaquín,Metropolitana,true,30000000-0000-4000-8000-000000000011
VALPARAISO,Valparaíso,Valparaíso,true,30000000-0000-4000-8000-000000000009
```

### 2. `carreras.csv`
Columnas: `codigo,nombre,escuela,activa,malla_version,vigente_desde` (y opcionalmente `id` al final).

```csv
codigo,nombre,escuela,activa,malla_version,vigente_desde
ING-INFORMATICA,Ingeniería en Informática,Escuela de Informática y Telecomunicaciones,true,2026,2026-03-01
```

### 3. `mallas/<CODIGO>.csv`
El nombre del archivo debe coincidir con el `codigo` de la carrera en `carreras.csv`.
Columnas: `semestre,sigla,nombre,creditos,area`.

```csv
semestre,sigla,nombre,creditos,area
1,MAT1110,Herramientas de Matemáticas para el Análisis,6,Matemáticas
1,PRY1101,Fundamentos de Programación,8,Programación
```

## Cómo ejecutar la carga

Como los archivos CSV se copian dentro de la imagen del contenedor al construirla, cada vez que agregues o modifiques un CSV debes reconstruir `catalog`, ejecutar el comando y reiniciar `gateway` (son los mismos comandos en macOS y en Windows):

```bash
docker compose up -d --build --wait catalog
docker compose exec -T catalog python manage.py cargar_catalogo
docker compose restart gateway
```

> **Nota sobre los datos de ejemplo:** Los scripts de demostración (`sh scripts/levantar_demo.sh` en macOS/Linux o `scripts\cargar_datos_demo.ps1` en Windows) vacían las tablas del catálogo (`TRUNCATE`) antes de insertar las semillas de prueba. Por lo tanto, si quieres ver el catálogo completo después de levantar la demo, corre `cargar_catalogo` **después** de ellos.

## Reglas de la carga

- **Idempotente (se puede repetir):** Ejecutar el comando varias veces no duplica sedes, carreras, mallas ni asignaturas; actualiza los registros existentes y conserva sus identificadores.
- **Cómo nacen los identificadores (`id`):** Si el CSV incluye la columna `id` (en sedes o carreras), se usa ese UUID. Si no viene (o en asignaturas), se calcula de forma determinista con `uuid5` a partir del código de la sede, el código de la carrera o la sigla de la asignatura. Así los identificadores son idénticos en todos los clones del repositorio y en cada recarga.
- **Versiones de malla:** Si en `carreras.csv` cambia `malla_version` con una fecha `vigente_desde` posterior a la malla vigente actual, el comando cierra automáticamente la malla anterior (`vigente_hasta` pasa a ser el día anterior al `vigente_desde` nuevo) y crea la nueva como única malla vigente. Si la versión ya existe y es la vigente, sincroniza sus asignaturas con el archivo CSV.
- **Estabilidad de códigos y siglas:** Nunca cambies el `codigo` de una carrera ni la `sigla` de una asignatura ya cargada, ya que de ellos dependen sus UUID deterministas y las referencias en otros servicios (como las copias de lectura en Tutorías).

## Carreras transcritas

| Carrera | Código | Fuente (dirección en duoc.cl) | Fecha de consulta | Asignaturas | Sin sigla en la malla | Tiempo de transcripción |
|---|---|---|---|---|---|---|
