from apps.core.exceptions import ObjectNotFoundException
from apps.authentication.models import User

class PatientRepository:
    def get_patients(self,clinic_id):
        patients = User.objects.filter(role=User.Roles.PATIENT,clinic=clinic_id)
        return patients


    def get_patient(self,user_id,clinic_id):
        patient = User.objects.filter(id=user_id,role=User.Roles.PATIENT,clinic=clinic_id).first()
        if not patient:
            raise ObjectNotFoundException(
                message="Patient not found",
                message_key="patient_not_found",
            )
        return patient


