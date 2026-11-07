from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from apps.accounts import views as accounts
from apps.audit.views import AuditLogViewSet
from apps.billing.views import PatientBalanceViewSet, PaymentViewSet
from apps.catalog.views import ServiceCategoryViewSet, ServiceViewSet
from apps.clinical.views import PrescriptionViewSet
from apps.dental.views import ProcedureViewSet, ToothRecordViewSet, TreatmentPlanViewSet
from apps.finance.views import (
    CompensationViewSet,
    ExpenseViewSet,
    PayrollViewSet,
    RecurringExpenseViewSet,
    ReportViewSet,
)
from apps.imaging.views import AttachmentViewSet
from apps.patients.views import PatientViewSet
from apps.scheduling.views import AppointmentViewSet, ChairViewSet
from apps.tenancy.views import CurrentClinicView, SpecialtyViewSet, StaffViewSet

admin.site.site_header = "SalomatOS Admin"

router = DefaultRouter()
router.include_root_view = False
router.register("specialties", SpecialtyViewSet, basename="specialty")
router.register("staff", StaffViewSet, basename="staff")
router.register("patients", PatientViewSet, basename="patient")
router.register("service-categories", ServiceCategoryViewSet, basename="service-category")
router.register("services", ServiceViewSet, basename="service")
router.register("chairs", ChairViewSet, basename="chair")
router.register("appointments", AppointmentViewSet, basename="appointment")
router.register("prescriptions", PrescriptionViewSet, basename="prescription")
router.register("attachments", AttachmentViewSet, basename="attachment")
router.register("tooth-records", ToothRecordViewSet, basename="tooth-record")
router.register("treatment-plans", TreatmentPlanViewSet, basename="treatment-plan")
router.register("procedures", ProcedureViewSet, basename="procedure")
router.register("payments", PaymentViewSet, basename="payment")
router.register("balances", PatientBalanceViewSet, basename="balance")
router.register("expenses", ExpenseViewSet, basename="expense")
router.register("recurring-expenses", RecurringExpenseViewSet, basename="recurring-expense")
router.register("compensations", CompensationViewSet, basename="compensation")
router.register("audit-logs", AuditLogViewSet, basename="audit-log")

api_v1 = [
    path("auth/login/", accounts.LoginView.as_view(), name="login"),
    path("auth/refresh/", accounts.RefreshView.as_view(), name="refresh"),
    path("auth/logout/", accounts.LogoutView.as_view(), name="logout"),
    path("auth/me/", accounts.MeView.as_view(), name="me"),
    path("auth/change-password/", accounts.ChangePasswordView.as_view(), name="change-password"),
    path("clinic/", CurrentClinicView.as_view(), name="current-clinic"),
    # Routed by hand: these views compute rows, so they have no detail route.
    path("payroll/", PayrollViewSet.as_view({"get": "list"}), name="payroll-list"),
    path("payroll/pay/", PayrollViewSet.as_view({"post": "pay"}), name="payroll-pay"),
    path("reports/finance/", ReportViewSet.as_view({"get": "finance"}), name="report-finance"),
    path("reports/statistics/", ReportViewSet.as_view({"get": "statistics"}), name="report-statistics"),
    *router.urls,
]

# No media/ route on purpose: uploaded files hold PHI and are only reachable
# through the authenticated download endpoints.
urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include(api_v1)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
]

if settings.DEBUG:
    urlpatterns += [path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs")]
