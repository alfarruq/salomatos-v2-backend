from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from apps.authentication.models import User, Gallery,DoctorType


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['id', 'username', 'full_name', 'role', 'doctor', 'is_active','is_origin']
    list_display_links = ('id', 'username', 'full_name')
    search_fields = ('username', 'full_name', 'role', 'doctor__full_name')
    list_editable = ('is_origin',)


@admin.register(Gallery)
class GalleryAdmin(admin.ModelAdmin):
    list_display = ['id', 'user']
    list_display_links = ['id', 'user']
    search_fields = ['user__username', 'user__full_name']

@admin.register(DoctorType)
class DoctorTypeAdmin(admin.ModelAdmin):
    list_display = ['id', 'name']
    list_display_links = ['id', 'name']
    search_fields = ['name']
