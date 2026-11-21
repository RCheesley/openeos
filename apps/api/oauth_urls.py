"""The authorisation server's URLs, mounted at the site root.

Only what the API uses is routed: authorise, token, revoke and the two
metadata documents. The library's application-management pages, device flow,
introspection, OpenID Connect and dynamic registration are left out. The
namespace has to be ``oauth2_provider`` because the library reverses its own
URL names when it builds the metadata.
"""
from django.urls import path
from oauth2_provider import views as oauth_views

from .oauth_views import ConsentView, ProtectedResourceMetadataView

app_name = 'oauth2_provider'

urlpatterns = [
    path('o/authorize/', ConsentView.as_view(), name='authorize'),
    path('o/token/', oauth_views.TokenView.as_view(), name='token'),
    path('o/revoke_token/', oauth_views.RevokeTokenView.as_view(), name='revoke-token'),
    # RFC 8414, at the origin and in the path-component form.
    path(
        '.well-known/oauth-authorization-server',
        oauth_views.OAuthServerMetadataView.as_view(), name='oauth-server-metadata',
    ),
    path(
        '.well-known/oauth-authorization-server/<path:issuer_path>',
        oauth_views.OAuthServerMetadataView.as_view(), name='oauth-server-metadata-issuer',
    ),
    # RFC 9728, likewise. /.well-known/oauth-protected-resource/api/v1 describes the API itself.
    path(
        '.well-known/oauth-protected-resource',
        ProtectedResourceMetadataView.as_view(), name='oauth-resource-metadata',
    ),
    path(
        '.well-known/oauth-protected-resource/<path:resource_path>',
        ProtectedResourceMetadataView.as_view(), name='oauth-resource-metadata-path',
    ),
]
