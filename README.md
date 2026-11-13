# Plataforma de Tutorías entre Estudiantes

Plataforma web que conecta a estudiantes de Duoc UC que necesitan apoyo en una
asignatura con compañeros que la dominan.

Proyecto APT · Capstone (PTY4614) · Ingeniería en Informática · Duoc UC · 2026

## Descripción

### Qué problema resuelve

Los estudiantes de Duoc UC recurren con frecuencia a compañeros de cursos
superiores para reforzar las asignaturas que les cuestan, pero esa búsqueda
ocurre de manera informal y dispersa: grupos de mensajería, recomendaciones de
pasillo y contactos personales. No existe un punto centralizado dentro de la
institución donde un estudiante pueda encontrar quién domina una asignatura,
conocer su reputación y coordinar un horario. La ayuda existe, pero no se
encuentra.

### Qué hace

La plataforma centraliza la oferta y la demanda de apoyo académico entre pares.
El producto mínimo viable (MVP) considera:

- Registro con el correo institucional @duocuc.cl, verificado con un enlace de
  un solo uso, e inicio y cierre de sesión.
- Perfil con carrera, nivel y sede.
- Catálogo académico con carreras, sedes, mallas, semestres y asignaturas. El
  modelo está pensado para las 92 carreras de Duoc UC, pero cuenta semestres:
  las que se dictan por bimestres no se cargan. El repositorio trae 23 carreras
  reales con su malla 2026, en archivos CSV que se cargan con un comando (la
  planificación pedía de 3 a 5).
- Declaración de las asignaturas en que un estudiante ofrece tutorías, con la
  tarifa que él mismo fija (puede ser $0). Solo se habilitan asignaturas de su
  malla ubicadas en semestres anteriores a su nivel.
- Publicación de bloques de disponibilidad, búsqueda de tutores por asignatura,
  solicitud de tutoría, confirmación o rechazo, y cancelación.
- Avisos por correo: al tutor cuando recibe una solicitud; al estudiante
  cuando se la confirman o rechazan, y a la otra persona cuando se cancela una
  tutoría o se retira una solicitud.
- Historial de las tutorías solicitadas e impartidas.
- Evaluación de 1 a 5 después de cada sesión, con comentario opcional, y
  reputación visible de cada tutor.
- Pago simulado de la reserva, con reintento y reembolso simulado al cancelar.
- Panel de administración para gestionar los usuarios, revisar las tutorías y
  retirar evaluaciones. El catálogo se carga desde archivos CSV, no desde el
  panel.

La plataforma agenda la tutoría; la sesión ocurre de forma presencial o por un
enlace externo que el tutor indica al confirmar. Quedan fuera de esta versión
la videollamada integrada, el chat interno, la aplicación móvil nativa, los
pagos con dinero real y la integración con los sistemas académicos de Duoc UC,
incluido su inicio de sesión institucional.

### A quién va dirigido

A los estudiantes de Duoc UC. Estudiante y tutor no son cuentas distintas: una
misma persona puede pedir ayuda en los ramos que le cuestan y ofrecerla en los
de semestres anteriores al que cursa.

| Rol           | Qué hace en la plataforma                                                                                             |
| ------------- | --------------------------------------------------------------------------------------------------------------------- |
| Estudiante    | Busca tutores por asignatura, solicita una tutoría, paga (simulado), cancela o retira su solicitud y evalúa al tutor. |
| Tutor         | Declara asignaturas y tarifa, publica su disponibilidad, acepta o rechaza solicitudes y ve su reputación.             |
| Administrador | Busca usuarios y los desactiva o los vuelve a activar, revisa las tutorías y retira evaluaciones.                     |

## Tecnologías utilizadas

| Capa                 | Tecnología                                                                                                                            |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Lenguajes            | Python 3.12 en el backend; JavaScript, HTML y CSS en el frontend                                                                      |
| Backend              | Django 5.2 y Django REST Framework 3.16, servidos con Gunicorn                                                                        |
| Frontend             | HTML, CSS y JavaScript sin framework, servidos por el gateway en `/app/` (la alternativa que dejó prevista AD-12, en lugar del plan con React y Vite; el profesor la aceptó el 21-10) |
| Base de datos        | PostgreSQL 16, una base independiente por microservicio                                                                               |
| API Gateway          | Nginx 1.27                                                                                                                            |
| Autenticación        | Tokens JWT firmados con RS256 (AD-06): solo Identidad los emite, con la clave privada; Identidad, Tutorías y Pagos los verifican con la clave pública |
| Correo               | Mailpit como servidor de correo de desarrollo                                                                                         |
| Contenedores         | Docker y Docker Compose: un Dockerfile por servicio y un `docker-compose.yml` que levanta el sistema completo                         |
| Calidad              | pytest, pytest-django y pytest-cov en los cuatro servicios, con una cobertura mínima de 60 % en Identidad y Tutorías; pruebas de extremo a extremo con pytest contra el sistema levantado (`pruebas_e2e/`), que la integración continua no corre; ruff y black en Python. El frontend no tiene pruebas automáticas: no hay `frontend/package.json`, y la integración continua salta ese paso |
| Integración continua | GitHub Actions                                                                                                                        |
| Cloud                | No se usa. El sistema completo corre en contenedores Docker en cualquier computador; GitHub aloja el código y la integración continua |

## Instrucciones para ejecutar el proyecto localmente

### Requisitos

| Herramienta    | Versión mínima | Cómo comprobarlo                                  |
| -------------- | -------------- | ------------------------------------------------- |
| Git            | 2.40           | `git --version`                                   |
| Docker Desktop | 4.30           | `docker version` (línea `Server: Docker Desktop`) |
| Docker Compose | 2.27           | `docker compose version`                          |

En Windows, Docker Desktop necesita WSL 2 activado. El sistema completo usa
alrededor de 3 GB de memoria; si tu computador tiene 8 GB, cierra el navegador
mientras lo levantas la primera vez.

### Levantar el sistema

