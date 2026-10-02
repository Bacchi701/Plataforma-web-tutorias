import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "clave-de-desarrollo")
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

# Sin django.contrib.auth ni contenttypes: el usuario es propio (cuentas) y
# asi identity_db queda solo con las tablas del anexo A mas django_migrations.
INSTALLED_APPS = [
    "rest_framework",
    "salud",
    "correo",
    "cuentas",
]

# Debe existir desde la primera migracion de cuentas (T-025).
AUTH_USER_MODEL = "cuentas.Usuario"

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

# ---------- Correo (HU-02, AD-11) ----------
# Identidad es el unico servicio que envia correos. En desarrollo y en la
# demostracion todo cae en la bandeja de Mailpit y nada sale a internet.
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("EMAIL_HOST", "mailpit")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "1025"))
# Mailpit no pide usuario ni cifrado, asi que estas tres van vacias. Se llenan
# en el .env local, sin tocar el codigo, para la unica prueba que la bandeja no
# puede hacer: el envio real a una casilla @duocuc.cl que exige el supuesto
# S-02 del Pilar 5.
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "0") == "1"
# Sin este limite, si la bandeja esta caida, la peticion que envia el correo
# queda colgada hasta que el gateway la corta a los 30 segundos.
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = os.environ.get(
    "CORREO_REMITENTE", "Plataforma de Tutorías <no-responder@tutorias.test>"
)

# ---------- Registro y verificacion del correo (HU-04) ----------
# El enlace del correo apunta a la pagina del frontend que llama a la API.
URL_FRONTEND = os.environ.get("URL_FRONTEND", "http://localhost:8080/app")
VERIFICACION_HORAS = 24
