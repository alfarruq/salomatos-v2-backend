from rest_framework import serializers
from apps.authentication.models import Gallery


class GalleryListSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    image = serializers.ImageField()
    created_at = serializers.DateTimeField()

class GalleryCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Gallery
        fields = [
            'id',
            'clinic',
            'user',
            'image',
        ]