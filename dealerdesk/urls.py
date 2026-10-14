from django.contrib import admin
from django.urls import include, path

from core import frontend_views

urlpatterns = [
    path("", frontend_views.index, name="frontend_home"),
    path("dashboard/", frontend_views.index, name="frontend_dashboard"),
    path("dashboard", frontend_views.index, name="frontend_dashboard_noslash"),
    path("docs/", frontend_views.docs, name="frontend_docs"),
    path("docs", frontend_views.docs, name="frontend_docs_noslash"),
    path("api/docs/", frontend_views.docs, name="frontend_api_docs"),
    path("api/docs", frontend_views.docs, name="frontend_api_docs_noslash"),
    path("api/", include("core.urls")),
    path("admin/", admin.site.urls),
]

