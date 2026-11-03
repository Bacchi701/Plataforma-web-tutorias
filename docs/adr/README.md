# Decisiones de arquitectura

Versión 1.0 · 03-11-2026 · datos al 02-11-2026

Esta carpeta no repite las decisiones: dice dónde está escrita cada una.

- Las decisiones AD-01 a AD-15, con sus alternativas y su justificación, están
  en la sección 1 del Pilar 2, «Diseño y arquitectura», versión 1.8:
  [`docs/planificacion/Planificacion_Pilar2_Arquitectura.docx`](../planificacion/Planificacion_Pilar2_Arquitectura.docx).
- Los cambios del modelo de datos, cada uno con su origen, están en la sección
  3.1 del anexo A del Pilar 2, versión 1.6:
  [`docs/planificacion/Pilar2_AnexoA_Modelo_de_Datos.docx`](../planificacion/Pilar2_AnexoA_Modelo_de_Datos.docx).
- Los contratos de las API están en [`docs/api/`](../api/), y los diagramas,
  en [`docs/diagramas/`](../diagramas/).

## AD-01 a AD-15

Son de la planificación, y están en el Pilar 2 desde la versión que indica la
última columna, según su control de cambios.

| Decisión | Tema                                                                                   | Desde              |
| -------- | -------------------------------------------------------------------------------------- | ------------------ |
| AD-01    | Cuatro microservicios: Identidad, Catálogo académico, Tutorías y Pagos                 | v1.0 (02-09-2026)  |
| AD-02    | Django REST Framework y PostgreSQL                                                     | v1.0 (02-09-2026)  |
| AD-03    | Nginx como gateway (proxy inverso), sin lógica de negocio                              | v1.0 (02-09-2026)  |
| AD-04    | Monorepo, con una carpeta por servicio                                                 | v1.0 (02-09-2026)  |
| AD-05    | Comunicación síncrona REST sobre JSON                                                  | v1.0 (02-09-2026)  |
| AD-06    | Tokens JWT firmados con RS256                                                          | v1.0 (02-09-2026)  |
| AD-07    | Copias de lectura de los datos de otros servicios                                      | v1.0 (02-09-2026)  |
| AD-08    | Una base de datos PostgreSQL por servicio                                              | v1.0 (02-09-2026)  |
| AD-09    | Panel de administración propio, con rutas protegidas por la marca de administrador     | v1.1 (11-09-2026)  |
| AD-10    | Contenedor programador que corre cada cinco minutos los comandos de Tutorías           | v1.1 (11-09-2026)  |
| AD-11    | Mailpit como correo de desarrollo; Identidad es el único servicio que envía correos    | v1.1 (11-09-2026)  |
| AD-12    | Frontend. Cambió el 21-10-2026 (ver la tabla siguiente)                                | v1.1 (11-09-2026)  |
| AD-13    | Token de acceso en memoria y token de renovación en una cookie httpOnly                | v1.1 (11-09-2026)  |
| AD-14    | Cuenta propia en Identidad, con el correo @duocuc.cl verificado                        | v1.6 (25-09-2026)  |
| AD-15    | La carrera y la sede se guardan como identificadores y se validan donde se usan        | v1.7 (25-09-2026)  |

## Decisiones posteriores al 25-09-2026

El 25-09-2026 se cerró la planificación, con el Pilar 2 en la versión 1.7.
Estas son las decisiones de arquitectura y del modelo de datos que se tomaron
después. Las recogen la versión 1.8 del Pilar 2 y la 1.6 del anexo A.

| Fecha      | Decisión | Dónde está escrita | Evidencia en el repositorio |
| ---------- | -------- | ------------------ | --------------------------- |
| 30-09-2026 | Revisión de normalización del modelo, con tres correcciones: `usuario_ref` deja de copiar los nombres de la carrera y de la sede (M-01); `reserva` deja de guardar `tutor_usuario_id`, y la regla de que nadie reserva un bloque propio pasa a un disparador (M-02); los errores de la carga del catálogo pasan de una columna a la tabla `importacion_error` (M-03). | Anexo A, sección 3.1 | [`Normalizacion.pdf`](../../Fase%202/Evidencias%20Proyecto/Evidencias%20de%20sistema/Base%20de%20datos/Normalizacion.pdf), del 30-09; las migraciones iniciales de los cuatro servicios, del 01-10, que llegaron a `develop` con los PR #5 a #8 |
| 21-10-2026 | AD-12 cambia: el profesor aceptó que el frontend sean páginas HTML, CSS y JavaScript sin framework, que el gateway sirve en `/app/`, en vez de React con Vite. Era la alternativa que la misma AD-12 dejaba prevista. | Pilar 2, sección 1 (AD-12); [README](../../README.md), «Tecnologías utilizadas» | PR #10 (HU-06), fusionado el 22-10; la carpeta `frontend/` |
| 23-10-2026 | T-174: al confirmar una reserva, su `estado_pago` queda en nulo, y pasa a PENDIENTE cuando Pagos crea el pago. | Anexo A, sección 3.1 (M-10) y sección 9; Pilar 2, sección 7 | El comentario de `estado_pago` en `services/tutoring/tutorias/models.py` y el diagrama [`03_tutoring_db.mmd`](../diagramas/03_tutoring_db.mmd) |
| 29-10-2026 | Para declarar una asignatura (HU-14) y poner al día la copia de sus datos (HU-41), Tutorías le pide a Identidad `GET /yo` con el token del propio usuario, y a Catálogo, la malla pública de su carrera. Las rutas `/internal`, con una clave de servicio, quedan para lo que necesite datos de otro usuario y para Pagos. La respuesta de `GET /yo` trae el correo, pero Tutorías no lo guarda. | Pilar 2, secciones 2, 5.4 y 7; [README](../../README.md), «Arquitectura de la solución» | PR #21 (HU-14 y HU-41), fusionado el 29-10; `services/tutoring/tutorias/llamadas.py` |

Los demás cambios del modelo implementado (M-04 a M-14), con su origen, están
en la misma sección 3.1 del anexo A.
