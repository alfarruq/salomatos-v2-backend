from django.db import models
from apps.core.models import CreatedUpdatedAbstractModel
from apps.authentication.models import User
from django.utils.translation import gettext_lazy as _


class Appointment(CreatedUpdatedAbstractModel):
    class Status(models.TextChoices):
        IN_PROGRESS = 'in_progress', _('In Progress')
        COMPLETED = 'completed', _('Completed')

    clinic = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='clinic_appointments',
        limit_choices_to={'role':User.Roles.SUPERADMIN},
        null=True,
    )
    patient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='patient_appointments',
        limit_choices_to={'role':User.Roles.PATIENT},
        blank=True,
        null=True,
    )
    doctor = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='doctor_appointments',
        limit_choices_to={'role':User.Roles.DOCTOR}
    )
    date = models.DateField()
    time = models.TimeField()
    notes = models.TextField(blank=True, null=True)
    status = models.CharField(choices=Status.choices,max_length=20,default=Status.IN_PROGRESS)

    is_reminded = models.BooleanField(default=False)
    treatment_type = models.CharField(max_length=255,blank=True,null=True)
    tooth_number = models.PositiveIntegerField(blank = True, null = True)











