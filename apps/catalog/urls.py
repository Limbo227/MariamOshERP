from django.urls import path

from apps.catalog import views

urlpatterns = [
    path("products/", views.product_list, name="product_list"),
    path("suppliers/", views.supplier_list, name="supplier_list"),
]
