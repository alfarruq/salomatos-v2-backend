from apps.core.api.v1.repositories.recipes import RecipeRepository
from apps.core.api.v1.serializers.recipes import (
    RecipeListSerializer,
    RecipeCreateUpdateSerializer,
    MedicineListSerializer,
    MedicineCreateUpdateSerializer
)
from apps.core.services import BaseService
from rest_framework import status

class RecipeService(BaseService):
    def __init__(self,request):
        super().__init__(request)
        self.db = RecipeRepository()

    def create_recipe(self, *args, **kwargs):
        serializer_class = RecipeCreateUpdateSerializer(
            data=self.request.data, context={'request': self.request}
        )
        serializer_class.is_valid(raise_exception=True)
        recipe = serializer_class.save(clinic=self.request.user)
        return self.get_response_object(
            recipe,
            RecipeListSerializer,
            context={'request': self.request},
        )

    def get_recipes(self,*args,**kwargs):
        recipes = self.db.get_recipes(clinic_id=self.request.user)
        return self.get_response(
            recipes,
            RecipeListSerializer,
            context={'request': self.request},
            many=True
        )

    def delete_recipe(self,*args,**kwargs):
        recipe = self.db.get_recipe(recipe_id=kwargs.get('pk'),clinic_id=self.request.user)
        recipe.delete()
        return self.get_response_object(
            context={'request': self.request},
            status_code=status.HTTP_204_NO_CONTENT,
        )




