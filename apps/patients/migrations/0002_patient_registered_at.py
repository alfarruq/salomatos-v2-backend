import django.utils.timezone
from django.db import migrations, models


def registered_when_created(apps, schema_editor):
    # Every existing row was entered as a full patient, so it was registered when it was created.
    Patient = apps.get_model("patients", "Patient")
    Patient.objects.update(registered_at=models.F("created_at"))


class Migration(migrations.Migration):
    dependencies = [
        ("patients", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="patient",
            name="registered_at",
            field=models.DateTimeField(blank=True, default=django.utils.timezone.now, null=True),
        ),
        migrations.RunPython(registered_when_created, migrations.RunPython.noop),
    ]
