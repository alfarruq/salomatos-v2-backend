from rest_framework.permissions import IsAuthenticated, AllowAny
from drf_yasg.utils import swagger_auto_schema
from drf_yasg  import openapi
from rest_framework.views import APIView
from apps.clinic.api.v1.serializers.clinics import (
    ClinicListSerializer,
    ClinicCreateUpdateSerializer,
    SMSListSerializer
)
from apps.clinic.api.v1.services.clinics import ClinicService,SMSService

class ClinicCreateListView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        responses={200: ClinicListSerializer},
        tags=['Clinic'],
        operation_description='Clinic List',
    )
    def get(self,request,*args,**kwargs):
        return ClinicService(request=request).get_clinics(*args,**kwargs)

    @swagger_auto_schema(
        request_body=ClinicCreateUpdateSerializer,
        responses={200: ClinicListSerializer},
        tags=['Clinic'],
        operation_description='Clinic Create',
    )
    def post(self,request,*args,**kwargs):
        return ClinicService(request=request).create_clinic(*args,**kwargs)


class ClinicDetailUpdateDeleteView(APIView):
    permission_classes = [IsAuthenticated]
    @swagger_auto_schema(
        request_body=ClinicCreateUpdateSerializer,
        responses={200: ClinicListSerializer},
        tags=['Clinic'],
        operation_description='Clinic Update',
    )
    def patch(self,request,*args,**kwargs):
        return ClinicService(request=request).update_clinic(*args,**kwargs)

    @swagger_auto_schema(
        tags=['Clinic'],
        operation_description='Clinic Delete',
    )
    def delete(self,request,*args,**kwargs):
        return ClinicService(request=request).delete_clinic(*args,**kwargs)


class SMSCreateListView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        responses={200: SMSListSerializer},
        tags=['SMS'],
        operation_description='SMS List',
    )
    def get(self,request,*args,**kwargs):
        return SMSService(request=request).get_smses(*args,**kwargs)