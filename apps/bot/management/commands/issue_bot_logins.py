from django.core.management.base import BaseCommand

from apps.bot.credentials import issue_for_patient, issue_for_user
from apps.bot.signals import BOT_ROLES
from apps.patients.models import Patient
from apps.tenancy.models import Membership


class Command(BaseCommand):
    help = "Gives a bot login to every patient, doctor and owner that has none yet."

    def handle(self, *args, **options):
        patients = Patient.objects.filter(bot_account__isnull=True)
        users = {
            m.user
            for m in Membership.objects.filter(
                role__in=BOT_ROLES, is_active=True, user__bot_account__isnull=True
            ).select_related("user")
        }
        for patient in patients:
            issue_for_patient(patient)
        for user in users:
            issue_for_user(user)
        self.stdout.write(self.style.SUCCESS("Bot logins issued."))
