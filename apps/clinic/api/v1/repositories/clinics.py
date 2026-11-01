from apps.core.exceptions import ObjectNotFoundException
from apps.clinic.models import Clinic , SMS

class ClinicRepository:
    def get_clinics(self,user):
        clinics = Clinic.objects.filter(admin=user)
        return clinics

    def get_clinic(self,clinic_id):
        clinic = Clinic.objects.filter(id=clinic_id).first()
        if not clinic:
            raise ObjectNotFoundException(
                message="Clinic not found",
                message_key="clinic_not_found",
            )
        return clinic

class SMSRepository:
    def get_smses(self,clinic_id):
        smses = SMS.objects.filter(clinic=clinic_id)
        return smses

    def get_sms(self,sms_id,clinic_id):
        sms = SMS.objects.filter(id=sms_id,clinic=clinic_id).first()
        if not sms:
            raise ObjectNotFoundException(
                message="SMS not found",
                message_key="sms_not_found",
            )
        return sms






