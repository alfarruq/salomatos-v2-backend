"""Keeps organization owners a member of every branch.

Done with signals rather than a service call so that branches and owners
created through Django admin or a shell get the same access.
"""

from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver

from apps.tenancy.models import Clinic, Membership, Organization
from apps.tenancy.services import ensure_owner_membership


@receiver(post_save, sender=Clinic)
def give_owners_new_branch(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        for user in instance.organization.owners.all():
            ensure_owner_membership(instance, user)


@receiver(m2m_changed, sender=Organization.owners.through)
def give_new_owner_all_branches(sender, instance, action, pk_set, reverse, **kwargs):
    if reverse:
        return
    if action == "post_add":
        from django.contrib.auth import get_user_model

        for user in get_user_model().objects.filter(pk__in=pk_set):
            for clinic in instance.clinics.all():
                ensure_owner_membership(clinic, user)
    elif action == "post_remove":
        Membership.objects.filter(user_id__in=pk_set, clinic__organization=instance, role=Membership.Role.OWNER).update(
            is_active=False
        )
