from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

# Technical admin is reserved for superusers; business users use scoped screens.
admin.site.has_permission = lambda request: request.user.is_active and request.user.is_superuser
urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("apps.core.urls")),
    path("catalog/", include("apps.catalog.urls")),
    path("inventory/", include("apps.inventory.urls")),
]

