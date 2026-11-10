from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.tenancy.services import create_organization


class Command(BaseCommand):
    help = "Creates a customer organization with its first branch, for an install."

    def add_arguments(self, parser):
        parser.add_argument("name")
        parser.add_argument("--owner", action="append", default=[], help="Username of an owner; repeatable.")

    def handle(self, *args, name, owner, **options):
        users = list(get_user_model().objects.filter(username__in=owner))
        missing = set(owner) - {user.username for user in users}
        if missing:
            raise CommandError(f"Unknown usernames: {', '.join(sorted(missing))}")
        organization = create_organization(name, users)
        # Ids only: the name is the customer's, the ids are what an operator needs next.
        self.stdout.write(f"Organization {organization.pk} created with branch {organization.clinics.get().pk}.")
