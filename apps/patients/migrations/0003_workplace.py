from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("patients", "0002_patient_registered_at")]

    operations = [
        migrations.RemoveField(model_name="patient", name="gender"),
        migrations.AddField(
            model_name="patient",
            name="workplace",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
