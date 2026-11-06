from django.contrib import admin

from apps.tenancy.models import Clinic, Membership, Organization, Specialty


class ClinicInline(admin.TabularInline):
    model = Clinic
    extra = 0
    fields = ("name", "phone_number", "address", "is_active")


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    inlines = [ClinicInline]


@admin.register(Clinic)
class ClinicAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "is_active")
    list_filter = ("is_active",)


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "clinic", "role", "is_active")
    list_filter = ("role", "is_active")
    raw_id_fields = ("user",)


@admin.register(Specialty)
class SpecialtyAdmin(admin.ModelAdmin):
    list_display = ("name", "clinic")
