from django.urls import include, path

urlpatterns = [
    path("api/catalog/v1/", include("salud.urls")),
    path("api/catalog/v1/", include("catalogo.urls")),
]
