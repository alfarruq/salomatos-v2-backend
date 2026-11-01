from apps.core.exceptions import ObjectNotFoundException
from apps.core.models import (
    Recipe,
    Medicine
)

class RecipeRepository():
    def get_recipes(self,clinic_id):
        recipes = Recipe.objects.filter(clinic=clinic_id)
        return recipes

    def get_recipe(self,recipe_id,clinic_id):
        recipe = Recipe.objects.filter(id=recipe_id,clinic=clinic_id).first()
        if not recipe:
            raise ObjectNotFoundException(
                message="Recipe not found.",
                message_key="recipe_not_found",
            )
        return recipe

    def get_medicines(self):
        medicines = Medicine.objects.all()
        return medicines

    def get_medicine(self,medicine_id):
        medicine = Medicine.objects.filter(id=medicine_id).first()
        if not medicine:
            raise ObjectNotFoundException(
                message="Medicine not found.",
                message_key="medicine_not_found",
            )