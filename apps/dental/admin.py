from django.contrib import admin

from apps.dental.models import TreatmentPlan


@admin.register(TreatmentPlan)
class TreatmentPlanAdmin(admin.ModelAdmin):
    # Platform operators see ids and states only, never clinical details.
    list_display = ("id", "clinic", "status", "created_at")
    list_filter = ("status",)
    fields = ("clinic", "status")
    readonly_fields = fields

    def has_add_permission(self, request):
        return False
