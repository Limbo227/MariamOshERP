from django.urls import path

from apps.inventory import views

urlpatterns = [
    path("warehouses/", views.warehouse_list, name="warehouse_list"),
    path("balances/", views.balance_list, name="balance_list"),
    path("openings/", views.opening_list, name="opening_list"),
    path("openings/new/", views.opening_create, name="opening_create"),
    path("openings/<int:pk>/", views.opening_detail, name="opening_detail"),
    path("openings/<int:pk>/post/", views.opening_post, name="opening_post"),
]
