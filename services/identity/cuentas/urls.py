from django.urls import path

from . import internas, vistas

urlpatterns = [
    path("registro", vistas.registro, name="registro"),
    path("verificar-correo", vistas.verificar_correo, name="verificar-correo"),
    path("login", vistas.login, name="login"),
    path("refresh", vistas.refresh, name="refresh"),
    path("logout", vistas.logout, name="logout"),
    path("yo", vistas.yo, name="yo"),
    path(
        "internal/usuarios/<uuid:usuario_id>",
        internas.un_usuario,
        name="interna-usuario",
    ),
    path("internal/usuarios", internas.varios_usuarios, name="interna-usuarios"),
]
