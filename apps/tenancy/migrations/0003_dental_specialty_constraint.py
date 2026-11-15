from django.db import migrations, models


class Migration(migrations.Migration):
    """A migration of its own: PostgreSQL refuses CREATE INDEX on a table with
    deferred FK checks still pending from 0002's inserts in the same transaction."""

    dependencies = [
        ("tenancy", "0002_dental_specialty"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="specialty",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_dental", True)),
                fields=("clinic",),
                name="uniq_dental_specialty_per_clinic",
            ),
        ),
    ]
