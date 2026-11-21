"""The consent screen and the metadata documents.

The library's authorisation view is extended so the user also chooses the
organisation the application will act in. Everything about codes, PKCE and
redirects stays the library's.
"""
from urllib.parse import urlsplit

from django import forms
from django.utils import timezone
from oauth2_provider.exceptions import OAuthToolkitError
from oauth2_provider.forms import AllowForm
from oauth2_provider.models import get_application_model
from oauth2_provider.views import AuthorizationView, OAuthProtectedResourceMetadataView
from oauthlib.oauth2.rfc6749.errors import CustomOAuth2Error

from apps.audit.services import record

from .access import api_organizations
from .models import Connection

API_ROOT = '/api/v1'


def api_resource_identifier(request):
    """The RFC 8707 resource identifier of the API on the host being asked."""
    return request.build_absolute_uri(API_ROOT)


def same_origin(request, uri):
    here, there = urlsplit(request.build_absolute_uri('/')), urlsplit(uri)
    return (here.scheme, here.netloc) == (there.scheme, there.netloc)


class ConsentForm(AllowForm):
    organization = forms.ModelChoiceField(queryset=None, empty_label=None, required=False)

    def __init__(self, *args, organizations, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['organization'].queryset = organizations
        self.fields['organization'].label_from_instance = lambda org: org.get_display_name()
        first = organizations.first()
        if first is not None:
            self.fields['organization'].initial = first.pk

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('allow') and cleaned.get('organization') is None:
            self.add_error('organization', 'Choose the organisation this application may act in.')
        return cleaned


class ConsentView(AuthorizationView):
    """Ask the user which organisation an application may act in, and with which scopes.

    Sign-in is the normal login, so two-factor applies to anyone who has it on.
    The organisation offered is one the user belongs to with the API switched
    on; on an organisation's own hostname it is that organisation alone.
    """

    form_class = ConsentForm

    def get_organizations(self):
        return api_organizations(self.request.user, getattr(self.request, 'host_org', None))

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['organizations'] = self.get_organizations()
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['organizations'] = list(self.get_organizations())
        scopes = ctx.get('scopes') or []
        descriptions = ctx.get('scopes_descriptions') or []
        ctx['scope_rows'] = list(zip(scopes, descriptions))
        return ctx

    def get(self, request, *args, **kwargs):
        refusal = self._refuse_foreign_resource(request.GET.getlist('resource'), request.GET)
        return refusal or super().get(request, *args, **kwargs)

    def form_valid(self, form):
        self._organization = form.cleaned_data.get('organization')
        refusal = self._refuse_foreign_resource(
            (form.cleaned_data.get('resource') or '').split(), form.cleaned_data
        )
        if refusal:
            return refusal
        if not form.cleaned_data.get('allow'):
            record(
                'api.connection.denied', request=self.request, organization=self._organization,
                details={'client_id': form.cleaned_data.get('client_id'), 'scope': form.cleaned_data.get('scope')},
            )
        return super().form_valid(form)

    def create_authorization_response(self, request, scopes, credentials, allow):
        if allow:
            organization = getattr(self, '_organization', None)
            if organization is None:
                # Reached without the form, which only an application set to skip
                # the consent screen does. There is then nobody to pick an organisation.
                raise OAuthToolkitError(
                    error=CustomOAuth2Error(
                        error='access_denied',
                        description='Consent is required to choose an organisation.',
                        state=credentials.get('state'),
                    ),
                    redirect_uri=credentials['redirect_uri'],
                )
            application = get_application_model().objects.get(client_id=credentials['client_id'])
            scope = scopes if isinstance(scopes, str) else ' '.join(scopes)
            connection, _ = Connection.objects.update_or_create(
                user=request.user, application=application, organization=organization,
                defaults={'scope': scope, 'approved_at': timezone.now(), 'revoked_at': None},
            )
            # A token is only good on the host it was issued for (RFC 8707).
            credentials = {**credentials, 'api_connection': connection}
            credentials.setdefault('resource', [api_resource_identifier(request)])
            record(
                'api.connection.approved', request=request, organization=organization,
                target=connection, details={'application': application.name, 'scope': scope},
            )
        return super().create_authorization_response(request, scopes, credentials, allow)

    def _refuse_foreign_resource(self, resources, params):
        """Answer ``invalid_target`` for a resource that is not on this host (RFC 8707)."""
        for uri in resources:
            if same_origin(self.request, uri):
                continue
            # Only redirect to a registered address; otherwise the library's own
            # validation, which runs next, reports the bad client or redirect.
            application = get_application_model().objects.filter(client_id=params.get('client_id')).first()
            redirect_uri = params.get('redirect_uri')
            if application is None or not redirect_uri or not application.redirect_uri_allowed(redirect_uri):
                return None
            error = OAuthToolkitError(
                error=CustomOAuth2Error(
                    error='invalid_target',
                    description=f"The resource '{uri}' is not served here.",
                    state=params.get('state'),
                ),
                redirect_uri=redirect_uri,
            )
            return self.error_response(error, application)
        return None


class ProtectedResourceMetadataView(OAuthProtectedResourceMetadataView):
    """RFC 9728 metadata, with a link to the API's human-readable docs."""

    def get_resource_documentation(self):
        return self.request.build_absolute_uri(f'{API_ROOT}/docs')
