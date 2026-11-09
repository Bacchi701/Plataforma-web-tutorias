#!/bin/sh
# Carga 500 usuarios de prueba FICTICIOS en identity_db y tutoring_db, para
# medir la busqueda de tutores (HU-34, RNF-02).
#
# Uso, desde la raiz del repositorio, con el sistema levantado y despues de
# cargar los datos de ejemplo (sh scripts/levantar_demo.sh):
#   sh scripts/cargar_usuarios_prueba.sh
#
# Sirve en macOS, en Linux y en Git Bash de Windows. Se puede repetir las veces
# que haga falta: cada archivo borra la carga anterior, y solo esa, y la vuelve
# a crear. Volver a cargar los datos de ejemplo borra esta carga. Las cuentas
# son carga.001 a carga.500@duocuc.cl, todas con la clave Tutorias2026.

set -e
# Git Bash de Windows: que no convierta rutas como /tmp.
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

for par in identity_db:identity.sql tutoring_db:tutoring.sql; do
  servicio=${par%%:*}
  archivo=${par##*:}
  if [ ! -f "data/seeds/carga/$archivo" ]; then
    echo "No encuentro data/seeds/carga/$archivo en esta rama."
    exit 1
  fi
  echo "== $servicio  <-  data/seeds/carga/$archivo"
  docker compose cp "data/seeds/carga/$archivo" "$servicio:/tmp/carga_$archivo" || {
    echo "No se pudo copiar data/seeds/carga/$archivo. Esta levantado $servicio? (docker compose ps)"
    exit 1
  }
  docker compose exec -T "$servicio" sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -v ON_ERROR_STOP=1 -q -f /tmp/carga_$archivo" || {
    echo "Fallo la carga de $archivo: copia el error de arriba."
    exit 1
  }
done

echo ""
echo "Listo: 500 usuarios de prueba cargados (carga.001 a carga.500@duocuc.cl, clave Tutorias2026)."
