from django.core.management.base import BaseCommand

from apps.patients.leads import archive_stale_leads


class Command(BaseCommand):
    help = "Archives people who only booked a visit and have not been back for ten days."

    def handle(self, *args, **options):
        self.stdout.write(f"Archived {archive_stale_leads()} stale leads.")
