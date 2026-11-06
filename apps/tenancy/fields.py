from rest_framework import serializers


class ClinicRelatedField(serializers.PrimaryKeyRelatedField):
    """A FK input limited to rows of the request's clinic.

    Without it an id from another tenant would be accepted and its row linked
    (and later shown) here. Pass `extra_filter` to narrow further, e.g. to
    doctors only.
    """

    def __init__(self, **kwargs):
        self.extra_filter = kwargs.pop("extra_filter", None)
        super().__init__(**kwargs)

    def get_queryset(self):
        request = self.context.get("request")
        clinic = getattr(request, "clinic", None)
        queryset = super().get_queryset()
        if clinic is None:
            return queryset.none()
        queryset = queryset.filter(clinic=clinic)
        if self.extra_filter:
            queryset = queryset.filter(**self.extra_filter)
        return queryset
