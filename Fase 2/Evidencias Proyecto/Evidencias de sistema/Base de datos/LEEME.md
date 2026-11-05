# Evidencias de sistema · Base de datos

Versión 1.0 · 03-11-2026 · datos al 02-11-2026

El modelo de datos de la plataforma tiene 21 tablas, repartidas en cuatro bases
PostgreSQL: una por servicio. Esta carpeta tiene dos versiones de los
diagramas entidad-relación y la revisión de normalización del 30-09-2026.

## `diagramas/`: la versión vigente

Es una copia exacta de los diagramas 01 a 05 de
[`docs/diagramas/`](../../../../docs/diagramas/), que llegaron a `develop` con
el PR #25, el 30-10-2026, y se pusieron al día el 03-11-2026 con el anexo A
v1.6: sus encabezados dicen «Anexo A v1.6», y en la vista global la llamada 2
dice «Tutorías pide el aviso por correo». Describe el modelo implementado: las
migraciones del 01-10-2026, con la revisión de normalización del 30-09-2026, y
la columna `asignatura.area`, que llegó con el PR #9 (HU-12).

| Archivo           | Qué muestra                                                                |
| ----------------- | -------------------------------------------------------------------------- |
| `01_identity_db`  | La base de Identidad                                                        |
| `02_catalog_db`   | La base del Catálogo académico                                              |
| `03_tutoring_db`  | La base de Tutorías                                                         |
| `04_payment_db`   | La base de Pagos                                                            |
| `05_vista_global` | Las entidades que participan de una frontera entre servicios, con algunas de su base como contexto |

Cada diagrama está en dos archivos: la fuente en Mermaid (`.mmd`) y su imagen
(`.png`). Los originales están en `docs/diagramas/`; esta carpeta es una copia.

## `diagramas_30-09/`: la copia del 30-09-2026

Son los diagramas que acompañaron al informe de avance de la Fase 2 (sus
evidencias A9 a A11), y se conservan sin cambios. Sus encabezados dicen
«Anexo A v1.3», y los diagramas difieren de la versión vigente: por ejemplo,
`pago.id` dice `gen_random_uuid` (hoy los identificadores los genera Django) y
`asignatura` no tiene la columna `area`.

## `Normalizacion.pdf`

La revisión de normalización del modelo, del 30-09-2026, preparada para la
demostración del 02-10. Es la evidencia A23 del informe de avance. Su
conclusión sigue vigente: las 21 tablas están en tercera forma normal, después
de corregir las tres que la revisión encontró fuera de forma normal (M-01 a
M-03 en el anexo A del Pilar 2). Sus
figuras son las de esa fecha, las mismas de `diagramas_30-09/`. Algunas frases
describen en presente lo que al 02-11 todavía no existe, como el programador
de tareas que refresca las copias de lectura (HU-19 y HU-37) y el recálculo de
la reputación al evaluar (HU-25), que son del Sprint 4.
