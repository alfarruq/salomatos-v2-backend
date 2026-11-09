from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken


def revoke_all_sessions(user) -> None:
    """Blacklists every refresh token of the user, so a new password signs out every device.

    Access tokens already issued stay valid until they expire (minutes); refresh
    tokens would otherwise keep an old session alive for days.
    """
    outstanding = OutstandingToken.objects.filter(user=user).exclude(blacklistedtoken__isnull=False)
    BlacklistedToken.objects.bulk_create(
        [BlacklistedToken(token=token) for token in outstanding], ignore_conflicts=True
    )
