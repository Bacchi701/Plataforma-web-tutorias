from django.urls import path

from . import busqueda

urlpatterns = [
    path("tutores", busqueda.buscar_tutores, name="tutores"),
    path("tutores/<uuid:usuario_id>", busqueda.perfil_publico, name="tutor"),
]
