import hashlib

from rest_framework.throttling import SimpleRateThrottle


class LoginUsernameThrottle(SimpleRateThrottle):
    """Caps password guesses per account, whatever address they come from.

    The per-address limit alone stops one machine, not a guesser that rotates
    addresses; this one follows the username the guesses are aimed at.
    """

    scope = "login_username"

    def get_cache_key(self, request, view):
        username = request.data.get("username") if hasattr(request.data, "get") else None
        if not isinstance(username, str) or not username.strip():
            return None
        digest = hashlib.sha256(username.strip().lower().encode()).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": digest}
