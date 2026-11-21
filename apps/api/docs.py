"""The browsable docs page and the page its sign-in returns to.

Swagger UI signs in through a pop-up window and reads the result back from
it. The browser only keeps the two windows connected while every page the
pop-up passes through sends the same Cross-Origin-Opener-Policy. The sign-in
and consent pages send Django's default (``same-origin``), so the docs page
and the return page must send it too. drf-spectacular's own views relax the
header on the docs page and redirect to a static file that carries no header,
which suits a sign-in service on another address but breaks one on this
address, leaving a blank pop-up.
"""
from django.http import HttpResponse
from django.templatetags.static import static
from django.views import View
from drf_spectacular.utils import extend_schema
from drf_spectacular.views import SpectacularSwaggerView

RETURN_SCRIPT = 'drf_spectacular_sidecar/swagger-ui-dist/oauth2-redirect.js'


class DocsView(SpectacularSwaggerView):
    @extend_schema(exclude=True)
    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        # Let SecurityMiddleware apply the site-wide policy.
        del response.headers['Cross-Origin-Opener-Policy']
        return response


class DocsSignInReturnView(View):
    """Serve Swagger UI's sign-in return page from the app, so it gets the site's headers."""

    def get(self, request):
        return HttpResponse(
            '<!doctype html>\n<html lang="en">\n<head><title>Signing in</title></head>\n'
            f'<body>\n<script src="{static(RETURN_SCRIPT)}"></script>\n</body>\n</html>\n'
        )
