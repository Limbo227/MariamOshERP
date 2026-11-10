from django.urls import path

from apps.procurement import contract_views, views

urlpatterns = [
    path("contracts/", contract_views.contract_list, name="contract_list"),
    path("contracts/new/", contract_views.contract_create, name="contract_create"),
    path("contracts/swod/", contract_views.contract_swod, name="contract_swod"),
    path("contracts/<int:pk>/", contract_views.contract_detail, name="contract_detail"),
    path("contracts/<int:pk>/ship/", contract_views.contract_ship, name="contract_ship"),
    path("contracts/<int:pk>/receive/", contract_views.contract_receive, name="contract_receive"),
    path("contracts/<int:pk>/pay/", contract_views.contract_pay, name="contract_pay"),
    path("payments/", contract_views.payment_list, name="payment_list"),
    path("orders/", views.order_list, name="order_list"),
    path("orders/new/", views.order_create, name="order_create"),
    path("orders/<int:pk>/", views.order_detail, name="order_detail"),
    path("orders/<int:pk>/confirm/", views.order_confirm, name="order_confirm"),
    path("orders/<int:pk>/accept/", views.order_accept, name="order_accept"),
    path("orders/<int:pk>/receive/", views.order_receive, name="order_receive"),
    path("orders/<int:pk>/amend/", views.order_amend, name="order_amend"),
    path("orders/<int:pk>/pay/", views.order_pay, name="order_pay"),
    path("shipments/", views.shipment_list, name="shipment_list"),
    path("shipments/new/", views.shipment_create, name="shipment_create"),
    path("shipments/<int:pk>/", views.shipment_detail, name="shipment_detail"),
    path("shipments/<int:pk>/wagon/", views.shipment_wagon, name="shipment_wagon"),
    path("shipments/<int:pk>/charge/", views.shipment_charge, name="shipment_charge"),
    path("shipments/<int:pk>/passport/", views.shipment_passport, name="shipment_passport"),
    path("shipments/<int:pk>/state/", views.shipment_state, name="shipment_state"),
]
