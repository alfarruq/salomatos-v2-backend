from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.saas import views

router = DefaultRouter()
router.include_root_view = False
router.register("organizations", views.OrganizationViewSet, basename="platform-organization")
router.register("clinics", views.PlatformClinicViewSet, basename="platform-clinic")
router.register("payments", views.PlatformPaymentViewSet, basename="platform-payment")

urlpatterns = [
    path("auth/login/", views.PlatformLoginView.as_view(), name="platform-login"),
    path("auth/refresh/", views.PlatformRefreshView.as_view(), name="platform-refresh"),
    path("auth/logout/", views.PlatformLogoutView.as_view(), name="platform-logout"),
    path("auth/me/", views.PlatformMeView.as_view(), name="platform-me"),
    path("credentials/", views.CredentialsView.as_view(), name="platform-credentials"),
    path("dashboard/", views.DashboardView.as_view(), name="platform-dashboard"),
    *router.urls,
]
