from apps.core.exceptions import ObjectNotFoundException
from apps.clinic.models import Treatment,TreatmentType
from apps.authentication.models import User

class TreatmentRepository:
    def get_treatments(self,clinic_id):
        treatments = Treatment.objects.filter(patient__role=User.Roles.PATIENT,clinic=clinic_id)
        return treatments

    def get_treatment(self,treatment_id,clinic_id):
        treatment = Treatment.objects.filter(id=treatment_id,clinic=clinic_id).first()
        if not treatment:
            raise ObjectNotFoundException(
                message="Treatment not found",
                message_key="treatment_not_found",
            )
        return treatment

    def get_treatment_types(self,clinic_id):
        treatment_types = TreatmentType.objects.filter(clinic=clinic_id)
        return treatment_types

    def get_treatment_type(self, treatment_type_id,clinic_id):
        treatment_type = TreatmentType.objects.filter(id=treatment_type_id,clinic=clinic_id).first()
        if not treatment_type:
            raise ObjectNotFoundException(
                message="Treatment type not found",
                message_key="treatment_type_not_found",
            )
        return treatment_type

