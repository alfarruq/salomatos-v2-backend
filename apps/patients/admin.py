from django.contrib import admin

from apps.patients.models import Patient


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    # Django admin is for platform operators; it shows ids, not patient details.
    list_display = ("id", "clinic", "archived_at", "created_at")
    list_filter = ("clinic",)
    fields = ("clinic", "archived_at")
    readonly_fields = fields

    def has_add_permission(self, request):
        return False
