from rest_framework.permissions import IsAuthenticated, AllowAny
from drf_yasg.utils import swagger_auto_schema
from drf_yasg  import openapi
from rest_framework.views import APIView
from apps.clinic.api.v1.serializers.doctors import (
    DoctorListSerializer,
    DoctorCreateUpdateSerializer,
    DoctorTypeListSerializer,
    DoctorTypeCreateUpdateSerializer,
)
from apps.clinic.api.v1.services.doctors import DoctorService

class DoctorCreateListView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        responses={200: DoctorListSerializer},
        tags=['Doctor'],
        operation_description='Doctor List',
    )
    def get(self,request,*args,**kwargs):
        return DoctorService(request=request).get_doctors(*args,**kwargs)

    @swagger_auto_schema(
        request_body=DoctorCreateUpdateSerializer,
        responses={200: DoctorListSerializer},
        tags=['Doctor'],
        operation_description='Doctor Create',
    )
    def post(self,request,*args,**kwargs):
        return DoctorService(request=request).create_doctor(*args,**kwargs)


class DoctorDetailUpdateDeleteView(APIView):
    permission_classes = [IsAuthenticated]
    @swagger_auto_schema(
        request_body=DoctorCreateUpdateSerializer,
        responses={200: DoctorListSerializer},
        tags=['Doctor'],
        operation_description='Doctor Update',
    )
    def patch(self,request,*args,**kwargs):
        return DoctorService(request=request).update_doctor(*args,**kwargs)

    @swagger_auto_schema(
        tags=['Doctor'],
        operation_description='Doctor Delete',
    )
    def delete(self,request,*args,**kwargs):
        return DoctorService(request=request).delete_doctor(*args,**kwargs)






class DoctorTypeCreateListView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        responses={200: DoctorTypeListSerializer},
        tags=['DoctorType'],
        operation_description='Doctor Type List',
    )
    def get(self,request,*args,**kwargs):
        return DoctorService(request=request).get_doctor_types(*args,**kwargs)

    @swagger_auto_schema(
        request_body=DoctorTypeCreateUpdateSerializer,
        responses={200: DoctorTypeListSerializer},
        tags=['DoctorType'],
        operation_description='Doctor Type Create',
    )
    def post(self,request,*args,**kwargs):
        return DoctorService(request=request).create_doctor_type(*args,**kwargs)


class DoctorTypeDetailUpdateDeleteView(APIView):
    permission_classes = [IsAuthenticated]
    @swagger_auto_schema(
        request_body=DoctorTypeCreateUpdateSerializer,
        responses={200: DoctorTypeListSerializer},
        tags=['DoctorType'],
        operation_description='Doctor Type Update',
    )
    def patch(self,request,*args,**kwargs):
        return DoctorService(request=request).update_doctor_type(*args,**kwargs)

    @swagger_auto_schema(
        tags=['DoctorType'],
        operation_description='Doctor Type Delete',
    )
    def delete(self,request,*args,**kwargs):
        return DoctorService(request=request).delete_doctor_type(*args,**kwargs)


