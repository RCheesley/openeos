from rest_framework.throttling import SimpleRateThrottle


class TokenRateThrottle(SimpleRateThrottle):
    """Limit requests per connection, so rotating a token does not reset the count."""

    scope = 'token'

    def get_cache_key(self, request, view):
        connection = getattr(request.auth, 'api_connection', None)
        if connection is None:
            return None
        return self.cache_format % {'scope': self.scope, 'ident': f'connection-{connection.pk}'}
