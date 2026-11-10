from django.urls import path

from apps.inventory import views

urlpatterns = [
    path("warehouses/", views.warehouse_list, name="warehouse_list"),
    path("balances/", views.balance_list, name="balance_list"),
    path("openings/", views.opening_list, name="opening_list"),
    path("openings/new/", views.opening_create, name="opening_create"),
    path("openings/<int:pk>/", views.opening_detail, name="opening_detail"),
    path("openings/<int:pk>/post/", views.opening_post, name="opening_post"),
    path("receipts/", views.receipt_list, name="receipt_list"),
    path("receipts/new/", views.receipt_create, name="receipt_create"),
    path("receipts/<int:pk>/", views.receipt_detail, name="receipt_detail"),
    path("receipts/<int:pk>/post/", views.receipt_post, name="receipt_post"),
    path("receipts/<int:pk>/inspect/", views.receipt_inspect, name="receipt_inspect"),
    path("receipts/<int:pk>/release/", views.receipt_release, name="receipt_release"),
    path("adjustments/new/", views.adjustment_create, name="adjustment_create"),
    path("ledger/", views.ledger_list, name="ledger_list"),
]
