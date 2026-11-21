"""The web pages that go with the API: the organisation's switch and a user's connections."""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import TemplateView, View

from apps.accounts.scoping import get_active_org, is_org_admin
from apps.accounts.views import AdminRequiredMixin
from apps.audit.services import record

from .models import Connection, OrganizationApiAccess


class ApiAccessView(LoginRequiredMixin, AdminRequiredMixin, TemplateView):
    """Organisation admins switch the API on or off and see who has connected what."""

    template_name = 'api/access.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        org = get_active_org(self.request)
        ctx['org'] = org
        ctx['api_enabled'] = OrganizationApiAccess.is_enabled(org)
        ctx['connections'] = (
            Connection.objects.filter(organization=org, revoked_at__isnull=True)
            .select_related('user', 'application')
        )
        return ctx

    def post(self, request):
        org = get_active_org(request)
        if org is None:
            raise Http404
        enabled = request.POST.get('enabled') == 'on'
        OrganizationApiAccess.objects.update_or_create(
            organization=org, defaults={'enabled': enabled, 'updated_by': request.user},
        )
        record(
            'api.access.enabled' if enabled else 'api.access.disabled',
            request=request, organization=org, target=org,
        )
        messages.success(request, f'API access switched {"on" if enabled else "off"} for {org.name}.')
        return redirect('api_web:access')


class ConnectionListView(LoginRequiredMixin, TemplateView):
    """The applications the signed-in user has connected, in any organisation."""

    template_name = 'api/connections.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['connections'] = (
            Connection.objects.filter(user=self.request.user, revoked_at__isnull=True)
            .select_related('application', 'organization')
        )
        return ctx


class ConnectionRevokeView(LoginRequiredMixin, View):
    """POST-only: end a connection. Its owner may, and so may an admin of its organisation."""

    def post(self, request, pk):
        connection = get_object_or_404(Connection, pk=pk, revoked_at__isnull=True)
        own = connection.user_id == request.user.pk
        org = get_active_org(request)
        as_admin = connection.organization_id == getattr(org, 'pk', None) and is_org_admin(request.user, org)
        if not (own or as_admin):
            raise Http404
        connection.revoke()
        record(
            'api.connection.revoked', request=request, organization=connection.organization,
            target=connection, details={'application': connection.application.name, 'by_admin': not own},
        )
        messages.success(request, f'{connection.application.name} is disconnected.')
        return redirect('api_web:connections' if own else 'api_web:access')
