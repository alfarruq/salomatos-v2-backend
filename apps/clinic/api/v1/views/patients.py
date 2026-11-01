from rest_framework.permissions import IsAuthenticated, AllowAny
from drf_yasg.utils import swagger_auto_schema
from drf_yasg  import openapi
from rest_framework.views import APIView
from apps.clinic.api.v1.serializers.patients import (
    PatientListSerializer,
    PatientCreateUpdateSerializer,
    PatientDetailSerializer,
)
from apps.clinic.api.v1.services.patients import PatientService


class PatientCreateListView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        responses={200: PatientListSerializer},
        tags=['Patient'],
        operation_description='Patient List',
        manual_parameters=[
            openapi.Parameter(
                name='search',
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description='Search by patient name',

            ),
            openapi.Parameter(
                name='status',
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                enum=['pending', 'in_progress', 'completed'],
                description='Filter by appointment status',
            ),
            openapi.Parameter(
                name='doctor',
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description='Filter patient by doctor',
            ),
            openapi.Parameter(
                name='treatment_id',
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_INTEGER,
                description='Filter patient by treatment',
            )

        ],
    )
    def get(self,request,*args,**kwargs):
        return PatientService(request=request).get_patients(*args,**kwargs)

    @swagger_auto_schema(
        request_body=PatientCreateUpdateSerializer,
        responses={200: PatientListSerializer},
        tags=['Patient'],
        operation_description='Patient Create',
    )
    def post(self,request,*args,**kwargs):
        return PatientService(request=request).create_patient(*args,**kwargs)

class PatientDetailUpdateDeleteView(APIView):
    permission_classes = [IsAuthenticated]
    @swagger_auto_schema(
        responses={200: PatientDetailSerializer},
        tags=['Patient'],
        operation_description='Patient Detail ',
    )
    def get(self,request,*args,**kwargs):
        return PatientService(request=request).get_patient(*args,**kwargs)


    @swagger_auto_schema(
        request_body=PatientCreateUpdateSerializer,
        responses={200: PatientListSerializer},
        tags=['Patient'],
        operation_description='Patient Update',
    )
    def patch(self,request,*args,**kwargs):
        return PatientService(request=request).update_patient(*args,**kwargs)


