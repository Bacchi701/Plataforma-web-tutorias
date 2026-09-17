from django.urls import path

from . import vistas

urlpatterns = [
    path("estado", vistas.estado, name="estado"),
]
