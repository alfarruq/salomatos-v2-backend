"""Hiding prices from callers the owner has kept away from money."""

from apps.tenancy.permissions import can_see_money


class HidesMoneyMixin:
    """Serializer mixin: the listed fields read as null for a caller without `money:view`.

    Done on the server so a hidden price never leaves it; the UI only hides the empty columns.
    """

    money_fields: tuple[str, ...] = ()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if request is not None and not can_see_money(request):
            for name in self.money_fields:
                if name in data:
                    data[name] = None
        return data
