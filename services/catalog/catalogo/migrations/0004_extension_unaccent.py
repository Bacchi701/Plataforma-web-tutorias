# Escrita a mano (SCRUM-56): habilita la extension unaccent para que la
# busqueda de asignaturas por nombre o sigla no distinga tildes.
from django.contrib.postgres.operations import UnaccentExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("catalogo", "0003_asignatura_area"),
    ]

    operations = [
        UnaccentExtension(),
    ]
