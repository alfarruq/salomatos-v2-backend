from rest_framework.permissions import IsAuthenticated, AllowAny
from drf_yasg.utils import swagger_auto_schema
from drf_yasg  import openapi
from rest_framework.views import APIView
from apps.core.api.v1.serializers.recipes import (
    RecipeListSerializer,
    RecipeCreateUpdateSerializer,
    MedicineListSerializer,
    MedicineCreateUpdateSerializer
)
from apps.core.api.v1.services.recipes import RecipeService

class RecipeCreateListView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        request_body=RecipeCreateUpdateSerializer,
        responses={200: RecipeListSerializer},
        tags=['Recipe'],
        operation_description='Recipe Create',
    )
    def post(self,request,*args,**kwargs):
        return RecipeService(request=request).create_recipe(*args,**kwargs)

    @swagger_auto_schema(
        responses={200: RecipeListSerializer},
        tags=['Recipe'],
        operation_description='Recipe List',
    )
    def get(self, request, *args, **kwargs):
        return RecipeService(request=request).get_recipes(*args, **kwargs)


class RecipeDetailUpdateDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        tags=['Recipe'],
        operation_description='Recipe Delete',
    )
    def delete(self,request,*args,**kwargs):
        return RecipeService(request=request).delete_recipe(*args,**kwargs)


