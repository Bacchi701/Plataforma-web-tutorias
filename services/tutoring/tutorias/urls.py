from django.urls import path

from . import bloques, busqueda, copias, evaluaciones, perfiles, reservas

urlpatterns = [
    path("tutores", busqueda.buscar_tutores, name="tutores"),
    path("tutores/<uuid:usuario_id>", busqueda.perfil_publico, name="tutor"),
    path(
        "tutores/<uuid:usuario_id>/evaluaciones",
        evaluaciones.del_tutor,
        name="tutor-evaluaciones",
    ),
    path("disponibilidad", bloques.mis_bloques, name="bloques"),
    path("disponibilidad/<uuid:bloque_id>", bloques.un_bloque, name="bloque"),
    path("perfiles", perfiles.declarar_o_listar, name="perfiles"),
    path("perfiles/<uuid:perfil_id>", perfiles.un_perfil, name="perfil"),
    path("yo/refrescar", copias.refrescar, name="refrescar"),
    path(
        "reservas/<uuid:reserva_id>/evaluacion",
        evaluaciones.evaluar,
        name="evaluacion",
    ),
    path("reservas", reservas.solicitar_o_listar, name="reservas"),
    path("reservas/<uuid:reserva_id>", reservas.una_reserva, name="reserva"),
]
