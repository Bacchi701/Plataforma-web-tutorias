import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "clave-de-desarrollo")
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

# Sin django.contrib.auth ni contenttypes: Pagos no conoce usuarios, y asi
# payment_db queda solo con las tablas del anexo A mas django_migrations.
INSTALLED_APPS = [
    "rest_framework",
    "salud",
    "pagos",
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

# Pagos no emite tokens: verifica con la clave publica el token de acceso que
# firma Identidad (HU-17, HU-23), como Tutorias. Una peticion sin token sigue
# sin usuario; las vistas que piden sesion usan IsAuthenticated, que en ese
# caso responde 401.
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": ["pagos.autenticacion.TokenDeAcceso"],
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

# ---------- Token de acceso (HU-17, HU-23, AD-06) ----------
# Pagos solo verifica: recibe la clave publica, que se versiona en keys/ y
# docker-compose.yml monta en /app/keys. La privada vive solo en Identidad
# (Pilar 2, seccion 10).
JWT_CLAVE_PUBLICA = os.environ.get(
    "JWT_CLAVE_PUBLICA", str(BASE_DIR / "keys" / "jwt_public.pem")
)
JWT_EMISOR = "identity"

# ---------- Llamadas a Tutorias (HU-23) ----------
# Direccion de Tutorias dentro de la red de Docker (pagos/llamadas.py). Pagos le
# pide la reserva y le avisa cada cambio del pago por sus rutas /internal, con
# la clave de servicio (Pilar 2, seccion 5.4), la misma en los cuatro servicios.
URL_TUTORIAS = os.environ.get("URL_TUTORIAS", "http://tutoring:8000")
CLAVE_SERVICIO = os.environ.get("CLAVE_SERVICIO", "")
