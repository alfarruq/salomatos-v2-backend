from rest_framework.permissions import IsAuthenticated, AllowAny
from drf_yasg.utils import swagger_auto_schema
from drf_yasg  import openapi
from rest_framework.views import APIView
from apps.clinic.api.v1.serializers.admins import (
    AdminListSerializer,
    AdminCreateUpdateSerializer,
)
from apps.clinic.api.v1.services.admins import AdminService

class AdminCreateListView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        responses={200: AdminListSerializer},
        tags=['Admin'],
        operation_description='Admin List',
    )
    def get(self,request,*args,**kwargs):
        return AdminService(request=request).get_admins(*args,**kwargs)

    @swagger_auto_schema(
        request_body=AdminCreateUpdateSerializer,
        responses={200: AdminListSerializer},
        tags=['Admin'],
        operation_description='Admin Create',
    )
    def post(self,request,*args,**kwargs):
        return AdminService(request=request).create_admin(*args,**kwargs)


class AdminDetailUpdateDeleteView(APIView):
    permission_classes = [IsAuthenticated]
    @swagger_auto_schema(
        request_body=AdminCreateUpdateSerializer,
        responses={200: AdminListSerializer},
        tags=['Admin'],
        operation_description='Admin Update',
    )
    def patch(self,request,*args,**kwargs):
        return AdminService(request=request).update_admin(*args,**kwargs)

    @swagger_auto_schema(
        tags=['Admin'],
        operation_description='Admin Delete',
    )
    def delete(self,request,*args,**kwargs):
        return AdminService(request=request).delete_admin(*args,**kwargs)