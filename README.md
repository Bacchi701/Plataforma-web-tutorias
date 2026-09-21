# Plataforma de Tutorias entre Estudiantes

Plataforma web que conecta a estudiantes de Duoc UC que necesitan apoyo
academico con companeros que dominan determinadas asignaturas.

Portafolio de Titulo - Ingenieria en Informatica - Duoc UC - 2026

## Que necesitas antes de empezar

| Herramienta    | Version minima | Como comprobarlo         |
|----------------|----------------|--------------------------|
| Git            | 2.40           | `git --version`          |
| Docker Desktop | 4.30           | `docker --version`       |
| Docker Compose | 2.27           | `docker compose version` |

En Windows, Docker Desktop necesita WSL 2 activado. El sistema completo usa
alrededor de 3 GB de memoria; si tu equipo tiene 8 GB, cierra el navegador
mientras lo levantas la primera vez.

## Levantar el sistema

```bash
git clone https://github.com/Bacchi701/Plataforma-web-tutorias.git
cd Plataforma-web-tutorias
cp .env.example .env          # PowerShell: Copy-Item .env.example .env
docker compose up -d --build
```

La primera vez tarda entre 3 y 6 minutos porque construye las imagenes.
Las siguientes, menos de un minuto.

## Comprobar que esta arriba

Abre <http://localhost:8080>: la pagina muestra los cuatro servicios con su
estado. Uno por uno:

| Servicio           | URL                                            |
|--------------------|------------------------------------------------|
| Identidad          | <http://localhost:8080/api/identity/v1/estado> |
| Catalogo academico | <http://localhost:8080/api/catalog/v1/estado>  |
| Tutorias           | <http://localhost:8080/api/tutoring/v1/estado> |
| Pagos              | <http://localhost:8080/api/payments/v1/estado> |

Cada uno responde algo asi:

```json
{"servicio": "identity", "estado": "ok", "base_de_datos": "ok", "version": "0.1.0"}
```

Ningun servicio ni base de datos publica un puerto al equipo: el puerto 8080
del gateway es la unica puerta de entrada, y esa es justamente la condicion
del criterio de aceptacion CA8.

## Comandos del dia a dia

```bash
docker compose ps                  # que hay levantado y como esta
docker compose logs -f identity    # seguir los registros de un servicio
docker compose restart identity    # reiniciar solo uno
docker compose down                # apagar, conservando los datos
docker compose down -v             # apagar y BORRAR las cuatro bases
docker compose up -d --build       # reconstruir despues de cambiar codigo
```

## Estructura

```
.github/workflows/   canal de integracion continua
docs/                contratos OpenAPI, planificacion, evidencia, diagramas
infra/nginx/         configuracion del gateway
services/            identity, catalog, tutoring, payments
data/seeds/          carreras.csv y asignaturas.csv
keys/               clave publica de firma (la privada no se versiona)
scripts/             carga del catalogo y sincronizacion de copias
```

## Que todavia no esta

Los cuatro servicios responden unicamente su endpoint de estado. El correo
de desarrollo y el programador de tareas llegan con HU-02 y HU-37, el
frontend en React con HU-06, y el registro de usuarios con HU-04.

## Problemas frecuentes

**`bind: address already in use` en el puerto 8080.** Otro programa lo esta
ocupando. Cambia `PUERTO_GATEWAY` en tu `.env` a 8090 y vuelve a levantar.

**`exec ./entrada.sh: no such file or directory`.** El archivo quedo con
finales de linea de Windows. Comprueba que `.gitattributes` esta en la raiz,
y vuelve a clonar el repositorio en una carpeta nueva.

**Un servicio queda en `unhealthy`.** Mira sus registros con
`docker compose logs identity`. Casi siempre es una variable que falta en el
`.env`: compara tu archivo con `.env.example`.

**El equipo se queda sin memoria.** Sube el limite en Docker Desktop, en
Settings > Resources, a 4 GB. Si aun asi no alcanza, esta prevista la
alternativa de la seccion 10 del Pilar 2: una sola instancia de PostgreSQL
con cuatro bases y cuatro usuarios sin permisos cruzados.

## Documentacion del proyecto

Los cinco pilares de la planificacion estan en `docs/planificacion/`.
