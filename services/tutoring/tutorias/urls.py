from django.urls import path

from . import bloques, busqueda

urlpatterns = [
    path("tutores", busqueda.buscar_tutores, name="tutores"),
    path("tutores/<uuid:usuario_id>", busqueda.perfil_publico, name="tutor"),
    path("disponibilidad", bloques.mis_bloques, name="bloques"),
    path("disponibilidad/<uuid:bloque_id>", bloques.un_bloque, name="bloque"),
]
