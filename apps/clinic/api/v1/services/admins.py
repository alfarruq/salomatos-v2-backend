from apps.clinic.api.v1.repositories.admins import AdminRepository
from apps.clinic.api.v1.serializers.admins import (
    AdminListSerializer,
    AdminCreateUpdateSerializer,
)
from apps.core.services import BaseService
from rest_framework import status
from apps.authentication.models import User
from apps.core.exceptions import (
    ObjectNotFoundException,
    PermissionDeniedException,
)

class AdminService(BaseService):
    def __init__(self,request):
        super().__init__(request)
        self.db = AdminRepository()

    def get_admins(self,*args,**kwargs):
        admins = self.db.get_admins(clinic_id=self.request.user)
        return self.get_response(
            admins,
            AdminListSerializer,
            context={'request': self.request},
            many=True
        )

    def create_admin(self, *args, **kwargs):
        serializer_class = AdminCreateUpdateSerializer(
            data=self.request.data,
            context={'request': self.request}
        )
        serializer_class.is_valid(raise_exception=True)

        admin = serializer_class.save(
            role=User.Roles.ADMIN,
            clinic=self.request.user,
        )
        return self.get_response_object(
            admin,
            AdminListSerializer,
            context={'request': self.request},
        )

    def update_admin(self,*args,**kwargs):
        admin = self.db.get_doctor(user_id=kwargs.get('pk'),clinic_id=self.request.user)
        serializer_class = AdminCreateUpdateSerializer(
            instance=admin,
            data=self.request.data,
            partial=True,
            context={'request': self.request}
        )
        serializer_class.is_valid(raise_exception=True)
        serializer_class.save()
        return self.get_response_object(
            obj=admin,
            response_serializer_class=AdminListSerializer,
            context={'request': self.request}
        )

    def delete_admin(self,*args,**kwargs):
        admin = self.db.get_admin(user_id=kwargs.get('pk'),clinic_id=self.request.user)
        admin.delete()
        return self.get_response_object(
            context={'request': self.request},
            status_code=status.HTTP_204_NO_CONTENT,
        )