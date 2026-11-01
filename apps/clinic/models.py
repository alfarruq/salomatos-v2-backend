from django.db import models
from apps.core.models import CreatedUpdatedAbstractModel
from apps.authentication.models import User
from django.utils.translation import gettext_lazy as _
from apps.authentication.utils import validate_number


class Clinic(CreatedUpdatedAbstractModel):
    admin = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name = 'clinic_admin',
        limit_choices_to = {'role':User.Roles.SUPERADMIN},
        null=True,
        blank=True,
    )
    name = models.CharField(max_length = 255)
    phone_number = models.CharField(max_length = 14,validators=[validate_number])
    address = models.CharField(max_length = 255)
    logo = models.ImageField(upload_to = 'clinic/logo',blank = True, null = True)

    working_hours = models.JSONField(blank = True, null = True)

    def __str__(self):
        return self.name

class TreatmentType(CreatedUpdatedAbstractModel):
    clinic = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='clinic_treatment_types',
        limit_choices_to={'role':User.Roles.SUPERADMIN},
        null = True,
    )
    doctor_type = models.ForeignKey(
        'authentication.DoctorType',
        on_delete=models.SET_NULL,
        related_name = 'doctor_treatment_types',
        blank = True,
        null = True,

    )
    name = models.CharField(max_length = 255)
    price = models.PositiveIntegerField(blank = True, null = True)

    def __str__(self):
        return self.name

class Treatment(CreatedUpdatedAbstractModel):
    class Status(models.TextChoices):
        IN_PROGRESS = 'in_progress', _('In Progress')
        COMPLETED = 'completed', _('Completed')

    clinic = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='clinic_treatments',
        limit_choices_to={'role': User.Roles.SUPERADMIN},
        null = True,
    )

    patient = models.ForeignKey(
        User,
        on_delete = models.SET_NULL,
        related_name = 'patient_treatments',
        limit_choices_to = {'role':User.Roles.PATIENT},
        blank = True,
        null = True,
    )
    doctor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name = 'doctor_treatments',
        limit_choices_to = {'role':User.Roles.DOCTOR},
        blank = True,
        null = True,
    )
    treatment_type = models.ForeignKey(
        TreatmentType,
        on_delete=models.SET_NULL,
        related_name = 'treatments',
        blank = True,
        null = True,
    )

    total_treatment_cost = models.PositiveIntegerField()
    total_paid = models.PositiveIntegerField()
    visit_number = models.PositiveIntegerField()

    tooth_number = models.PositiveIntegerField(blank = True, null = True)
    start_date = models.DateField()
    notes = models.TextField(blank=True, null=True)
    status = models.CharField(choices=Status.choices,max_length=20,default=Status.IN_PROGRESS)

