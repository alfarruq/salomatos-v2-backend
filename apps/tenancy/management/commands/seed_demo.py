from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User
from apps.catalog.models import Service
from apps.patients.models import Patient
from apps.scheduling.models import Chair
from apps.tenancy.models import Clinic, Membership, Organization

DEMO_PASSWORD = "demo-pass-123"


class Command(BaseCommand):
    help = "Creates a demo organization with two branches and one user per role. DEBUG only."

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo runs only with DEBUG=1.")
        if Organization.objects.filter(name="Demo Dental").exists():
            self.stdout.write("Demo data already exists.")
            return

        def user(username, full_name):
            return User.objects.create_user(username=username, password=DEMO_PASSWORD, full_name=full_name)

        org = Organization.objects.create(name="Demo Dental")
        org.owners.add(user("demo_owner", "Demo Owner"))
        for index, name in enumerate(["Demo Branch Chilonzor", "Demo Branch Yunusobod"], start=1):
            clinic = Clinic.objects.create(organization=org, name=name)
            Membership.objects.create(
                user=user(f"demo_admin{index}", f"Demo Admin {index}"), clinic=clinic, role="admin"
            )
            doctor = Membership.objects.create(
                user=user(f"demo_doctor{index}", f"Demo Doctor {index}"), clinic=clinic, role="doctor"
            )
            Chair.objects.create(clinic=clinic, name="Chair 1")
            Service.objects.create(clinic=clinic, name="Consultation", price=50000, duration_minutes=20)
            Service.objects.create(clinic=clinic, name="Composite filling", price=350000, duration_minutes=45)
            for n in range(1, 4):
                Patient.objects.create(
                    clinic=clinic,
                    full_name=f"Demo Patient {index}-{n}",
                    phone_number=f"+99890000{index}{n:03d}",
                    primary_doctor=doctor,
                )
        self.stdout.write(self.style.SUCCESS(f"Demo data created. Password for every demo_* user: {DEMO_PASSWORD}"))
