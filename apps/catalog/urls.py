from django.urls import path

from apps.catalog import views

urlpatterns = [
    path("products/", views.product_list, name="product_list"),
    path("products/new/", views.product_create, name="product_create"),
    path("stations/", views.station_list, name="station_list"),
    path("stations/new/", views.station_create, name="station_create"),
    path("suppliers/", views.supplier_list, name="supplier_list"),
    path("suppliers/new/", views.supplier_create, name="supplier_create"),
]
