from apps.clinic.api.v1.repositories.treatment import TreatmentRepository
from apps.clinic.api.v1.serializers.treatment import (
    TreatmentListSerializer,
    TreatmentCreateUpdateSerializer,
    TreatmentTypeListSerializer,
    TreatmentTypeCreateUpdateSerializer
)
from apps.core.services import BaseService
from apps.authentication.models import User
from rest_framework import status
from apps.clinic.api.v1.filters.treatment import TreatmentFilter,TreatmentTypeFilter

class TreatmentService(BaseService):
    def __init__(self,request):
        super().__init__(request)
        self.db = TreatmentRepository()

    def create_treatment(self,*args,**kwargs):
        serializer_class = TreatmentCreateUpdateSerializer(
            data=self.request.data,context={'request': self.request},
            many=True,
        )
        serializer_class.is_valid(raise_exception=True)
        treatment = serializer_class.save(clinic=self.request.user)
        return self.get_response(
            treatment,
            TreatmentListSerializer,
            context={'request': self.request},
            many=True

        )

    def get_treatments(self,*args,**kwargs):
        unfiltered_treatment = self.db.get_treatments(clinic_id=self.request.user)

        filtered_treatment = TreatmentFilter(
            data=self.request.query_params,
            queryset=unfiltered_treatment,
            request=self.request,
        ).qs

        return self.get_paginated_response(
            filtered_treatment,
            TreatmentListSerializer,
            context={'request': self.request},
        )

    def delete_treatment(self,*args,**kwargs):
        treatment = self.db.get_treatment(treatment_id=kwargs.get('pk'),clinic_id=self.request.user)
        treatment.delete()
        return self.get_response_object(
            context={'request': self.request},
            status_code=status.HTTP_204_NO_CONTENT,
        )

    def update_treatment(self, *args, **kwargs):
        treatment = self.db.get_treatment(treatment_id=kwargs.get('pk'),clinic_id=self.request.user)
        serializer_class = TreatmentCreateUpdateSerializer(
            instance=treatment,
            data=self.request.data,
            partial=True,
            context={'request': self.request}
        )
        serializer_class.is_valid(raise_exception=True)
        serializer_class.save()
        return self.get_response_object(
            obj=treatment,
            response_serializer_class=TreatmentListSerializer,
            context={'request': self.request}
        )


    def get_treatment_types(self,*args,**kwargs):
        unfiltered_treatment_types = self.db.get_treatment_types(clinic_id=self.request.user)

        filtered_treatment_types = TreatmentTypeFilter(
            data=self.request.query_params,
            queryset=unfiltered_treatment_types,
            request=self.request,
        ).qs

        return self.get_paginated_response(
            filtered_treatment_types,
            TreatmentTypeListSerializer,
            context={'request': self.request},


        )

    def create_treatment_type(self,*args,**kwargs):
        serializer_class = TreatmentTypeCreateUpdateSerializer(
            data=self.request.data,context={'request': self.request},
        )
        serializer_class.is_valid(raise_exception=True)
        treatment_type = serializer_class.save(clinic=self.request.user)
        return self.get_response_object(
            treatment_type,
            TreatmentTypeListSerializer,
            context={'request': self.request}
        )

    def update_treatment_type(self, *args, **kwargs):
        treatment_type= self.db.get_treatment_type(treatment_type_id=kwargs.get('pk'),clinic_id=self.request.user)
        serializer_class = TreatmentTypeCreateUpdateSerializer(
            instance=treatment_type,
            data=self.request.data,
            partial=True,
            context={'request': self.request}
        )
        serializer_class.is_valid(raise_exception=True)
        serializer_class.save()
        return self.get_response_object(
            obj=treatment_type,
            response_serializer_class=TreatmentTypeListSerializer,
            context={'request': self.request}
        )

    def delete_treatment_type(self, *args, **kwargs):
        treatment_type = self.db.get_treatment_type(treatment_type_id=kwargs.get('pk'),clinic_id=self.request.user)
        treatment_type.delete()
        return self.get_response_object(
            context={'request': self.request},
            status_code=status.HTTP_204_NO_CONTENT,
        )




