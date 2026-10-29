import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "clave-de-desarrollo")
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

# Sin django.contrib.auth ni contenttypes: los usuarios viven en Identidad, y
# asi tutoring_db queda solo con las tablas del anexo A mas django_migrations.
# django.contrib.postgres no crea tablas: es la app de Django para lo propio de
# PostgreSQL que usa este modelo (la restriccion EXCLUDE sobre rangos).
INSTALLED_APPS = [
    "django.contrib.postgres",
    "rest_framework",
    "salud",
    "tutorias",
]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "configuracion.urls"
WSGI_APPLICATION = "configuracion.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ["POSTGRES_USER"],
        "PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "HOST": os.environ["POSTGRES_HOST"],
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

# Tutorias no emite tokens: verifica con la clave publica el token de acceso
# que firma Identidad (HU-17). Una peticion sin token sigue sin usuario; las
# vistas que piden sesion usan IsAuthenticated, que en ese caso responde 401.
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": ["tutorias.autenticacion.TokenDeAcceso"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    # Sin django.contrib.auth no existe AnonymousUser: una peticion sin
    # token queda con request.user = None.
    "UNAUTHENTICATED_USER": None,
    # Formato de error unico: codigo, mensaje y detalles (Pilar 2, seccion 11).
    "EXCEPTION_HANDLER": "configuracion.errores.formato_uniforme",
}

LANGUAGE_CODE = "es-cl"
# Se almacena en UTC y se convierte a hora de Chile en el cliente (Pilar 2, seccion 11)
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------- Token de acceso (HU-17, AD-06) ----------
# Tutorias solo verifica: recibe la clave publica, que se versiona en keys/ y
# docker-compose.yml monta en /app/keys. La privada vive solo en Identidad
# (Pilar 2, seccion 10).
JWT_CLAVE_PUBLICA = os.environ.get(
    "JWT_CLAVE_PUBLICA", str(BASE_DIR / "keys" / "jwt_public.pem")
)
JWT_EMISOR = "identity"

# ---------- Consultas a Identidad y a Catalogo (HU-14, HU-41) ----------
# Direcciones dentro de la red de Docker (tutorias/llamadas.py). Tutorias pide
# GET /yo a Identidad con el mismo token de la peticion, y la malla de una
# carrera a Catalogo, que es publica: ninguna de las dos necesita una clave.
URL_IDENTIDAD = os.environ.get("URL_IDENTIDAD", "http://identity:8000")
URL_CATALOGO = os.environ.get("URL_CATALOGO", "http://catalog:8000")
