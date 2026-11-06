import uuid

from django.db import models


class BaseModel(models.Model):
    """UUID primary key and timestamps for every table.

    Sequential ids let anyone who sees one record guess the next, so no table
    exposes an integer key.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]
