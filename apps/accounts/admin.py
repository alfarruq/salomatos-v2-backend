from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.accounts.models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("username",)
    list_display = ("username", "full_name", "is_active", "is_staff")
    search_fields = ("username", "full_name")
    list_filter = ("is_active", "is_staff", "is_platform_operator")
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Profile", {"fields": ("full_name", "phone_number", "email")}),
        (
            "Access",
            {"fields": ("is_active", "is_staff", "is_platform_operator", "is_superuser", "groups", "user_permissions")},
        ),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("username", "full_name", "password1", "password2")}),)
