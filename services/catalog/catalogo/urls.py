from django.urls import path

from . import vistas

urlpatterns = [
    path("carreras", vistas.listar_carreras, name="carreras"),
    path("carreras/<uuid:carrera_id>", vistas.detalle_carrera, name="carrera"),
    path(
        "carreras/<uuid:carrera_id>/asignaturas",
        vistas.asignaturas_de_carrera,
        name="carrera-asignaturas",
    ),
    path("asignaturas", vistas.buscar_asignaturas, name="asignaturas"),
    path("areas", vistas.listar_areas, name="areas"),
    path("sedes", vistas.listar_sedes, name="sedes"),
]
