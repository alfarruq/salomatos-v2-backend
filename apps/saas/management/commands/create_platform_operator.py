import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User


class Command(BaseCommand):
    help = "Create a login for the vendor's platform panel. It gets no clinic access."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--full-name", default="Platform operator")

    def handle(self, *args, username, full_name, **options):
        if User.objects.filter(username__iexact=username).exists():
            raise CommandError("This username is taken.")
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Password (again): "):
            raise CommandError("Passwords do not match.")
        user = User(username=username, full_name=full_name, is_platform_operator=True)
        try:
            validate_password(password, user)
        except ValidationError as err:
            raise CommandError(" ".join(err.messages)) from err
        user.set_password(password)
        user.save()
        self.stdout.write(self.style.SUCCESS(f"Platform operator {username} created."))