```bash
git clone https://github.com/Bacchi701/Plataforma-web-tutorias.git
cd Plataforma-web-tutorias
cp .env.example .env          # PowerShell: Copy-Item .env.example .env
docker compose up -d --build
```

`docker-compose.yml` construye cada servicio desde su
`services/<servicio>/Dockerfile` y levanta once contenedores: el gateway, los
cuatro servicios, sus cuatro bases de datos, la bandeja de correo de
desarrollo y el programador de tareas, que usa la imagen de Tutorías (HU-37).
La primera vez tarda entre 3 y 6 minutos porque construye las
imágenes. Las siguientes, menos de un minuto.

### Comprobar que está arriba

Abre <http://localhost:8080>: la página muestra los cuatro servicios con su
estado. Uno por uno:

| Servicio           | URL                                            |
| ------------------ | ---------------------------------------------- |
| Identidad          | <http://localhost:8080/api/identity/v1/estado> |
| Catálogo académico | <http://localhost:8080/api/catalog/v1/estado>  |
| Tutorías           | <http://localhost:8080/api/tutoring/v1/estado> |
| Pagos              | <http://localhost:8080/api/payments/v1/estado> |

Cada uno responde algo así:

```json
{"servicio": "identity", "estado": "ok", "base_de_datos": "ok", "version": "0.1.0"}
```

Ningún servicio ni base de datos publica un puerto a tu computador: el puerto
8080 del gateway es la única puerta de entrada, que es la condición del
criterio de aceptación CA8.

En `develop` están las historias terminadas (ver «Estado del desarrollo»), y
desde ahí se prueba la demo.

### Probar la demo

Con los datos de ejemplo se recorre el MVP completo, con los avisos por correo
en la bandeja de desarrollo: registro con el correo institucional y
verificación, inicio de sesión, perfil, catálogo, declaración de asignaturas,
disponibilidad del tutor, búsqueda de tutores, solicitud, confirmación o
rechazo, pago simulado, cancelación con reembolso, historial, evaluación y
panel de administración.

En Windows (PowerShell), desde la carpeta del repositorio:

```powershell
git switch develop
git pull --ff-only
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose build identity
docker compose run --rm --no-deps -v "${PWD}\keys:/claves" --entrypoint python identity manage.py generar_claves_jwt --carpeta /claves
docker compose up -d --build --wait
docker compose up -d --force-recreate --wait identity tutoring payments
docker compose restart gateway
powershell -ExecutionPolicy Bypass -File .\scripts\cargar_datos_demo.ps1
```

En macOS, en Linux o en Git Bash de Windows, un script hace todo lo anterior:

```bash
git switch develop && git pull --ff-only
sh scripts/levantar_demo.sh
```

- El comando de las claves genera el par que firma los tokens. La clave
  privada queda en `keys/` y no se sube al repositorio (la excluye
  `.gitignore`); la pública cambia, y Git la mostrará modificada: es normal y
  no hay que subirla. Si ya existe una clave privada, el comando no la
  reemplaza; con `--forzar` la reemplaza y cierra todas las sesiones.
- `docker compose up -d --force-recreate --wait identity tutoring payments`
  hace que Identidad, Tutorías y Pagos lean las claves recién generadas: las
  guardan en memoria al arrancar. Después de un `--forzar` hay que repetirlo,
  junto con el reinicio del gateway.
- `docker compose restart gateway` hace que el gateway vuelva a encontrar a
  los servicios: Nginx busca su dirección solo al arrancar.
- La carga de los datos de ejemplo vacía y vuelve a llenar las cuatro bases.
  Se puede repetir las veces que haga falta. Las cuentas, los tutores y las
  reservas son ficticios.
- Los datos de ejemplo traen un catálogo de prueba de cuatro carreras: tres
  con mallas recortadas y una cerrada a propósito, Diseño Gráfico. Las 23
  carreras reales se cargan aparte, después de los datos de ejemplo, con
  `docker compose up -d --build --wait catalog`,
  `docker compose exec -T catalog python manage.py cargar_catalogo` y
  `docker compose restart gateway` (ver
  `services/catalog/datos_catalogo/LEEME.md`). Las cuentas de ejemplo siguen
  en las carreras de prueba, y con las dos cargas «Ingeniería en Informática»
  aparece dos veces: la de prueba y la real. Si después vuelves a cargar los
  datos de ejemplo, como se hace al terminar las pruebas de extremo a extremo,
  las carreras reales se borran y hay que cargarlas de nuevo.
- En macOS, `levantar_demo.sh` deja `COOKIE_REFRESH_SEGURA=0` en el `.env`:
  Safari no guarda cookies seguras en `http://localhost`, y sin esa cookie la
  sesión no se recupera al recargar la página.

Después abre:

| Qué                                    | Dirección                                      |
| -------------------------------------- | ---------------------------------------------- |
| Estado de los cuatro servicios         | <http://localhost:8080/>                       |
| Portada                                | <http://localhost:8080/app/index.html>         |
| Asignaturas, mallas y sus tutores      | <http://localhost:8080/app/asignaturas.html>   |
| Tutores: los mejor evaluados y la búsqueda por nombre | <http://localhost:8080/app/tutores.html> |
| Registro con correo @duocuc.cl         | <http://localhost:8080/app/registro.html>      |
| Bandeja de correo (verificación y avisos) | <http://localhost:8025>                     |
| Inicio de sesión                       | <http://localhost:8080/app/login.html>         |
| Mi perfil y las asignaturas que enseño (con sesión) | <http://localhost:8080/app/perfil.html> |
| Mi disponibilidad (con sesión, tutores) | <http://localhost:8080/app/disponibilidad.html> |
| Mis reservas: solicitudes, tutorías y pago (con sesión) | <http://localhost:8080/app/reservas.html> |
| Historial y evaluación (con sesión)    | <http://localhost:8080/app/historial.html>     |
| Panel de administración (cuenta de administrador) | <http://localhost:8080/app/admin.html> |

Cuentas de ejemplo, todas con la clave `Tutorias2026`:

