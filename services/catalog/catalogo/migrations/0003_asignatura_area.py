from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalogo", "0002_modelo_inicial"),
    ]

    operations = [
        migrations.AddField(
            model_name="asignatura",
            name="area",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
