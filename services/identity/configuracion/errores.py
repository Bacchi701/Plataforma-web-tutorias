"""Formato de error unico de la API (Pilar 2, seccion 11).

Toda respuesta de error lleva un codigo, un mensaje legible y, si hace
falta, los detalles por campo. Asi el frontend tiene un solo manejador.
"""

from rest_framework.views import exception_handler


def formato_uniforme(exc, context):
    respuesta = exception_handler(exc, context)
    if respuesta is None:
        return None

    datos = respuesta.data
    if isinstance(datos, dict) and set(datos) == {"detail"}:
        mensaje, detalles = str(datos["detail"]), None
    else:
        mensaje, detalles = "La petición tiene datos inválidos.", datos

    codigo = getattr(getattr(exc, "detail", None), "code", None)
    respuesta.data = {
        "codigo": str(codigo or getattr(exc, "default_code", "error")),
        "mensaje": mensaje,
        "detalles": detalles,
    }
    return respuesta