| Cuenta                     | Qué muestra                                                                 |
| -------------------------- | --------------------------------------------------------------------------- |
| `valentina.demo@duocuc.cl` | Tutora de Ingeniería en Informática, con asignaturas declaradas y bloques publicados. |
| `camila.demo@duocuc.cl`    | Estudiante de Ingeniería en Informática, en segundo semestre: puede ofrecer tutorías de las asignaturas del primero. Tiene una tutoría confirmada de Desarrollo Web con Matías Fuentes, de una fecha que ya pasó: el programador la marca como realizada en su siguiente pasada (corre cada cinco minutos), y desde ahí se evalúa en «Historial». |
| `matias.demo@duocuc.cl` y `fernanda.demo@duocuc.cl` | Otros dos tutores.                             |
| `diego.demo@duocuc.cl`     | Estudiante de primer semestre: todavía no puede ofrecer tutorías.           |
| `tomas.demo@duocuc.cl`     | Cuenta sin verificar: no puede iniciar sesión.                              |
| `josefa.demo@duocuc.cl`    | Cuenta desactivada: «Tu cuenta está desactivada.»                           |
| `admin.demo@duocuc.cl`     | Administrador: el panel de administración (HU-31 y HU-33). |

Una cuenta nueva se crea en el registro con cualquier correo que termine en
`@duocuc.cl`; el enlace de verificación llega a la bandeja de desarrollo, no a
una casilla real.

### Pruebas de extremo a extremo

Las pruebas de `pruebas_e2e/` (HU-34) corren contra el sistema levantado y
piden todo por el gateway, como la página en el navegador:

- `test_recorrido.py`, el recorrido completo: dos cuentas nuevas se registran,
  verifican su correo y completan su perfil; el tutor declara una asignatura y
  publica un bloque; el estudiante lo busca, solicita la tutoría y la paga
  cuando el tutor la confirma; el programador la cierra y el estudiante la
  evalúa. Revisa también los avisos por correo, una tutoría pagada que se
  cancela con reembolso y una solicitud retirada.
- `test_rnf02_busqueda.py`: la búsqueda de tutores con 500 usuarios de prueba
  responde en menos de 2 segundos (RNF-02).

