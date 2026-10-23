# Escrita a mano: habilita pg_trgm antes de crear las tablas, porque el indice
# ix_asignatura_busqueda de 0002_modelo_inicial la necesita (anexo A, seccion 2).
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        TrigramExtension(),
    ]
