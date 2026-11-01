from apps.core.exceptions import ObjectNotFoundException
from apps.authentication.models import User

class PatientRepository:
    def get_patients(self, user):
        patients = User.objects.filter(role=User.Roles.PATIENT, is_origin=True)

        if user.role == User.Roles.SUPERADMIN:
            return patients.filter(clinic_id=user.id)
        if user.role == User.Roles.ADMIN:
            return patients.filter(clinic_id=user.clinic_id)
        if user.role == User.Roles.DOCTOR:
            return patients.filter(clinic_id=user.clinic_id, doctor_id=user.id)
        return patients.none()

    def get_patient(self, user_id, user):
        patients = User.objects.filter(id=user_id, role=User.Roles.PATIENT)

        if user.role == User.Roles.SUPERADMIN:
            patients = patients.filter(clinic_id=user.id)
        elif user.role == User.Roles.ADMIN:
            patients = patients.filter(clinic_id=user.clinic_id)
        elif user.role == User.Roles.DOCTOR:
            patients = patients.filter(clinic_id=user.clinic_id, doctor_id=user.id)
        else:
            patients = patients.none()

        patient = patients.first()
        if not patient:
            raise ObjectNotFoundException(
                message="Patient not found",
                message_key="patient_not_found",
            )
        return patient


