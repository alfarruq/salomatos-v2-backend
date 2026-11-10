import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models

from apps.core.validators import validate_phone


class UserManager(BaseUserManager):
    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError("Username is required")
        user = self.model(username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(username, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """A staff login. Patients are not users (see apps.patients).

    What a user may do is decided per clinic by `tenancy.Membership`, never by a
    field on the user, so one person can work in several clinics with
    different roles.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=150, unique=True)
    full_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=16, validators=[validate_phone], blank=True)
    email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)
    # Django admin access; also marks platform operators.
    is_staff = models.BooleanField(default=False)
    # The vendor's own staff (platform panel). Such a login holds no clinic
    # membership and cannot sign in to the clinic app.
    is_platform_operator = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return self.username
