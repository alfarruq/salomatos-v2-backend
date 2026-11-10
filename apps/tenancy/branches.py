"""Branches ("filial") of the caller's organization, managed by its owners.

A branch is a `Clinic`, the tenant itself, so this is the one endpoint whose
rows have no `clinic` FK. Its queryset is built from the organization of the
request's clinic (or of `X-Organization-Id`) instead, and only owners of that
organization reach it: an `owner` membership granted in one clinic is not
enough, because that person does not own the other branches.
"""

from django.db import transaction
from django.db.models import Count, Q
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.catalog.models import Service, ServiceCategory
from apps.tenancy.models import Clinic, Membership, Specialty
from apps.tenancy.viewsets import ClinicScopedMixin


class BranchSerializer(serializers.ModelSerializer):
    staff_count = serializers.IntegerField(read_only=True, default=0)
    patient_count = serializers.IntegerField(read_only=True, default=0)
    copy_catalog_from = serializers.UUIDField(
        write_only=True,
        required=False,
        allow_null=True,
        help_text="Create only: copy the price list and specialties of this branch of the same organization.",
    )

    class Meta:
        model = Clinic
        fields = [
            "id",
            "name",
            "phone_number",
            "address",
            "timezone",
            "is_active",
            "staff_count",
            "patient_count",
            "copy_catalog_from",
        ]
        read_only_fields = ["id", "is_active"]

    def _organization(self):
        return self.context["view"].organization

    def validate_name(self, value):
        qs = Clinic.objects.filter(organization=self._organization(), name__iexact=value.strip())
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A branch with this name already exists.", code="duplicate")
        return value.strip()

    def validate_copy_catalog_from(self, value):
        if value is None:
            return None
        if self.instance is not None:
            raise serializers.ValidationError("Only a new branch copies a price list.", code="invalid")
        source = Clinic.objects.filter(organization=self._organization(), pk=value).first()
        if source is None:
            raise serializers.ValidationError("Invalid pk - object does not exist.", code="does_not_exist")
        return source

    @transaction.atomic
    def create(self, validated_data):
        source = validated_data.pop("copy_catalog_from", None)
        # The post_save signal gives every organization owner the new branch.
        branch = Clinic.objects.create(organization=self._organization(), **validated_data)
        if source is not None:
            copy_catalog(source, branch)
        return branch


def copy_catalog(source: Clinic, target: Clinic) -> None:
    """Copies specialties and the price list. Staff, chairs and patients are never copied."""
    specialties = {}
    for row in Specialty.objects.filter(clinic=source):
        specialties[row.pk] = Specialty.objects.create(clinic=target, name=row.name)
    categories = {}
    for row in ServiceCategory.objects.filter(clinic=source):
        categories[row.pk] = ServiceCategory.objects.create(clinic=target, name=row.name)
    Service.objects.bulk_create(
        Service(
            clinic=target,
            category=categories.get(row.category_id),
            specialty=specialties.get(row.specialty_id),
            code=row.code,
            name=row.name,
            price=row.price,
            duration_minutes=row.duration_minutes,
            is_active=row.is_active,
        )
        for row in Service.objects.filter(clinic=source)
    )


class BranchViewSet(
    ClinicScopedMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Clinic.objects.none()
    serializer_class = BranchSerializer
    pagination_class = None
    audit_reads = False
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    organization_actions = frozenset({"list"})
    required_permissions = {
        "list": "branch:manage",
        "create": "branch:manage",
        "partial_update": "branch:manage",
        "destroy": "branch:manage",
        "reactivate": "branch:manage",
    }

    def check_permissions(self, request):
        super().check_permissions(request)
        organization = request.organization or request.clinic.organization
        if not organization.owners.filter(pk=request.user.pk).exists():
            # Same answer as an unknown organization: an owner role in one branch is not ownership.
            raise NotFound()
        self.organization = organization

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Clinic.objects.none()
        # Replaces the clinic filter on purpose (see the module docstring): the rows are the branches.
        return (
            Clinic.objects.filter(organization=self.organization)
            .annotate(
                staff_count=Count(
                    "memberships",
                    filter=Q(memberships__is_active=True) & ~Q(memberships__role=Membership.Role.OWNER),
                    distinct=True,
                ),
                patient_count=Count("patients", filter=Q(patients__archived_at__isnull=True), distinct=True),
            )
            .order_by("created_at")
        )

    def perform_create(self, serializer):
        branch = serializer.save()
        record(self.request, AuditLog.Action.CREATE, branch, clinic=branch)

    def perform_update(self, serializer):
        branch = serializer.save()
        record(self.request, AuditLog.Action.UPDATE, branch, clinic=branch)

    def destroy(self, request, *args, **kwargs):
        # Branches are closed, not deleted: their patients, visits and money stay readable.
        branch = self.get_object()
        if not Clinic.objects.filter(organization=self.organization, is_active=True).exclude(pk=branch.pk).exists():
            raise ValidationError({"branch": "The last open branch cannot be closed."}, code="last_branch")
        branch.is_active = False
        branch.save(update_fields=["is_active", "updated_at"])
        record(request, AuditLog.Action.ARCHIVE, branch, clinic=branch)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def reactivate(self, request, pk=None):
        branch = self.get_object()
        branch.is_active = True
        branch.save(update_fields=["is_active", "updated_at"])
        record(request, AuditLog.Action.RESTORE, branch, clinic=branch)
        return Response(self.get_serializer(self.get_queryset().get(pk=branch.pk)).data)
