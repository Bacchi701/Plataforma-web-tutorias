from django.urls import include, path

urlpatterns = [
    path("api/tutoring/v1/", include("salud.urls")),
    path("api/tutoring/v1/", include("tutorias.urls")),
]
