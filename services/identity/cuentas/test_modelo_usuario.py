import pytest
from django.db import IntegrityError, connection, transaction

from .models import Usuario

CLAVE = "clave-de-prueba-123"


def crear_usuario(email="ana.demo@duocuc.cl", **campos):
    campos.setdefault("nombre", "Ana")
    campos.setdefault("apellido", "Demo")
    return Usuario.objects.create_user(email, CLAVE, **campos)


@pytest.mark.django_db
def test_identity_db_tiene_solo_las_tablas_del_anexo():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        )
        tablas = {fila[0] for fila in cursor.fetchall()}

    assert tablas == {
        "usuario",
        "token_verificacion",
        "refresh_token",
        "aviso_correo",
        "django_migrations",
    }


@pytest.mark.django_db
def test_la_clave_se_guarda_como_hash_y_nunca_en_claro():
    usuario = crear_usuario()

    with connection.cursor() as cursor:
        cursor.execute("SELECT password_hash FROM usuario WHERE id = %s", [usuario.id])
        guardado = cursor.fetchone()[0]

    assert guardado.startswith("pbkdf2_sha256$")
    assert CLAVE not in guardado
    assert usuario.check_password(CLAVE)


@pytest.mark.django_db
def test_el_correo_debe_ser_institucional():
    with pytest.raises(IntegrityError), transaction.atomic():
        crear_usuario(email="ana.demo@gmail.com")


@pytest.mark.django_db
def test_no_se_repite_un_correo_aunque_cambien_las_mayusculas():
    crear_usuario(email="ana.demo@duocuc.cl")

    # create() no pasa por la normalizacion de create_user: asi se prueba que
    # la regla la sostiene la base (ux_usuario_email), no el codigo.
    with pytest.raises(IntegrityError), transaction.atomic():
        Usuario.objects.create(
            email="Ana.Demo@DUOCUC.cl", nombre="Ana", apellido="Otra", password="x"
        )


@pytest.mark.django_db
def test_el_nivel_va_de_1_a_12():
    with pytest.raises(IntegrityError), transaction.atomic():
        crear_usuario(nivel=13)
