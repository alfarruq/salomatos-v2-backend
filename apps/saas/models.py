from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.core.models import BaseModel


class Currency(models.TextChoices):
    USD = "USD", "USD"
    UZS = "UZS", "UZS"


class Contract(BaseModel):
    """What one customer (organization) agreed to pay. One row per organization.

    Prices live here; what was actually paid lives in `PlatformPayment`, so a
    price change never rewrites history.
    """

    organization = models.OneToOneField("tenancy.Organization", on_delete=models.PROTECT, related_name="contract")
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.USD)
    install_fee = models.DecimalField(max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    server_fee_yearly = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    voice_fee_monthly = models.DecimalField(
        max_digits=14, decimal_places=2, default=10, validators=[MinValueValidator(0)]
    )
    voice_enabled = models.BooleanField(default=False)
    # Null = the platform default (VOICE_MONTHLY_LIMIT).
    voice_monthly_limit = models.PositiveIntegerField(null=True, blank=True)
    # Off by default: the vendor sets the owner's password and changes it on request.
    owner_can_change_password = models.BooleanField(default=False)
    signed_on = models.DateField(null=True, blank=True)
    # The vendor's own notes about the deal. Never patient data.
    note = models.CharField(max_length=500, blank=True)

    def __str__(self):
        return str(self.pk)


class PlatformPayment(BaseModel):
    """Money a customer paid the vendor, entered by hand. Append-only: a mistake is voided."""

    class Kind(models.TextChoices):
        INSTALL = "install", "Install fee"
        SERVER = "server", "Server fee"
        VOICE = "voice", "Voice add-on"
        SMS = "sms", "SMS credits"
        OTHER = "other", "Other"

    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        CARD = "card", "Card"
        TRANSFER = "transfer", "Bank transfer"

    organization = models.ForeignKey("tenancy.Organization", on_delete=models.PROTECT, related_name="platform_payments")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    currency = models.CharField(max_length=3, choices=Currency.choices)
    method = models.CharField(max_length=16, choices=Method.choices, default=Method.TRANSFER)
    paid_on = models.DateField()
    # Server and voice payments extend the paid period up to this date.
    covers_until = models.DateField(null=True, blank=True)
    # SMS payments buy this many messages.
    sms_credits = models.PositiveIntegerField(null=True, blank=True)
    note = models.CharField(max_length=500, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    void_reason = models.CharField(max_length=500, blank=True)

    class Meta(BaseModel.Meta):
        ordering = ["-paid_on", "-created_at"]
        indexes = [models.Index(fields=["organization", "kind"]), models.Index(fields=["paid_on"])]

    def __str__(self):
        return str(self.pk)


class IssuedCredential(BaseModel):
    """The temporary password the vendor handed an owner, readable until the owner replaces it.

    Only the first password is kept, encrypted. `password_hash` is the user's hash at
    issue time: once the owner (or anyone) sets another password the hashes differ, the
    copy is stale and is neither shown nor kept. A password the owner chose is never stored.
    """

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    password_encrypted = models.TextField()
    password_hash = models.CharField(max_length=256)

    def __str__(self):
        return str(self.pk)


class PlatformEvent(BaseModel):
    """What a platform operator did to which customer. Ids and codes only; append-only."""

    class Action(models.TextChoices):
        LOGIN = "login", "Login"
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        SUSPEND = "suspend", "Suspend"
        REACTIVATE = "reactivate", "Reactivate"
        PAYMENT = "payment", "Payment"
        VOID = "void", "Void"
        RESET_PASSWORD = "reset_password", "Reset password"
        REVEAL_PASSWORD = "reveal_password", "Reveal temporary password"

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    action = models.CharField(max_length=16, choices=Action.choices)
    organization = models.ForeignKey(
        "tenancy.Organization", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    target_type = models.CharField(max_length=64, blank=True)
    target_id = models.UUIDField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        indexes = [models.Index(fields=["organization", "-created_at"])]

    def __str__(self):
        return str(self.pk)
