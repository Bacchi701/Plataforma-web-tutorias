from django.urls import path

from . import internas, vistas

urlpatterns = [
    path("pagos", vistas.crear_o_consultar, name="pagos"),
    path("pagos/<uuid:pago_id>/simular", vistas.simular, name="simular"),
    path("internal/pagos/reembolso", internas.reembolso, name="interna-reembolso"),
]
