from oauth2_provider.contrib.rest_framework import TokenHasScope as BaseTokenHasScope


class TokenHasScope(BaseTokenHasScope):
    """The token carries every scope in the view's ``required_scopes``.

    A view that only needs a valid token sets ``required_scopes = []``.
    """
