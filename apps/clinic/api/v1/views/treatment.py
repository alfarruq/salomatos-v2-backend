from rest_framework.permissions import IsAuthenticated, AllowAny
from drf_yasg.utils import swagger_auto_schema
from drf_yasg  import openapi
from rest_framework.views import APIView
from apps.clinic.api.v1.serializers.treatment import (
    TreatmentListSerializer,
    TreatmentCreateUpdateSerializer,
    TreatmentTypeListSerializer,
    TreatmentTypeCreateUpdateSerializer
)
from apps.clinic.api.v1.services.treatment import TreatmentService


class TreatmentCreateListView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        request_body=TreatmentCreateUpdateSerializer(many=True),
        responses={200: TreatmentListSerializer(many=True)},
        tags=['Treatment'],
        operation_description='Treatment Create',
    )
    def post(self,request,*args,**kwargs):
        return TreatmentService(request=request).create_treatment(*args,**kwargs)

    @swagger_auto_schema(
        responses={200: TreatmentListSerializer},
        tags=['Treatment'],
        operation_description='Treatment List',
        manual_parameters=[
            openapi.Parameter(
                name='patient_id',
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_INTEGER,
                description='Patient ID',
            ),
            openapi.Parameter(
                name='doctor_id',
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_INTEGER,
                description='Doctor ID',
            ),
            openapi.Parameter(
                name='treatment_type_id',
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_INTEGER,
                description='Treatment Type ID',
            ),
            openapi.Parameter(
                name = 'remaining',
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_BOOLEAN,
                description='Remaining',

            ),
            openapi.Parameter(
                name = 'status',
                in_=openapi.IN_QUERY,
                type = openapi.TYPE_STRING,
                enum = ['in_progress','completed'],
                description='Status',
            )
        ],
    )
    def get(self,request,*args,**kwargs):
        return TreatmentService(request=request).get_treatments(*args,**kwargs)

class TreatmentDetailUpdateDeleteView(APIView):
    permission_classes = [IsAuthenticated]
    @swagger_auto_schema(
        tags=['Treatment'],
        operation_description='Treatment Delete',
    )
    def delete(self,request,*args,**kwargs):
        return TreatmentService(request=request).delete_treatment(*args,**kwargs)

    @swagger_auto_schema(
        request_body=TreatmentCreateUpdateSerializer,
        responses={200: TreatmentListSerializer},
        tags=['Treatment'],
        operation_description='Treatment  Update',
    )
    def patch(self, request, *args, **kwargs):
        return TreatmentService(request=request).update_treatment(*args, **kwargs)

class TreatmentTypeCreateListView(APIView):
    permission_classes = [IsAuthenticated]
    @swagger_auto_schema(
        responses={200: TreatmentTypeListSerializer},
        tags=['TreatmentType'],
        operation_description='Treatment Types List',
        manual_parameters=[
            openapi.Parameter(
                name='doctor_type_id',
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_INTEGER,
                description='Doctor type ID',
            )
        ]
    )
    def get(self,request,*args,**kwargs):
        return TreatmentService(request=request).get_treatment_types(*args,**kwargs)

    @swagger_auto_schema(
        request_body=TreatmentTypeCreateUpdateSerializer,
        responses={200: TreatmentTypeListSerializer},
        tags=['TreatmentType'],
        operation_description='Treatment Types Create',
    )
    def post(self,request,*args,**kwargs):
        return TreatmentService(request=request).create_treatment_type(*args,**kwargs)


class TreatmentTypeDetailUpdateDeleteView(APIView):
    permission_classes = [IsAuthenticated]
    @swagger_auto_schema(
        request_body=TreatmentTypeCreateUpdateSerializer,
        responses={200: TreatmentTypeListSerializer},
        tags=['TreatmentType'],
        operation_description='Treatment Types Update',
    )
    def patch(self,request,*args,**kwargs):
        return TreatmentService(request=request).update_treatment_type(*args,**kwargs)

    @swagger_auto_schema(
        responses={200: TreatmentTypeListSerializer},
        tags=['TreatmentType'],
        operation_description='Treatment Types Delete',
    )
    def delete(self,request,*args,**kwargs):
        return TreatmentService(request=request).delete_treatment_type(*args,**kwargs)
