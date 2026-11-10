from django.contrib import admin

from apps.saas.models import Contract, PlatformEvent, PlatformPayment


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ("organization", "currency", "install_fee", "server_fee_yearly", "voice_enabled")


@admin.register(PlatformPayment)
class PlatformPaymentAdmin(admin.ModelAdmin):
    # Read-only: payments are entered and voided through the platform API, which keeps the ledger append-only.
    list_display = ("organization", "kind", "amount", "currency", "paid_on", "voided_at")
    list_filter = ("kind", "currency")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PlatformEvent)
class PlatformEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "organization", "target_type", "target_id")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
