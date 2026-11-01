from django.contrib import admin
from apps.clinic.models import (
    Treatment,
    TreatmentType,
    Clinic,
    SMS
)



@admin.register(TreatmentType)
class TreatmentTypeAdmin(admin.ModelAdmin):
    list_display = ['id','name','price']
    list_display_links = ['name','price']
    search_fields = ['name','price']

@admin.register(Treatment)
class TreatmentAdmin(admin.ModelAdmin):
    list_display = ['id','patient','doctor','treatment_type','start_date']
    list_display_links = ['patient','doctor','treatment_type','start_date']
    search_fields = ['patient','doctor','treatment_type','start_date']

@admin.register(Clinic)
class ClinicAdmin(admin.ModelAdmin):
    list_display = ['id','name','admin','phone_number','address']
    list_display_links = ['name','address']
    search_fields = ['name','address']

@admin.register(SMS)
class SMSAdmin(admin.ModelAdmin):
    list_display = ['id','clinic','balance',]
    list_display_links = ['clinic','balance',]
    search_fields = ['clinic','balance']


