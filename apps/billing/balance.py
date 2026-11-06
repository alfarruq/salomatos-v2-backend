from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from apps.billing.models import Payment
from apps.dental.models import Procedure

ZERO = Value(Decimal("0.00"), output_field=DecimalField(max_digits=14, decimal_places=2))
MONEY = DecimalField(max_digits=14, decimal_places=2)

# unit_price * quantity * (100 - discount) / 100, the same formula as PricedLine.total.
PROCEDURE_TOTAL = ExpressionWrapper(
    F("unit_price") * F("quantity") * (Value(100) - F("discount_percent")) / Value(100), output_field=MONEY
)


def _sum_subquery(queryset, expression):
    return Coalesce(
        Subquery(
            queryset.values("patient").annotate(s=Sum(expression)).values("s")[:1],
            output_field=MONEY,
        ),
        ZERO,
    )


def annotate_balance(patients):
    """Adds `charged`, `paid` and `debt` (charged - paid) to a Patient queryset."""
    charged = _sum_subquery(Procedure.objects.filter(patient=OuterRef("pk"), voided_at__isnull=True), PROCEDURE_TOTAL)
    paid = _sum_subquery(Payment.objects.filter(patient=OuterRef("pk"), voided_at__isnull=True), F("amount"))
    return patients.annotate(charged=charged, paid=paid).annotate(
        debt=ExpressionWrapper(F("charged") - F("paid"), output_field=MONEY)
    )
