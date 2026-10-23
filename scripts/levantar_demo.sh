#!/bin/sh
# Levanta la demo de la Plataforma de Tutorias desde un clon nuevo.
#
# Uso, desde la raiz del repositorio (rama develop o main):
#   sh scripts/levantar_demo.sh
# o, si el archivo esta en otra carpeta (por ejemplo, Descargas):
#   sh ~/Downloads/levantar_demo.sh
#
# Sirve en macOS, en Linux y en Git Bash de Windows. Necesita Docker Desktop
# abierto. Se puede repetir: no vuelve a generar las claves si ya existen y
# recarga los datos de ejemplo (todos ficticios).

set -e
# Git Bash de Windows: que no convierta rutas como /claves o /tmp.
export MSYS_NO_PATHCONV=1

# Se corre desde la carpeta del repositorio, o desde su carpeta scripts/.
if [ -f docker-compose.yml ]; then
  :
elif [ -f "$(dirname "$0")/../docker-compose.yml" ]; then
  cd "$(dirname "$0")/.."
else
  echo "Corre este script desde la carpeta del repositorio."
  exit 1
fi

if [ ! -f data/seeds/demo/identity.sql ]; then
  echo "No encuentro los datos de ejemplo en data/seeds/demo. Actualiza la rama con: git switch develop y git pull"
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker no responde. Abre Docker Desktop, espera a que diga que esta corriendo y vuelve a intentarlo."
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "== .env creado desde .env.example"
elif ! grep -q '^URL_FRONTEND=' .env; then
  { echo ""; grep -E '^(URL_FRONTEND|COOKIE_REFRESH_SEGURA)=' .env.example; } >> .env
  echo "== Se agregaron a .env las variables de la sesion"
fi

# Safari no guarda cookies Secure en http://localhost (WebKit, bug 232088), y sin
# esa cookie la portada no recupera la sesion. En macOS la cookie va sin Secure;
# solo cambia el .env de este clon, que no se sube al repositorio.
if [ "$(uname -s)" = "Darwin" ] && grep -q '^COOKIE_REFRESH_SEGURA=1' .env; then
  sed 's/^COOKIE_REFRESH_SEGURA=1/COOKIE_REFRESH_SEGURA=0/' .env > .env.tmp && mv .env.tmp .env
  echo "== macOS: la cookie de renovacion va sin Secure, para que Safari la guarde en localhost"
fi

echo "== Construyendo Identidad (la primera vez tarda unos minutos)"
docker compose build identity

if [ -f keys/jwt_private.pem ]; then
  echo "== Las claves de los tokens ya existen en keys/: se usan esas"
else
  echo "== Generando las claves de los tokens en keys/"
  # Git Bash entrega la ruta como C:/...; macOS y Linux, como /Users/... o /home/...
  RAIZ=$(pwd -W 2>/dev/null || pwd)
  docker compose run --rm -T --no-deps -v "$RAIZ/keys:/claves" --entrypoint python identity manage.py generar_claves_jwt --carpeta /claves
fi

echo "== Levantando el sistema (la primera vez descarga y construye las imagenes)"
docker compose up -d --build --wait
# Identidad vuelve a leer las claves recien generadas, y el gateway vuelve a
# buscar a Identidad, por si el contenedor nuevo quedo con otra direccion.
docker compose up -d --force-recreate --wait identity
docker compose restart gateway

for par in identity_db:identity.sql catalog_db:catalog.sql tutoring_db:tutoring.sql payment_db:payments.sql; do
  servicio=${par%%:*}
  archivo=${par##*:}
  if [ ! -f "data/seeds/demo/$archivo" ]; then
    echo "-- data/seeds/demo/$archivo no esta en esta rama: se omite"
    continue
  fi
  echo "== $servicio  <-  data/seeds/demo/$archivo"
  docker compose cp "data/seeds/demo/$archivo" "$servicio:/tmp/$archivo"
  docker compose exec -T "$servicio" sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -v ON_ERROR_STOP=1 -q -f /tmp/$archivo" || {
    echo "Fallo la carga de $archivo: copia el error de arriba."
    exit 1
  }
done

echo ""
echo "Listo. Abre en el navegador:"
echo "  Estado de los servicios:  http://localhost:8080/"
echo "  Asignaturas y mallas:     http://localhost:8080/app/asignaturas.html"
echo "  Registro (@duocuc.cl):    http://localhost:8080/app/registro.html"
echo "  Bandeja de correo:        http://localhost:8025"
echo "  Inicio de sesion:         http://localhost:8080/app/login.html"
echo ""
echo "Cuentas de ejemplo, todas con la clave Tutorias2026:"
echo "  valentina.demo@duocuc.cl  verificada: entra"
echo "  tomas.demo@duocuc.cl      sin verificar: no puede entrar"
echo "  josefa.demo@duocuc.cl     desactivada"
echo ""
echo "Para apagar: docker compose down"
