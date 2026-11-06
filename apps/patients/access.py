from django.db.models import Q

from apps.patients.models import Patient
from apps.tenancy.permissions import permissions_for


def visible_patients(request):
    """Patients the caller may see in the current clinic.

    Shared by every module that hangs records off a patient, so that a doctor
    cannot reach a colleague's patient through prescriptions or images.
    """
    queryset = Patient.objects.filter(clinic_id__in=request.clinic_ids)
    if "patient:view_all" in permissions_for(request.membership):
        return queryset
    me = request.membership
    return queryset.filter(Q(primary_doctor=me) | Q(appointments__doctor=me)).distinct()


def patient_filter(request, prefix: str = "patient__"):
    """A Q that limits rows linked to a patient to the patients the caller may see."""
    if "patient:view_all" in permissions_for(request.membership):
        return Q()
    me = request.membership
    return Q(**{f"{prefix}primary_doctor": me}) | Q(**{f"{prefix}appointments__doctor": me})


def ensure_patient_visible(request, patient: Patient) -> None:
    from rest_framework.exceptions import ValidationError

    if not visible_patients(request).filter(pk=patient.pk).exists():
        # Same message as an unknown id: do not confirm the patient exists.
        raise ValidationError({"patient": "Invalid pk - object does not exist."}, code="does_not_exist")
