from django.db import migrations
from django.db.models import F, Value
from django.db.models.functions import Round


def fold_discount_into_price(apps, schema_editor):
    # Totals must not change: a discounted line becomes a line with the lower price.
    for name in ("Procedure", "PlanItem"):
        model = apps.get_model("dental", name)
        model.objects.filter(discount_percent__gt=0).update(
            unit_price=Round(F("unit_price") * (Value(100) - F("discount_percent")) / Value(100), 2)
        )


class Migration(migrations.Migration):
    dependencies = [("dental", "0002_procedure_status")]

    operations = [
        migrations.RunPython(fold_discount_into_price, migrations.RunPython.noop),
        migrations.RemoveField(model_name="procedure", name="discount_percent"),
        migrations.RemoveField(model_name="planitem", name="discount_percent"),
    ]