Corren en un contenedor desechable con Python, conectado a la red del
sistema: no hay que instalar nada. Con el sistema levantado, en Windows
(PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\cargar_datos_demo.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\cargar_usuarios_prueba.ps1
docker run --rm --network plataforma-tutorias_borde -v "${PWD}:/repo" -w /repo -e PYTHONDONTWRITEBYTECODE=1 python:3.12-slim bash -c 'set -o pipefail; pip install -q pytest==8.3.5 && python -m pytest -v -s -p no:cacheprovider pruebas_e2e 2>&1 | tee docs/evidencia/pruebas_e2e_$(date +%F).txt'
```

En macOS, en Linux o en Git Bash de Windows:

```bash
sh scripts/levantar_demo.sh
sh scripts/cargar_usuarios_prueba.sh
MSYS_NO_PATHCONV=1 docker run --rm --network plataforma-tutorias_borde -v "$(pwd -W 2>/dev/null || pwd):/repo" -w /repo -e PYTHONDONTWRITEBYTECODE=1 python:3.12-slim bash -c 'set -o pipefail; pip install -q pytest==8.3.5 && python -m pytest -v -s -p no:cacheprovider pruebas_e2e 2>&1 | tee docs/evidencia/pruebas_e2e_$(date +%F).txt'
```

- Tardan hasta unos 10 minutos: casi todo es esperar que termine el bloque de
  la tutoría y que pase el programador de tareas.
- La salida queda también en `docs/evidencia/pruebas_e2e_<fecha>.txt`, la
  evidencia del portafolio. La fecha es la del contenedor, en UTC.
- Al terminar, vuelve a cargar los datos de ejemplo: borran las cuentas que
  crea el recorrido y la carga de 500 usuarios, y también las 23 carreras
  reales, si las habías cargado.

### Variables de entorno

Todas viven en un solo archivo `.env` en la raíz, que se crea copiando
`.env.example` y nunca se sube al repositorio.

| Variables                                                        | Para qué sirven                                                                                     |
| ---------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `PUERTO_GATEWAY`                                                 | Puerto del gateway en tu computador (8080 por defecto).                                             |
| `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`      | Configuración común de los cuatro servicios.                                                        |
| `IDENTITY_DB_*`, `CATALOG_DB_*`, `TUTORING_DB_*`, `PAYMENT_DB_*` | Nombre, usuario y contraseña de la base de cada servicio.                                           |
| `PUERTO_BANDEJA`                                                 | Puerto de la bandeja de correo de desarrollo (8025 por defecto).                                    |
| `EMAIL_*` y `CORREO_REMITENTE`                                   | Vacías por defecto, así todo el correo cae en Mailpit. Solo se llenan para la prueba de envío real. |
| `URL_FRONTEND`, `COOKIE_REFRESH_SEGURA`                          | La página a la que lleva el enlace del correo de verificación, y si la cookie de renovación de la sesión va marcada como segura (`1`, por defecto). En macOS va en `0` (ver «Probar la demo»). |
| `CLAVE_SERVICIO` | La clave con que los servicios se llaman entre sí, en la cabecera `X-Clave-Servicio`. Vale lo mismo en los cuatro; fuera del computador de desarrollo se cambia. |

### Bandeja de correo de desarrollo

Todo correo que envía Identidad cae en Mailpit y se ve en
<http://localhost:8025>. Nada sale a internet: ningún correo llega a una
persona real. Para mandar uno de prueba:

```bash
docker compose exec identity python manage.py enviar_correo_prueba
```

La bandeja publica un segundo puerto, solo para tu computador (127.0.0.1). Es
una herramienta de desarrollo y no forma parte del sistema evaluado (Pilar 2,
sección 10). Se vacía cada vez que se reinicia su contenedor.

Mailpit no entrega a casillas reales. Para el envío real que exige el supuesto
S-02 del Pilar 5 (un correo de verificación que llegue a una casilla
@duocuc.cl) se llenan en el `.env` de un solo computador las variables
`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`,
`EMAIL_USE_TLS` (con el valor `1` si el servidor usa TLS) y
`CORREO_REMITENTE`, con una cuenta SMTP gratuita. Después,
`docker compose up -d` aplica los cambios a Identidad (`docker compose restart`
no relee el `.env`), y la prueba se envía con
`docker compose exec identity python manage.py enviar_correo_prueba --para tu.casilla@duocuc.cl`.
Esas claves nunca se suben al repositorio.

### Programador de tareas

El contenedor `tut_programador` usa la imagen de Tutorías y no publica
puertos. Al arrancar, y después cada 300 segundos, corre
`sincronizar_copias` (HU-19) y después `cerrar_y_expirar` (HU-29), cada uno en
su propio proceso: si uno falla, el otro corre igual. Cada comando deja su
fila en la tabla `ejecucion_tarea` de `tutoring_db`; el programador no escribe
en ella.

```bash
docker compose logs -f programador                                # lo que corrió y cómo terminó
docker compose exec programador python manage.py cerrar_y_expirar # correr un comando a mano, por ejemplo antes de mostrar algo en la demo
docker compose up -d --build                                      # después de cambiar el código de Tutorías: vuelve a crear el programador con la imagen nueva
docker compose up -d --force-recreate programador                 # si no lo volvió a crear
```

## Integrantes del equipo con sus roles

| Integrante       | Autor en Git  | Rol en Scrum                                                    | Responsabilidades                                                                                                                                                                                                                                                   |
| ---------------- | ------------- | --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Bryan Bacchi     | `Bacchi701`   | Líder del proyecto: Scrum Master, Product Owner y desarrollador | Dueño de los servicios de Identidad (con los avisos por correo) y Pagos. Responsable de la infraestructura: contenedores, gateway, correo de desarrollo e integración continua. Coordina al equipo, consolida la documentación y es el interlocutor con el docente. |
| Francisco Tejeda | `cacot12`     | Equipo de desarrollo                                            | Dueño del Catálogo académico y la carga de mallas, del módulo de evaluaciones y reputación, y del panel de administración. Es el segundo responsable de infraestructura.                                                  |
| Damaris Iriarte  | `Damaris2023` | Equipo de desarrollo                                            | Dueña del servicio de Tutorías: perfiles de tutor, disponibilidad, búsqueda, reservas y cancelaciones. Responsable del sistema visual del frontend.                                                                                                                 |

Cada integrante es dueño de sus servicios de punta a punta (modelo de datos,
API, pruebas y pantallas), y cada servicio tiene un segundo responsable que
sabe levantarlo y revisarlo: Damaris en Identidad y Pagos, Bryan en Catálogo y
evaluaciones, y Francisco en Tutorías e infraestructura. Con tres integrantes,
los roles de Scrum Master y Product Owner se concentran en el líder, y así
queda escrito.

Hubo excepciones a ese reparto. Por la reasignación del 30-09, la primera
versión de HU-06, HU-07, HU-08, HU-09 y HU-12 la hizo Bryan (PR #10, #6, #7, #12
y #9), y Francisco agregó a la de HU-12 la columna `area`, su filtro y la
paginación (sus commits del 08-10, dentro del PR #9). En el Sprint 3, para
equilibrar la carga, Francisco tomó la búsqueda de tutores (HU-20), que es de
Tutorías, como excepción registrada el 21-10. Damaris hizo la parte de Tutorías
del criterio 1 de HU-17, que es de Bryan: la verificación del token (PR #15,
registrada en SCRUM-43). Bryan hizo las mejoras que salieron de la revisión de
la plataforma con el equipo (HU-38 a HU-41). La declaración de asignaturas
(HU-14) está en Jira a nombre de Francisco; la implementó Bryan en el PR #21.
HU-30 y HU-34 están a nombre de Bryan en Jira: la replanificación del 25-09
propuso el cambio «a acordar con el equipo», y no hay un acuerdo escrito. El
historial y la pantalla de evaluación (HU-26) están en Jira a nombre de
Francisco; el PR #40 lo abrió Bryan. Francisco hizo en el PR #29 la primera
ruta `/internal` de Identidad y la clave de servicio (`CLAVE_SERVICIO`).

## Metodología de trabajo del equipo: Scrum

El equipo trabaja con Scrum, adaptado a tres personas.

- **Sprints de dos semanas.** Cuatro sprints, del 21-09 al 08-11 (el último
  dura una semana), precedidos por una semana de planificación y una de
  cimientos. El 25-09 el equipo fijó el 08-11 como término del desarrollo, y
  el plan pasó de cinco sprints a cuatro. El desarrollo siguió después del
  08-11: el último PR de las historias del MVP entró el 10-11, y el Sprint 4
  se cerró en Jira el 11-11.
- **Product Backlog.** El alcance se priorizó con MoSCoW. El bloque Must, que
  es el MVP, se descompuso en 37 historias de usuario (13 de ellas técnicas),
  estimadas en horas (355 h en total) y agrupadas en nueve épicas. Los Should
  entran de a uno, y solo si la velocidad medida deja espacio.
- **Cierre de sprint.** El plan prevé, cada dos semanas, un cierre de 90
  minutos: Sprint Review, en la que cada dueño de servicio demuestra lo suyo
  funcionando; retrospectiva; reporte al docente, y Sprint Planning del sprint
  siguiente, sobre las horas que cada integrante declara. También prevé
  congelar, al abrir cada sprint, los contratos de la API que ese sprint va a
  usar. Lo que consta: la Sprint Review del Sprint 1 y la planificación del
  Sprint 2, previstas para el 05-10, no se hicieron; la retrospectiva del
  Sprint 1, convocada para la misma llamada, la hizo Bryan solo (S1_7 y
  evidencia A21 del informe de avance). De las Sprint Review y las
  retrospectivas de los Sprints 2 y 3 no hay registro. El Sprint 3 se planificó
  en Jira el 23-10, y el Sprint 4, el 02-11. La revisión y la retrospectiva
  del Sprint 4 van en la semana 15 (16 al 21-11).
- **Seguimiento en Jira.** Desde el Sprint 2, por pedido del profesor, el
  backlog, el sprint y el Daily están en Jira (proyecto «Tutorias», clave
  SCRUM). El Daily es escrito: la regla es que cada integrante deje un
  comentario por día en la tarea del Daily de cada sprint (SCRUM-51 en el
  Sprint 2, SCRUM-69 en el Sprint 3 y SCRUM-78 en el Sprint 4), con lo que
  hizo, lo que hará y sus bloqueos. En el Sprint 2 constan cinco reportes: dos
  comentarios en SCRUM-51 (Damaris, 07-10; Bryan, 09-10) y tres tareas sueltas
  de Damaris (SCRUM-64, 65 y 66, del 05 y el 07-10). En el Sprint 3 no hay
  ninguno. En el Sprint 4, SCRUM-78 tiene el de Bryan del 02-11. En Jira, las
  horas de cada historia son la estimación, y las horas trabajadas no se
  registran. Las planillas de cada sprint (S1_2 a S4_2, en el Listado de
  documentos) usan esa estimación para comparar las horas comprometidas con
  las de las historias terminadas.
- **Definición de Listo (Definition of Done).** Una historia está terminada
  cuando cumple su criterio de aceptación sobre el sistema levantado, tiene
  pruebas automáticas de sus reglas de negocio, la integración continua está
  en verde, otro integrante la aprobó, el contrato en `docs/api` refleja la API
  real, el sistema se levanta desde un clon limpio y la historia está fusionada
  a `develop`.

El plan por etapas, con el objetivo con que se planificó cada sprint:

| Etapa         | Fechas         | Objetivo                                                                        |
| ------------- | -------------- | ------------------------------------------------------------------------------- |
| Planificación | 07 al 13-09    | Cinco pilares de planificación, repositorio y primeras maquetas                 |
| Cimientos     | 14 al 20-09    | El sistema completo se levanta con un comando                                   |
| Sprint 1      | 21-09 al 04-10 | Registro, verificación de correo e inicio de sesión, sobre la base del frontend |
| Sprint 2      | 05 al 18-10    | Cerrar lo abierto del Sprint 1 (PR #5 a #12), el contrato de Identidad (HU-03) y la carga del catálogo; si alcanzaba, perfil y declaración de asignaturas |
| Sprint 3      | 19-10 al 01-11 | El flujo de reservas: declarar asignaturas, solicitar, confirmar o rechazar y pago simulado, más 3 a 5 carreras reales |
| Sprint 4      | 02 al 08-11    | Lo que queda del MVP: solicitar, confirmar o rechazar una tutoría con avisos por correo, pago simulado, cancelación con reembolso, cierre y expiración automáticos, evaluaciones, panel de administración, carreras reales, sistema visual y pruebas de extremo a extremo; el desarrollo se congela el 08-11 |
| Cierre        | 09 al 21-11    | Informe final y ensayo de la demostración                                       |

El 23-10 el Sprint 3 se reenfocó en el flujo de reservas, y lo demás pasó al
Sprint 4. En la semana del 26-10 el equipo revisó la plataforma funcionando y
agregó siete historias al backlog (HU-38 a HU-44); las cuatro primeras
entraron al Sprint 3. El cierre del Sprint 4 está en «Estado del desarrollo».

**Flujo en Git (GitFlow reducido).** `develop` integra el trabajo del sprint.
Cada historia nace de `develop` en una rama corta (por ejemplo,
`feat/HU-04-registro-usuario`) y vuelve por Pull Request, con la integración
continua en verde y la aprobación de otro integrante. Según el plan, `main`
guarda la última versión presentable y recibe `develop` al cierre de cada
sprint, con su etiqueta: v0.1 el 04-10, v0.2 el 18-10, v0.3 el 01-11 y v1.0 el
08-11. Al 13-11 no se ha hecho: `main` sigue en el prototipo del 12-09
(`b8a21f3`), sin ninguna fusión de `develop`, y no hay etiquetas. Al cierre va
un PR de `develop` a `main`, con la etiqueta v1.0.

## Arquitectura de la solución

Arquitectura de microservicios: cuatro servicios en Django REST Framework
detrás de un API Gateway en Nginx, cada uno con su propia base de datos
PostgreSQL, todo orquestado con Docker Compose.

```mermaid
flowchart TB
    cliente["Navegador · páginas HTML, CSS y JavaScript"]
    gateway["API Gateway · Nginx<br/>único punto de entrada: 8080"]
    cliente -->|"páginas en /app/ y JSON en /api/"| gateway

    subgraph red["Microservicios en la red interna de Docker"]
        identity["Identidad<br/>Django REST"]
        catalog["Catálogo académico<br/>Django REST"]
        tutoring["Tutorías<br/>Django REST"]
        payments["Pagos<br/>Django REST"]
        identity_db[("identity_db")]
        catalog_db[("catalog_db")]
        tutoring_db[("tutoring_db")]
        payment_db[("payment_db")]
    end

    subgraph apoyo["Componentes de apoyo"]
        mailpit["Mailpit<br/>correo de desarrollo"]
        programador["Programador de tareas<br/>cada 5 minutos"]
    end

    gateway -->|"/api/identity"| identity
    gateway -->|"/api/catalog"| catalog
    gateway -->|"/api/tutoring"| tutoring
    gateway -->|"/api/payments"| payments

    identity --> identity_db
    catalog --> catalog_db
    tutoring --> tutoring_db
    payments --> payment_db

    tutoring -.->|"1"| catalog
    tutoring -.->|"2"| identity
    payments -.->|"3"| tutoring
    tutoring -.->|"4"| payments
    identity -.->|"envía los correos"| mailpit
    programador -.->|"ejecuta el comando"| tutoring
```

El diagrama muestra el MVP completo. Las páginas del frontend las sirve el
propio gateway en `/app/` (la alternativa de AD-12), y el programador de tareas es
el contenedor `tut_programador` (HU-37). Las flechas continuas son el tráfico del cliente, que siempre entra
por el gateway, y el acceso de cada servicio a su propia base. Las punteadas
son llamadas internas por la red privada:

| N.º | Llamada              | Para qué                                                                |
| --- | -------------------- | ----------------------------------------------------------------------- |
| 1   | Tutorías → Catálogo  | Valida la asignatura contra la malla y el nivel del usuario (RN-01).    |
| 2   | Tutorías → Identidad | Obtiene los datos del usuario y pide el envío de los avisos por correo. |
| 3   | Pagos → Tutorías     | Consulta la reserva y avisa el resultado del pago.                      |
| 4   | Tutorías → Pagos     | Pide el reembolso al cancelar una reserva pagada.                       |

Qué hace cada servicio:

| Servicio           | Prefijo            | Responsabilidad                                                                                                                           | Base de datos |
| ------------------ | ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- | ------------- |
| Identidad          | `/api/identity/v1` | Registro, verificación del correo institucional, sesión y tokens, datos del usuario, marca de administrador y envío de todos los correos. | `identity_db` |
| Catálogo académico | `/api/catalog/v1`  | Carreras, sedes, mallas, semestres, asignaturas y prerrequisitos; búsqueda de asignaturas e importación desde CSV.                        | `catalog_db`  |
| Tutorías           | `/api/tutoring/v1` | Perfiles de tutor y tarifas, disponibilidad, búsqueda de tutores, reservas y su ciclo de vida, evaluaciones y reputación.                 | `tutoring_db` |
| Pagos              | `/api/payments/v1` | Pago simulado de una reserva, su estado y el reembolso. Es un componente desactivable.                                                    | `payment_db`  |

Decisiones que sostienen el diseño:

- **Un solo punto de entrada.** El gateway es el único componente del sistema
  que publica un puerto (8080). Los servicios y las bases viven en una red
  interna de Docker y no son alcanzables desde fuera; la bandeja de correo de
  desarrollo abre otro puerto, solo en 127.0.0.1.
- **Cada servicio es dueño de sus datos.** Ninguno consulta la base de otro;
  todo cruce ocurre por la API REST del servicio dueño del dato.
- **Comunicación síncrona REST con JSON.** Hay cuatro llamadas entre
  servicios, numeradas en el diagrama, todas por la red interna de Docker y
  con 3 segundos de espera: si el otro servicio no responde, la petición
  termina en un 503 que dice cuál falló.
  - Cuando los datos son del propio usuario, se usan las rutas públicas. Para
    declarar una asignatura (HU-14) y poner al día la copia de sus datos
    (HU-41), Tutorías le pide a Identidad `GET /yo` con el mismo token del
    usuario, y a Catálogo la malla de su carrera, que es pública (llamadas 1
    y 2).
  - Lo que necesita datos de otro usuario (los avisos por correo de HU-16 y
    HU-21, y las cuentas que sincroniza HU-19) y las llamadas 3 y 4, entre
    Pagos y Tutorías (HU-23 y HU-28), van por rutas `/internal`, que no pasan
    por el gateway, no llevan el token del usuario y se autentican con una
    clave de servicio en una cabecera. Catálogo no tiene rutas internas (el
    criterio 4 de HU-12 quedó fuera del alcance): Tutorías le pide la malla y
    las asignaturas por sus rutas públicas.
- **Autenticación distribuida.** Solo Identidad emite los tokens JWT: los firma
  con RS256 y su clave privada. Los tres servicios con rutas que piden sesión,
  Identidad, Tutorías y Pagos, verifican la firma con la clave pública.
  Catálogo es de solo lectura y no pide token.
- **Copias de lectura.** Tutorías guarda una copia de los datos del usuario y
  de la asignatura que necesita para resolver la búsqueda de tutores sin una
  llamada HTTP por resultado. Se acepta consistencia eventual: la copia del
  usuario se pone al día cuando abre o guarda «Mi perfil» o declara una
  asignatura, y el programador de tareas refresca las demás.
- **Componentes de apoyo.** Mailpit recibe los correos en desarrollo sin
  enviarlos a personas reales, y el programador de tareas ejecuta cada cinco
  minutos los comandos de Tutorías que cierran reservas, expiran solicitudes y
  sincronizan las copias de lectura.

Las decisiones de arquitectura con sus alternativas, los contratos de interfaz
y el modelo de datos completo están en el Pilar 2 y su anexo A, en
[`docs/planificacion/`](docs/planificacion/). Los diagramas entidad-relación
de las cuatro bases, con el modelo implementado (la revisión de normalización
del 30 de septiembre y la columna `area` de HU-12), están en
[`docs/diagramas/`](docs/diagramas/).

## Estructura del repositorio

```text
Fase 1/              evidencias de la Fase 1 del Capstone (grupales e individuales)
Fase 2/              evidencias de la Fase 2: individuales, grupales y del proyecto
.github/workflows/   canal de integración continua
docs/planificacion/  los cinco pilares, el anexo A (modelo de datos) y la idea base del proyecto
docs/diagramas/      diagramas con su fuente: entidad-relación de las cuatro bases, componentes (UML), estados de la reserva, cronograma, carta Gantt y mapa de historias
docs/api/            contratos OpenAPI de los cuatro servicios
docs/adr/            dónde están las decisiones de arquitectura (Pilar 2 y anexo A)
docs/evidencia/      presentación del 30-10, cobertura de las pruebas y corrida de extremo a extremo
infra/nginx/         configuración del gateway y página de estado
infra/postgres/      reservada para scripts de inicialización de PostgreSQL; sin uso (solo .gitkeep)
services/            identity, catalog, tutoring y payments, cada uno con su Dockerfile; las carreras reales, en catalog/datos_catalogo/
data/seeds/demo/     datos de ejemplo de las cuatro bases y la prueba de sus restricciones
data/seeds/carga/    los 500 usuarios de prueba de la medición de RNF-02
pruebas_e2e/         pruebas de extremo a extremo contra el sistema levantado (HU-34)
keys/                clave pública de firma de tokens (la privada no se versiona)
scripts/             levantar la demo, cargar los datos de ejemplo y los usuarios de prueba, y probar las restricciones
frontend/            páginas del frontend (HTML, CSS y JavaScript), servidas en /app/
docker-compose.yml   levanta el sistema completo
pyproject.toml       configuración de ruff y black
requirements-dev.txt herramientas de prueba y de estilo (pytest, pytest-django, pytest-cov, black y ruff)
.env.example         variables de entorno de ejemplo, sin secretos
```

## Estado del desarrollo

Al 13-11-2026, con `develop` en `db6192d` (PR #58). Todas las historias de
desarrollo del MVP están integradas, y el Sprint 4 se cerró en Jira el
11-11; no queda ningún sprint abierto.

- **Historias del MVP:** 36 de 37 terminadas. Falta HU-32, la del cierre: el
  ensayo de la demostración y la documentación final.
- **Sprint 4 (02 al 08-11):** el desarrollo siguió después del 08-11, y el
  último PR de las historias del MVP, el #57, entró a `develop` el 10-11. Al
  cerrar el sprint, el 11-11, 23 de sus 24 historias estaban terminadas.
  HU-07, la carga del catálogo desde CSV, pasó a «Finalizada» en Jira el
  12-11, ya fuera del sprint.
- **Decisiones del Product Owner al cierre:**
  - HU-12: el criterio 4, las rutas internas de Catálogo, queda fuera del
    alcance. Desde el PR #21, Tutorías valida RN-01 con la malla pública.
  - HU-33: el catálogo se maneja con la carga desde CSV (HU-07 y HU-13), sin
    una sección en el panel. Importarlo desde el panel (RF-16, Should) queda
    fuera del MVP.
  - HU-36: el reembolso que no se vuelve a intentar cuando Pagos no responde
    queda como limitación conocida.
  - SCRUM-79, el 13-11 (PR #58): el nivel del perfil va de 1 a 8, porque
    ninguna de las 23 mallas reales pasa del semestre 8. La base de datos
    sigue admitiendo de 1 a 12.
- **Catálogo:** 23 carreras reales de Duoc UC con su malla 2026, transcritas de
  las mallas oficiales (`services/catalog/datos_catalogo/LEEME.md`). Diez
  llegan al semestre 8, doce al 5 y una al 4.
- **Mediciones del 09-11** (`docs/evidencia/`):
  - Pruebas: 185 de Identidad, 39 de Catálogo (más 17 saltadas), 576 de
    Tutorías, 129 de Pagos y 18 de extremo a extremo.
  - Cobertura, primero como la mide la integración continua y después sin las
    pruebas ni las migraciones: Identidad 99 % y 96 %, Catálogo 81 % y 87 %,
    Tutorías 99 % y 98 %, y Pagos 98 % y 96 %. Desde el PR #57, la integración
    continua exige 60 % en Identidad y en Tutorías.
  - La búsqueda de tutores, con 510 cuentas, respondió en 62,5 ms como máximo.
    RNF-02 pide menos de 2 segundos.
- **Pull Requests:** hasta el cierre del Sprint 4 se integraron 56 a `develop`,
  del #1 al #57; el #49, una reversión, no se fusionó. Después entró el #58,
  de SCRUM-79.
- **Fuera del MVP, en el backlog:** el buzón de avisos (HU-42) y recuperar la
  contraseña (HU-43), que son Should; declarar asignaturas cursadas con
  evidencia (HU-44), que es Could, y el pago con Mercado Pago en modo de prueba
  (SCRUM-70, RF-18, Could).
- **Limitaciones conocidas:**
  - Si Pagos no responde al cancelar una tutoría pagada, el reembolso no se
    vuelve a intentar (HU-36).
  - Con las claves JWT mal puestas quedan tres casos que responden 500 en vez
    de 503: en Tutorías y Pagos, una clave pública que no es PEM; en
    Identidad, una clave en binario o las dos claves intercambiadas.
  - La búsqueda de cuentas del panel de administración distingue tildes.
  - El nivel máximo es el mismo para todas las carreras: en una carrera técnica
    también se puede elegir hasta el semestre 8.
  - Como solo se ofrecen asignaturas de semestres anteriores al nivel, y el
    nivel llega a 8, las del semestre 8 ya no se pueden ofrecer, salvo desde
    una cuenta que guardó un nivel de 9 a 12 antes del #58.
  - El frontend no tiene pruebas automáticas: las de extremo a extremo llaman
    a la API por el gateway, no a las páginas.
- **Versiones en `main`:** v0.1, v0.2 y v0.3 no se publicaron. `main` sigue en
  el prototipo del 12-09 (`b8a21f3`), sin etiquetas; al cierre va un PR de
  `develop` a `main` con la etiqueta v1.0.

## Comandos del día a día

```bash
docker compose ps                  # qué hay levantado y cómo está
docker compose logs -f identity    # seguir los registros de un servicio
docker compose logs -f programador # ver qué comandos corrió el programador y cómo terminaron
docker compose restart identity    # reiniciar uno (no relee el .env)
docker compose down                # apagar, conservando los datos
docker compose down -v             # apagar y BORRAR las cuatro bases
docker compose up -d --build       # reconstruir después de cambiar código
docker compose restart gateway     # después de reconstruir: vuelve a encontrar los servicios
```

## Problemas frecuentes

**El puerto 8080 está ocupado** (`port is already allocated`, `address already
in use` u `Only one usage of each socket address`). Otro programa lo está
usando. En tu `.env`, cambia `PUERTO_GATEWAY=8090` y
`URL_FRONTEND=http://localhost:8090/app`, vuelve a levantar y usa 8090 en las
direcciones de este README.

**`port is already allocated` o `bind` en el puerto 8025.** Lo mismo con la
bandeja de correo: cambia `PUERTO_BANDEJA` en tu `.env` a 8026 y vuelve a
levantar. La bandeja queda en <http://localhost:8026>.

**Un servicio queda en `unhealthy`.** Mira sus registros con
`docker compose logs identity`. Casi siempre es una variable que falta en el
`.env`: compara tu archivo con `.env.example`.

**En la demo, el inicio de sesión dice «No existe /app/keys/jwt_private.pem».**
Faltan las claves de los tokens. En Windows, corre el comando de las claves de
«Probar la demo», después `docker compose up -d --force-recreate --wait identity tutoring payments`
y `docker compose restart gateway`. En macOS o Linux, `sh scripts/levantar_demo.sh`
hace todo.

**`localhost:8080` responde 502, o una página dice «No pudimos…», después de
reconstruir un servicio.** El gateway sigue buscando al servicio en su
dirección anterior: `docker compose restart gateway` y recarga la página.

**Al cambiar de página se cerró la sesión.** Pasa si se cambia de página
mientras la anterior todavía renueva la sesión. Espera el «Hola, …» del
encabezado antes de cambiar de página.

**La búsqueda de cuentas del panel no encuentra a alguien.** Busca por nombre
o apellido, no por correo, y distingue las tildes: escribe el nombre como
está, con sus tildes («Matías», no «Matias»).

**El inicio de sesión dice «No se pudo iniciar sesión.» aunque la clave esté
bien.** Si hubo varios intentos seguidos, es el límite del gateway: cinco por
minuto desde el mismo computador. Espera un minuto y vuelve a intentarlo. Si
dice «No existe /app/keys/…», faltan las claves (ver el punto de las claves).

**El computador se queda sin memoria.** Con WSL 2, la memoria que puede usar
Docker se fija en el archivo `%UserProfile%\.wslconfig`: agrega las líneas
`[wsl2]` y `memory=4GB`, ejecuta `wsl --shutdown` y vuelve a abrir Docker
Desktop. En macOS, la memoria se fija en Docker Desktop, en Settings →
Resources. Si aun así no alcanza, está prevista la alternativa de la sección 10
del Pilar 2: una sola instancia de PostgreSQL con cuatro bases y cuatro
usuarios sin permisos cruzados.

## Documentación del proyecto

| Documento                                                                       | Dónde está                                                |
| ------------------------------------------------------------------------------- | --------------------------------------------------------- |
| Planificación en cinco pilares: alcance (Pilar 1, v1.8), arquitectura (Pilar 2, v1.8), equipo (Pilar 3, v1.8), tiempo (Pilar 4, v2.0) y calidad (Pilar 5, v1.6) | [`docs/planificacion/`](docs/planificacion/)              |
| Modelo de datos detallado (anexo A del Pilar 2, v1.6)                           | [`docs/planificacion/`](docs/planificacion/)              |
| Decisiones de arquitectura: AD-01 a AD-15 y las tomadas después del 25-09      | [`docs/adr/README.md`](docs/adr/README.md)                |
| Diagramas entidad-relación de las cuatro bases, con su fuente en Mermaid (`.mmd`) | [`docs/diagramas/`](docs/diagramas/)                      |
| Diagrama UML de componentes (figura 1 del Pilar 2), con su fuente en Graphviz (`06_componentes.dot`) | [`docs/diagramas/06_componentes.png`](docs/diagramas/06_componentes.png) |
| Estados de la reserva (figura 2 del Pilar 2), con su fuente en Graphviz (`10_estados_reserva.dot`) | [`docs/diagramas/10_estados_reserva.png`](docs/diagramas/10_estados_reserva.png) |
| Calendario de la replanificación del 25-09 (figura 4 del Pilar 4), con su fuente en Python (`07_cronograma.py`) | [`docs/diagramas/07_cronograma.png`](docs/diagramas/07_cronograma.png) |
| Carta Gantt de las 44 historias y SCRUM-70 (figura 5 del Pilar 4), con su fuente en Python (`08_carta_gantt.py`) y sus datos (`08_carta_gantt.csv`) | [`docs/diagramas/08_carta_gantt.png`](docs/diagramas/08_carta_gantt.png) |
| Mapa de historias al 02-11 (figura 2 del documento 10 del Listado), con su fuente en Python (`11_story_map.py`) y sus datos (`11_story_map.csv`) | [`docs/diagramas/11_story_map.png`](docs/diagramas/11_story_map.png) |
| Contratos OpenAPI de los cuatro servicios                                      | [`docs/api/`](docs/api/), al día con cada PR que cambia una API |
| Presentación de la sesión del 30-10 con el profesor, y la cobertura de las pruebas y la corrida de extremo a extremo del 09-11 (el archivo de la corrida lleva la fecha UTC, 10-11) | [`docs/evidencia/`](docs/evidencia/) |
| Videos de la plataforma funcionando, del 16-10 y del 30-10                      | [`Fase 2/Evidencias Proyecto/Evidencias de sistema/Aplicación/`](Fase%202/Evidencias%20Proyecto/Evidencias%20de%20sistema/Aplicaci%C3%B3n/) |
| Revisión de normalización del modelo (30-09) y diagramas entidad-relación      | [`Fase 2/Evidencias Proyecto/Evidencias de sistema/Base de datos/`](Fase%202/Evidencias%20Proyecto/Evidencias%20de%20sistema/Base%20de%20datos/) |
| Evidencias de la Fase 1 del Capstone                                            | [`Fase 1/`](Fase%201/)                                    |
| Evidencias de la Fase 2: Listado de documentos (00 a 08 y 10, v1.1; 09, con datos al 02-11-2026; 11, plantilla v0.2; 12, v1.2), artefactos de los cuatro sprints e informe de avance | [`Fase 2/`](Fase%202/)                                    |
| Backlog priorizado, sprints y Daily                                             | Jira, proyecto «Tutorias» (clave SCRUM), con acceso por invitación |
