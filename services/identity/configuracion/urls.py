from django.urls import include, path

urlpatterns = [
    path("api/identity/v1/", include("salud.urls")),
    path("api/identity/v1/", include("cuentas.urls")),
]
