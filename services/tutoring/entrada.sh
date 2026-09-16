#!/bin/sh
# Arranque del servicio: espera a su base, aplica sus migraciones y levanta
# el servidor. Es identico en los cuatro servicios; lo unico que cambia es
# la variable NOMBRE_SERVICIO, que llega desde docker-compose.yml.
set -e

echo "[$NOMBRE_SERVICIO] esperando a $POSTGRES_HOST..."
intentos=0
until python -c "
import os, sys, psycopg
try:
    psycopg.connect(
        host=os.environ['POSTGRES_HOST'],
        port=os.environ['POSTGRES_PORT'],
        dbname=os.environ['POSTGRES_DB'],
        user=os.environ['POSTGRES_USER'],
        password=os.environ['POSTGRES_PASSWORD'],
        connect_timeout=3,
    ).close()
except Exception:
    sys.exit(1)
" 2>/dev/null
do
    intentos=$((intentos + 1))
    if [ "$intentos" -ge 30 ]; then
        echo "[$NOMBRE_SERVICIO] la base no respondio en 60 segundos" >&2
        exit 1
    fi
    sleep 2
done

echo "[$NOMBRE_SERVICIO] aplicando migraciones"
python manage.py migrate --noinput

echo "[$NOMBRE_SERVICIO] escuchando en el puerto 8000"
exec gunicorn configuracion.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 2 \
    --access-logfile -
