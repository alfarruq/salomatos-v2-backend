from django.db import models

from apps.core.models import BaseModel


class VoiceUsage(BaseModel):
    """One dictation turned into a draft, kept for the monthly cap and the bill.

    Token counts and ids only: the dictated text is PHI and is never stored.
    """

    clinic = models.ForeignKey("tenancy.Clinic", on_delete=models.PROTECT, related_name="+")
    member = models.ForeignKey("tenancy.Membership", on_delete=models.PROTECT, related_name="+")
    form = models.CharField(max_length=16)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)

    class Meta(BaseModel.Meta):
        indexes = [models.Index(fields=["clinic", "created_at"])]

    def __str__(self):
        return str(self.pk)
