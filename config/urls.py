from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from apps.ui.views import WorkplaceLoginView

# Technical admin is reserved for superusers; business users use scoped screens.
admin.site.has_permission = lambda request: request.user.is_active and request.user.is_superuser
admin.site.site_header = "EBB ERP"
admin.site.site_title = "EBB ERP"
admin.site.index_title = "Служебные данные"
urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", WorkplaceLoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("apps.ui.urls")),
]

