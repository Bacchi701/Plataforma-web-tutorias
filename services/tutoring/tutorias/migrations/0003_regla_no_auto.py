# Escrita a mano. Se copia DESPUES de generar 0002_modelo_inicial.
#
# ck_reserva_no_auto (RN-03) comparaba dos columnas de reserva. Al quitar
# tutor_usuario_id por la 3FN, el tutor es el dueno del bloque y la regla cruza
# dos tablas, cosa que un CHECK no puede hacer. Un disparador la mantiene en la
# base: la reserva se rechaza con el mismo nombre de restriccion.
from django.db import migrations

FUNCION = """
CREATE FUNCTION reserva_no_auto() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM bloque_disponibilidad AS b
        WHERE b.id = NEW.bloque_id
          AND b.usuario_id = NEW.solicitante_usuario_id
    ) THEN
        RAISE EXCEPTION 'Nadie puede reservar un bloque propio (RN-03)'
            USING ERRCODE = 'check_violation',
                  CONSTRAINT = 'ck_reserva_no_auto',
                  TABLE = 'reserva';
    END IF;
    RETURN NEW;
END;
$$
"""

DISPARADOR = """
CREATE TRIGGER trg_reserva_no_auto
BEFORE INSERT OR UPDATE OF bloque_id, solicitante_usuario_id ON reserva
FOR EACH ROW EXECUTE FUNCTION reserva_no_auto()
"""

BORRAR_DISPARADOR = "DROP TRIGGER IF EXISTS trg_reserva_no_auto ON reserva"
BORRAR_FUNCION = "DROP FUNCTION IF EXISTS reserva_no_auto()"


class Migration(migrations.Migration):
    dependencies = [
        ("tutorias", "0002_modelo_inicial"),
    ]

    operations = [
        # En lista, Django ejecuta cada texto entero, sin partirlo por los ";"
        # que hay dentro del cuerpo de la funcion.
        migrations.RunSQL(
            [FUNCION, DISPARADOR],
            reverse_sql=[BORRAR_DISPARADOR, BORRAR_FUNCION],
        ),
    ]
