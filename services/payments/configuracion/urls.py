from django.urls import include, path

urlpatterns = [
    path("api/payments/v1/", include("salud.urls")),
]
