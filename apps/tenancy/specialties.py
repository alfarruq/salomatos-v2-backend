"""The dental specialty every clinic is born with."""

import re

from apps.tenancy.models import Clinic, Specialty

DENTAL_NAME = "Stomatolog"
# Clinics typed the name themselves before it was built in; the live clinic has "Stamatolog".
DENTAL_NAME_PATTERN = re.compile(r"^\s*(stomatolog|stamatolog|стоматолог)", re.IGNORECASE)


def looks_dental(name: str) -> bool:
    return DENTAL_NAME_PATTERN.match(name) is not None


def ensure_dental_specialty(clinic: Clinic) -> Specialty:
    existing = Specialty.objects.filter(clinic=clinic, is_dental=True).first()
    if existing is not None:
        return existing
    # A same-named row typed by hand becomes the dental one instead of clashing on the name.
    for specialty in Specialty.objects.filter(clinic=clinic):
        if looks_dental(specialty.name):
            Specialty.objects.filter(pk=specialty.pk).update(is_dental=True)
            specialty.is_dental = True
            return specialty
    specialty = Specialty(clinic=clinic, name=DENTAL_NAME)
    specialty.is_dental = True
    specialty.save()
    return specialty
