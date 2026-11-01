from rest_framework.permissions import IsAuthenticated, AllowAny
from drf_yasg.utils import swagger_auto_schema
from drf_yasg  import openapi
from rest_framework.views import APIView
from apps.calendars.api.v1.serializers.appointments import (
    AppointmentListSerializer,
    AppointmentCreateUpdateSerializer
)
from apps.calendars.api.v1.services.appointments import AppointmentService


class AppointmentCreateListView(APIView):
    permission_classes = [IsAuthenticated]
    @swagger_auto_schema(
        responses={200: AppointmentListSerializer},
        tags=['Appointments'],
        operation_description='Appointments List',
        manual_parameters=[
            openapi.Parameter(
                name='week_day',
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description='Appointment by day and week',
                enum = ['day','week']
            ),
            openapi.Parameter(
                name = 'date',
                in_ = openapi.IN_QUERY,
                type = openapi.TYPE_STRING,
                description='Appointment by day and month and year (YYYY-MM-DD)',
            ),
            openapi.Parameter(
                name = 'doctor_id',
                in_ = openapi.IN_QUERY,
                type = openapi.TYPE_INTEGER,
                description='Appointment by doctor ID',

            )

        ]
    )
    def get(self,request,*args,**kwargs):
        return AppointmentService(request=request).get_appointments(*args, **kwargs)

    @swagger_auto_schema(
        request_body=AppointmentCreateUpdateSerializer,
        responses={200: AppointmentListSerializer},
        tags=['Appointments'],
        operation_description='Appointments Create',
    )
    def post(self,request,*args,**kwargs):
        return AppointmentService(request=request).create_appointment(*args, **kwargs)


class AppointmentDetailUpdateDeleteView(APIView):
    permission_classes = [IsAuthenticated]
    @swagger_auto_schema(
        request_body=AppointmentCreateUpdateSerializer,
        responses={200: AppointmentListSerializer},
        tags=['Appointments'],
        operation_description='Appointments Update',
    )
    def patch(self,request,*args,**kwargs):
        return AppointmentService(request=request).update_appointment(*args,**kwargs)

    @swagger_auto_schema(
        tags=['Appointments'],
        operation_description='Appointments Delete',
    )
    def delete(self,request,*args,**kwargs):
        return AppointmentService(request=request).delete_appointment(*args,**kwargs)