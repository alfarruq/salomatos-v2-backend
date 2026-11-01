from django.db import models
from apps.core.models import CreatedUpdatedAbstractModel
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.models import AbstractBaseUser,PermissionsMixin
from apps.authentication.utils import validate_number
from django.contrib.auth.hashers import identify_hasher
from apps.authentication.api.v1.services.user_manager import UserManager
import random
import string


class User(CreatedUpdatedAbstractModel,AbstractBaseUser,PermissionsMixin):
    class Roles(models.TextChoices):
        SUPERADMIN = 'superadmin', _('Super Admin')
        DOCTOR = 'doctor', _('Doctor')
        PATIENT = 'patient', _('Patient')
        ADMIN = 'admin', _('Admin')

    username = models.CharField(max_length = 255,unique=True,blank=True,null=True)
    full_name = models.CharField(max_length = 255)
    phone_number = models.CharField(max_length = 14,validators=[validate_number])
    email = models.EmailField(max_length = 255,blank=True,null=True)
    birth_date = models.DateField(blank=True,null=True)
    image = models.ImageField(upload_to = 'images/',blank=True,null=True)
    address = models.CharField(max_length = 255,blank=True,null=True)
    office = models.CharField(max_length = 255,blank=True,null=True)

    # for doctors
    doctor_type = models.ForeignKey(
        'DoctorType',
        on_delete=models.SET_NULL,
        related_name='doctors',
        blank=True,
        null=True
    )
    experience = models.PositiveIntegerField(blank=True,null=True)
    biography = models.TextField(blank=True,null=True)


    clinic = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        related_name='clinic_users',
        limit_choices_to={'role': Roles.SUPERADMIN},
        blank=True,
        null=True
    )
    role = models.CharField(
        choices = Roles.choices,
        default = Roles.PATIENT,
        max_length=200
    )
    doctor = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        related_name='patients',
        limit_choices_to={'role':Roles.DOCTOR},
        blank=True,
        null=True
    )


    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_origin = models.BooleanField(default=False)

    telegram_auth_code = models.CharField(max_length=10, unique=True, blank=True, null=True)
    telegram_chat_id = models.CharField(max_length=100, unique=True, blank=True, null=True)

    objects = UserManager()
    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = []



    def __str__(self):
        return self.full_name

    def save(self, *args, **kwargs):
        if self.password:
            try:
                identify_hasher(self.password)
            except ValueError:
                self.set_password(self.password)

        if not self.telegram_auth_code and not self.telegram_chat_id:
            while True:
                code = ''.join(random.choices(string.digits, k=6))
                if not User.objects.filter(telegram_auth_code=code).exists():
                    self.telegram_auth_code = code
                    break
        super().save(*args, **kwargs)

class Gallery(CreatedUpdatedAbstractModel):
    clinic = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name = 'clinic_galleries',
        limit_choices_to={'role': User.Roles.SUPERADMIN},
        null=True
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='gallery'
    )
    image = models.ImageField(upload_to = 'images/',blank=True,null=True)


class DoctorType(CreatedUpdatedAbstractModel):
    name = models.CharField(max_length = 255)
    clinic = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='clinic_doctor_types',
        limit_choices_to={'role': User.Roles.SUPERADMIN},
        null=True
    )

    def __str__(self):
        return self.name


