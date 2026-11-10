from rest_framework_simplejwt.tokens import RefreshToken

# Platform tokens carry this claim; clinic endpoints refuse them and platform
# endpoints refuse everything else, so one login never opens the other side.
SCOPE_CLAIM = "scope"
PLATFORM_SCOPE = "platform"


def platform_refresh_for(user) -> RefreshToken:
    refresh = RefreshToken.for_user(user)
    refresh[SCOPE_CLAIM] = PLATFORM_SCOPE
    return refresh


def is_platform_token(token) -> bool:
    return token is not None and hasattr(token, "get") and token.get(SCOPE_CLAIM) == PLATFORM_SCOPE
