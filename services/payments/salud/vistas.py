import os

from django.db import connection
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response


@api_view(["GET"])
def estado(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        base_de_datos = "ok"
    except Exception:
        base_de_datos = "sin conexion"

    cuerpo = {
        "servicio": os.environ.get("NOMBRE_SERVICIO", "desconocido"),
        "estado": "ok" if base_de_datos == "ok" else "degradado",
        "base_de_datos": base_de_datos,
        "version": "0.1.0",
    }

    # Devolver 503 cuando la base no responde es lo que hace util al
    # healthcheck: un contenedor que arranco pero no puede leer su base
    # no esta sano, y el compositor no debe darlo por listo.
    codigo = (
        status.HTTP_200_OK
        if base_de_datos == "ok"
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return Response(cuerpo, status=codigo)
