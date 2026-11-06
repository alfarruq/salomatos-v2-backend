from django.contrib import admin

from apps.catalog.models import Service, ServiceCategory

admin.site.register(ServiceCategory)


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "clinic", "price", "is_active")
    list_filter = ("clinic", "is_active")
