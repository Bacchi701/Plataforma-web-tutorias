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
| Administración en Turismo y Hospitalidad | ADM-TURISMO-HOSP | duoc.cl, MALLA_CURRICULAR-Administración-en-Turismo-y-Hospitalidad-DuocUC-2026.pdf | 04-11-2026 | 34 | 4: 4 vacantes de Diploma (1° a 4° sem); 2 vacantes de Mención (7° y 8° sem); Formación Cristiana (optativo, 2° o 3° sem); Electivo en Capacidades y Competencias Globales (optativo, 2° o 3° sem) | - |
| Informática Biomédica | INF-BIOMEDICA | duoc.cl, MALLA_CURRICULAR-Informática-Biomédica-DuocUC-2026.pdf | 04-11-2026 | 39 | 4: Optativo Formación Cristiana (3° sem); Capacidades y Competencias Globales (optativo, 3° sem); Optativo Disciplinar (6° sem); Capacidades y Competencias Globales (optativo, 7° sem) | - |
| Ingeniería Agrícola | ING-AGRICOLA | duoc.cl, MALLA_CURRICULAR-Ingeniería-Agrícola-DuocUC-2026.pdf | 04-11-2026 | 44 | 3: Formación Cristiana (optativo, 2°-8° sem); Formación de Capacidades y Competencias Globales (optativo, 2°-8° sem); Optativo Disciplinar (optativo, 3°-8° sem) | - |
| Ingeniería en Electricidad y Automatización Industrial | ING-ELEC-AUTOMATIZ | duoc.cl, MALLA_CURRICULAR-Ingeniería-en-Electricidad-y-Automatización-Industrial-DuocUC-2026.pdf | 04-11-2026 | 41 | 6: Electivo Capacidades y Competencias Globales (2° sem); Formación Cristiana (3° sem); Optativo Formación Disciplinar I (3° sem); Electivo Capacidades y Competencias Globales (5° sem); Optativo Formación Disciplinar II (5° sem); Optativo Formación Disciplinar III (6° sem) | - |
| Ingeniería en Informática | ING-INFORMATICA | duoc.cl, MALLA_CURRICULAR-Ingeniería-en-Informática-Mención-Inteligencia-Artificial-DuocUC-2026.pdf | 04-11-2026 | 37 | 3: Formación Cristiana (optativo, 3°-7°); Electivo de Capacidades y Competencias Globales (optativo, 3°-7°); Formación Optativa Disciplinar (optativo, 3°-7°) | - |
| Ingeniería en Mantenimiento Industrial | ING-MANTENIMIENTO | duoc.cl, MALLA_CURRICULAR-Ingeniería-en-Mantenimiento-Industrial-DuocUC-2026.pdf | 04-11-2026 | 42 | 3: Formación Cristiana (optativo, 2°-8° sem); Formación Disciplinar e Interdisciplinar (optativo, 2°-8° sem); Formación en Capacidades y Competencias Globales (optativo, 2°-8° sem) | - |
| Ingeniería en Maquinaria y Vehículos Pesados | ING-MAQUINARIA | duoc.cl, MALLA_CURRICULAR-Ingeniería-en-Maquinaria-y-Vehículos-Pesados-DuocUC-2026.pdf | 04-11-2026 | 42 | 3: Formación Cristiana (cupo electivo, 2°-7° sem); Electivo de Capacidades y Competencias Globales (cupo electivo, 2°-7° sem); Formación Optativa Disciplinar (cupo electivo, 2°-7° sem) | - |
| Ingeniería en Marketing Digital | ING-MARKETING | duoc.cl, MALLA_CURRICULAR-Ingeniería-en-Marketing-Digital-DuocUC-2026.pdf | 04-11-2026 | 40 | 5: Formación Cristiana (4° sem); Electivo Competencias Globales (4° sem); Formación Optativa (5° sem); Formación Optativa (7°-8° sem, 2 semestres); Electivo Competencias Globales (8° sem) | - |
| Ingeniería en Mecánica Automotriz y Autotrónica | ING-MEC-AUTOMOTRIZ | duoc.cl, MALLA_CURRICULAR-Ingeniería-en-Mecánica-Automotriz-y-Autotrónica-DuocUC-2026.pdf | 04-11-2026 | 36 | 6: Electivo Formación Cristiana (3° sem); Electivo Capacidades y Competencias Globales 1 (3° sem); Optativo Formación Disciplinar 1 (3° sem); Electivo Capacidades y Competencias Globales 2 (5° sem); Optativo Formación Disciplinar 2 (6° sem); Optativo Formación Disciplinar 3 (7° sem) | - |
| Ingeniería en Recursos Naturales y Sostenibilidad | ING-REC-NATURALES | duoc.cl, MALLA_CURRICULAR-Ingeniería-en-Recursos-Naturales-y-Sostenibilidad-DuocUC-2026.pdf | 04-11-2026 | 44 | 3: Electivo Capacidades y Competencias Globales (3°); Electivo de Formación Cristiana (4°); Electivo de Profundización (7°) | - |
| Preparador Físico | PREPARADOR-FISICO | duoc.cl, MALLA_CURRICULAR-Preparador-Físico-DuocUC-2026.pdf | 04-11-2026 | 25 | 3: Formación Cristiana (optativo, 2°-5° sem); Formación Disciplinar e Interdisciplinar (optativo, 2°-5° sem); Formación en Capacidades y Competencias Globales (optativo, 2°-5° sem) | - |
| Técnico Audiovisual | TEC-AUDIOVISUAL | duoc.cl, MALLA_CURRICULAR-Técnico-Audiovisual-DuocUC-2026.pdf | 04-11-2026 | 27 | 3: Formación Cristiana (3° sem); Formación de Capacidades y Competencias Globales (3° sem); Formación Optativa Disciplinar (4° sem) | - |
| Técnico en Calidad de Alimentos | TEC-CALIDAD-ALIM | duoc.cl, MALLA_CURRICULAR-Técnico-en-Calidad-de-Alimentos-DuocUC-2026.pdf | 04-11-2026 | 20 | 4: Optativo Disciplinar 1 (3° sem); Electivo de Capacidades y Competencias Globales (3° sem); Formación Cristiana (3° sem); Optativo Disciplinar 2 (4° sem) | - |
| Técnico en Desabolladura y Pintura Automotriz | TEC-DESABOLLADURA | duoc.cl, MALLA_CURRICULAR-Técnico-en-Desabolladura-y-Pintura-Automotriz-DuocUC-2026.pdf | 04-11-2026 | 20 | 4: Electivo de Capacidades y Competencias Globales (2°); Optativo de Formación Disciplinar I (3°); Optativo de Formación Cristiana (3°); Optativo de Formación Disciplinar II (4°) | - |
| Técnico en Electricidad y Automatización Industrial | TEC-ELEC-AUTOMATIZ | duoc.cl, MALLA_CURRICULAR-Técnico-en-Electricidad-y-Automatización-Industrial-DuocUC-2026.pdf | 04-11-2026 | 26 | 3: Electivo Capacidades y Competencias Globales (2° sem); Electivo Formación Cristiana (3° sem); Optativo Formación Disciplinar I (3° sem) | - |
| Técnico en Electricidad y Energías Renovables | TEC-ELEC-RENOVABLES | duoc.cl, MALLA_CURRICULAR-Técnico-en-Electricidad-y-Energías-Renovables-DuocUC-2026.pdf | 04-11-2026 | 27 | 3: Formación Cristiana (optativo, 2°-4° sem); Formación Disciplinar e Interdisciplinar (optativo, 2°-4° sem); Formación en Capacidades y Competencias Globales (optativo, 2°-4° sem) | - |
| Técnico en Laboratorio Clínico, Banco de Sangre e Imagenología | TEC-LAB-CLINICO | duoc.cl, MALLA_CURRICULAR-Técnico-en-Laboratorio-Clínico-Banco-de-Sangre-e-Imagenología-DuocUC-2026.pdf | 04-11-2026 | 27 | 3: Optativo Formación Disciplinar e Interdisciplinar (3°); Optativo Capacidades y Competencias Globales (3°); Formación Cristiana (4°) | - |
| Técnico en Mantenimiento Industrial | TEC-MANTENIMIENTO | duoc.cl, MALLA_CURRICULAR-Técnico-en-Mantenimiento-Industrial-DuocUC-2026.pdf | 04-11-2026 | 26 | 3: Formación Cristiana (cupo electivo, 2°-5° sem); Formación Disciplinar e Interdisciplinar (cupo electivo, 2°-5° sem); Formación en Capacidades y Competencias Globales (cupo electivo, 2°-5° sem) | - |
| Técnico en Mecánica Automotriz y Autotrónica | TEC-MEC-AUTOMOTRIZ | duoc.cl, MALLA_CURRICULAR-Técnico-en-Mecánica-Automotriz-y-Autotrónica-DuocUC-2026.pdf | 04-11-2026 | 25 | 3: Electivo Formación Cristiana (3° sem); Electivo Capacidades y Competencias Globales 1 (3° sem); Optativo Formación Disciplinar 1 (3° sem) | - |
| Técnico Modelador Proyectista | TEC-MODELADOR | duoc.cl, MALLA_CURRICULAR-Técnico-Modelador-Proyectista-DuocUC-2026.pdf | 04-11-2026 | 22 | 4: Optativo Formación Complementaria I (3°); Optativo Formación Cristiana (3°); Optativo Formación Complementaria II (4°); Optativo Capacidades y Competencias Globales (4°) | - |
| Técnico en Operación y Supervisión de Procesos Mineros | TEC-PROCESOS-MINEROS | duoc.cl, MALLA_CURRICULAR-Técnico-en-Operación-y-Supervisión-de-Procesos-Mineros-DuocUC-2026.pdf | 04-11-2026 | 27 | 3: Formación Cristiana (optativo, 2°-4° sem); Formación Disciplinar e Interdisciplinar (optativo, 2°-4° sem); Formación en Capacidades y Competencias Globales (optativo, 2°-4° sem) | - |
| Técnico en Turismo y Hospitalidad | TEC-TURISMO-HOSP | duoc.cl, MALLA_CURRICULAR-Técnico-en-Turismo-y-Hospitalidad-DuocUC-2026.pdf | 04-11-2026 | 22 | 3: 4 vacantes de Diploma (1° a 4° sem); Formación Cristiana (optativo, 2° o 3° sem); Electivo Competencias Globales (optativo, 2° o 3° sem) | - |
| Técnico Veterinario y Pecuario | TEC-VETERINARIO | duoc.cl, MALLA_CURRICULAR-Técnico-Veterinario-y-Pecuario-DuocUC-2026.pdf | 04-11-2026 | 25 | 3: Capacidades y Competencias Globales (optativo, 2° sem); Optativo Formación Cristiana (3° sem); Optativo Disciplinar (4° sem) | - |

Transcripción: 04-11-2026 · tiempo total: 3 horas

### Notas

- Se transcribieron también 9 carreras que se dictan por bimestres, pero no se cargan porque el catálogo cuenta semestres: Auditoría y Análisis de Negocios, Ingeniería en Automatización y Control Industrial, Ingeniería en Ciberseguridad, Ingeniería en Ciencia de Datos, Ingeniería en Control de Gestión, Ingeniería Industrial, Ingeniería en Minas, Ingeniería en Administración de Seguridad Privada y Técnico en Trabajo Social.
