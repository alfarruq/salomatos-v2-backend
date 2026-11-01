from apps.core.exceptions import ObjectNotFoundException
from apps.authentication.models import Gallery

class GalleryRepository:
    def get_galleries(self,clinic_id):
        gallery = Gallery.objects.filter(clinic=clinic_id)
        return gallery

    def get_gallery(self,gallery_id,clinic_id):
        gallery = Gallery.objects.filter(id=gallery_id,clinic=clinic_id).first()
        if not gallery:
            raise ObjectNotFoundException(
                message="Gallery not found",
                message_key="gallery_not_found",
            )
        return gallery
