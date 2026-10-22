import uuid

import pytest
from django.db import IntegrityError, connection, transaction

from .models import Pago


@pytest.mark.django_db
def test_payment_db_tiene_sus_dos_tablas():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        )
        tablas = {fila[0] for fila in cursor.fetchall()}

    assert tablas == {"pago", "intento_pago", "django_migrations"}


@pytest.mark.django_db
def test_sin_tarifa_no_hay_pago():
    with pytest.raises(IntegrityError), transaction.atomic():
        Pago.objects.create(reserva_id=uuid.uuid4(), monto=0)


@pytest.mark.django_db
def test_una_reserva_tiene_un_solo_pago():
    reserva = uuid.uuid4()
    Pago.objects.create(reserva_id=reserva, monto=5000)

    with pytest.raises(IntegrityError), transaction.atomic():
        Pago.objects.create(reserva_id=reserva, monto=5000)
