from apps.clinic.api.v1.repositories.doctors import DoctorRepository
from apps.clinic.api.v1.serializers.doctors import (
    DoctorListSerializer,
    DoctorCreateUpdateSerializer,
    DoctorTypeListSerializer,
    DoctorTypeCreateUpdateSerializer
)
from apps.core.services import BaseService
from rest_framework import status
from apps.authentication.models import User
from apps.core.exceptions import (
    ObjectNotFoundException,
    PermissionDeniedException,
)

class DoctorService(BaseService):
    def __init__(self,request):
        super().__init__(request)
        self.db = DoctorRepository()

    def get_doctors(self,*args,**kwargs):
        doctors = self.db.get_doctors(clinic_id=self.request.user)
        return self.get_response(
            doctors,
            DoctorListSerializer,
            context={'request': self.request},
            many=True
        )

    def create_doctor(self, *args, **kwargs):
        serializer_class = DoctorCreateUpdateSerializer(
            data=self.request.data,
            context={'request': self.request}
        )
        serializer_class.is_valid(raise_exception=True)

        doctor = serializer_class.save(
            role=User.Roles.DOCTOR,
            clinic=self.request.user,
        )
        return self.get_response_object(
            doctor,
            DoctorListSerializer,
            context={'request': self.request},
        )

    def update_doctor(self,*args,**kwargs):
        doctor = self.db.get_doctor(user_id=kwargs.get('pk'),clinic_id=self.request.user)
        serializer_class = DoctorCreateUpdateSerializer(
            instance=doctor,
            data=self.request.data,
            partial=True,
            context={'request': self.request}
        )
        serializer_class.is_valid(raise_exception=True)
        serializer_class.save()
        return self.get_response_object(
            obj=doctor,
            response_serializer_class=DoctorListSerializer,
            context={'request': self.request}
        )

    def delete_doctor(self,*args,**kwargs):
        doctor = self.db.get_doctor(user_id=kwargs.get('pk'),clinic_id=self.request.user)
        doctor.delete()
        return self.get_response_object(
            context={'request': self.request},
            status_code=status.HTTP_204_NO_CONTENT,
        )




    def get_doctor_types(self,*args,**kwargs):
        doctor_types = self.db.get_doctor_types(clinic_id=self.request.user)
        return self.get_response(
            doctor_types,
            DoctorTypeListSerializer,
            context={'request': self.request},
            many=True
        )

    def create_doctor_type(self, *args, **kwargs):
        serializer_class = DoctorTypeCreateUpdateSerializer(
            data=self.request.data,
            context={'request': self.request}
        )
        serializer_class.is_valid(raise_exception=True)

        doctor_types = serializer_class.save(
            clinic=self.request.user,
        )
        return self.get_response_object(
            doctor_types,
            DoctorTypeListSerializer,
            context={'request': self.request},
        )

    def update_doctor_type(self,*args,**kwargs):
        doctor_type = self.db.get_doctor_type(doctor_type_id=kwargs.get('pk'),clinic_id=self.request.user)
        serializer_class = DoctorTypeCreateUpdateSerializer(
            instance=doctor_type,
            data=self.request.data,
            partial=True,
            context={'request': self.request}
        )
        serializer_class.is_valid(raise_exception=True)
        serializer_class.save()
        return self.get_response_object(
            obj=doctor_type,
            response_serializer_class=DoctorTypeListSerializer,
            context={'request': self.request}
        )

    def delete_doctor_type(self,*args,**kwargs):
        doctor_type = self.db.get_doctor_type(doctor_type_id=kwargs.get('pk'),clinic_id=self.request.user)
        doctor_type.delete()
        return self.get_response_object(
            context={'request': self.request},
            status_code=status.HTTP_204_NO_CONTENT,
        )


