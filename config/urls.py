from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions

admin.site.site_header = "SalomatOS Admin"
admin.site.site_title = "SalomatOS project Admin"
admin.site.index_title = "Welcome to SalomatOS project dashboard"

schema_view = get_schema_view(
    openapi.Info(
        title="SalomatOS project API",
        default_version="v1",
        description="API for SalomatOS",
        terms_of_service="",
        contact=openapi.Contact(email="usman20060623@gmail.com"),
        license=openapi.License(name="BSD License"),
    ),
    public=True,
    permission_classes=[permissions.AllowAny],
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.authentication.api.urls")),
    path("api/", include("apps.calendars.api.urls")),
    path("api/", include("apps.clinic.api.urls")),
    path("api/", include("apps.core.api.urls")),

    re_path(r"static/(?P<path>.*)$", serve, {"document_root": settings.STATIC_ROOT}),
    re_path(r"media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]

if settings.DEBUG:
    urlpatterns += [
        re_path(
            r"^swagger(?P<format>\.json|\.yaml)$",
            schema_view.without_ui(cache_timeout=0),
            name="schema-json",
        ),
        re_path(
            r"^swagger/$",
            schema_view.with_ui("swagger", cache_timeout=0),
            name="schema-swagger-ui",
        ),
        re_path(
            r"^redoc/$",
            schema_view.with_ui("redoc", cache_timeout=0),
            name="schema-redoc",
        ),
    ]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
