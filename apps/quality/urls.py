from django.urls import path

from apps.quality import views

urlpatterns = [
    path("exceptions/", views.exception_list, name="exception_list"),
    path("exceptions/<int:pk>/resolve/", views.exception_resolve, name="exception_resolve"),
]
