"""Every new patient and every doctor or owner gets a bot login at once.

A signal, not a view hook, so rows made by seed_demo, Django admin or a shell
get one too.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.bot.credentials import issue_for_patient, issue_for_user
from apps.patients.models import Patient
from apps.tenancy.models import Membership

# Admins have nothing to do in the bot yet, so they get no login to leak.
BOT_ROLES = (Membership.Role.OWNER, Membership.Role.DOCTOR)


@receiver(post_save, sender=Patient)
def issue_patient_login(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        issue_for_patient(instance)


@receiver(post_save, sender=Membership)
def issue_staff_login(sender, instance, created, raw=False, **kwargs):
    if not raw and instance.role in BOT_ROLES and instance.is_active:
        issue_for_user(instance.user)
