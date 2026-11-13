from django.core.management.base import BaseCommand, CommandError

from apps.saas.v1_import import V1ImportError, import_clinic


class Command(BaseCommand):
    help = (
        "Imports one v1 clinic into a new v2 organization. Dry run unless --commit. "
        "Reads v1 through --source (a libpq connection string to a restored copy of the v1 database)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--source", required=True, help='libpq string, e.g. "dbname=salomatos_v1"')
        parser.add_argument("--clinic", type=int, required=True, help="clinic_clinic.id in v1")
        parser.add_argument("--name", help="Name of the new organization and branch (default: the v1 name)")
        parser.add_argument("--username-prefix", default="", help="Prepended to every imported staff login")
        parser.add_argument("--commit", action="store_true", help="Write the import; without it nothing is saved")

    def handle(self, *args, source, clinic, name, username_prefix, commit, **options):
        try:
            report = import_clinic(source, clinic, name=name, username_prefix=username_prefix, commit=commit)
        except V1ImportError as err:
            raise CommandError(str(err)) from err

        # Counts and ids only: the terminal output must not carry patient data.
        self.stdout.write("Imported:" if report.committed else "Dry run, nothing saved. Would import:")
        for key, value in sorted(report.counts.items()):
            self.stdout.write(f"  {key}: {value}")
        self.stdout.write("Money (UZS):")
        for key, value in report.totals.items():
            self.stdout.write(f"  {key}: {value}")
        issues = {key: value for key, value in report.issues.items() if value}
        if issues:
            self.stdout.write("Check:")
            for key, value in sorted(issues.items()):
                self.stdout.write(f"  {key}: {value}")
        if report.committed:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Organization {report.organization_id}, owner login {report.owner_username}. "
                    "The owner's temporary password is in the platform panel."
                )
            )
