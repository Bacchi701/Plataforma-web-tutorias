import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "clave-de-desarrollo")
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "rest_framework",
    "salud",
    "correo",
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

# El esqueleto no autentica todavia.
# La validacion del token con la clave publica llega con HU-05 y ahi se reemplaza esto
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
}

LANGUAGE_CODE = "es-cl"
# Se almacena en UTC y se convierte a hora de Chile en el cliente (Pilar 2, seccion 11)
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------- Correo (HU-02, AD-11) ----------
# Identidad es el unico servicio que envia correos. En desarrollo y en la
# demostracion todo cae en la bandeja de Mailpit y nada sale a internet.
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("EMAIL_HOST", "mailpit")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "1025"))
# Mailpit no pide usuario ni cifrado. Un servidor real si los pediria, y ahi
# se agregan EMAIL_HOST_USER, EMAIL_HOST_PASSWORD y EMAIL_USE_TLS.
EMAIL_USE_TLS = False
# Sin este limite, si la bandeja esta caida, la peticion que envia el correo
# queda colgada hasta que el gateway la corta a los 30 segundos.
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = "Plataforma de Tutorías <no-responder@tutorias.test>"
