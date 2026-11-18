from django.db.models import Exists, OuterRef, Q

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
    return queryset.filter(patient_filter(request, prefix=""))


def patient_filter(request, prefix: str = "patient__"):
    """A Q that limits rows linked to a patient to the patients the caller may see."""
    if "patient:view_all" in permissions_for(request.membership):
        return Q()
    from apps.scheduling.models import Appointment

    me = request.membership
    # EXISTS instead of a join: a join repeats a patient once per booking, which
    # forced callers into DISTINCT, and DISTINCT made every list count evaluate
    # its per-row annotations (debt) for the whole table.
    booked_with_me = Appointment.objects.filter(patient_id=OuterRef(f"{prefix}id"), doctor=me)
    return Q(**{f"{prefix}primary_doctor": me}) | Q(Exists(booked_with_me))


def ensure_patient_visible(request, patient: Patient) -> None:
    from rest_framework.exceptions import ValidationError

    if not visible_patients(request).filter(pk=patient.pk).exists():
        # Same message as an unknown id: do not confirm the patient exists.
        raise ValidationError({"patient": "Invalid pk - object does not exist."}, code="does_not_exist")
