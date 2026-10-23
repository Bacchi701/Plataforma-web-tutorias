# Escrita a mano: habilita btree_gist antes de crear las tablas, porque la
# restriccion EXCLUDE de bloque_disponibilidad compara usuario_id con "=" dentro
# de un indice GiST (anexo A, seccion 2).
from django.contrib.postgres.operations import BtreeGistExtension
from django.db import migrations


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        BtreeGistExtension(),
    ]
