from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q, TextField
from django.db.models.functions import Cast
from django.shortcuts import redirect
from django.utils.http import urlencode
from django.views.generic import ListView

from apps.accounts.scoping import get_active_org, is_org_admin

from apps.accounts.terminology import get_terms

from .events import describe
from .models import AuditEvent


class AuditEventListView(LoginRequiredMixin, ListView):
    """The active organisation's audit log, for its admins and superusers.

    Superusers see the same organisation-scoped list here; the Django admin is
    the place to look across every organisation.
    """

    model = AuditEvent
    template_name = 'audit/event_list.html'
    context_object_name = 'events'
    paginate_by = 50

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.org = get_active_org(request)
        if self.org is None:
            return redirect('accounts:org_setup')
        if not is_org_admin(request.user, self.org):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_filters(self):
        return {
            key: self.request.GET.get(key, '').strip()[:100]
            for key in ('action', 'q')
        }

    def get_queryset(self):
        queryset = (
            AuditEvent.objects
            .filter(organization=self.org)
            .select_related('actor')
        )
        filters = self.get_filters()
        if filters['action']:
            queryset = queryset.filter(action=filters['action'])
        if filters['q']:
            # The details are JSON; searching their text finds a username, a
            # team name or a deleted record's title wherever the event put it.
            queryset = queryset.annotate(
                details_text=Cast('details', TextField()),
            ).filter(
                Q(actor_label__icontains=filters['q'])
                | Q(target_label__icontains=filters['q'])
                | Q(action__icontains=filters['q'])
                | Q(details_text__icontains=filters['q'])
            )
        return queryset

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        filters = self.get_filters()
        terms = get_terms(self.request)
        for event in ctx['events']:
            event.description = describe(event.action, terms)
        ctx['org'] = self.org
        ctx['selected_action'] = filters['action']
        ctx['query'] = filters['q']
        ctx['is_filtered'] = any(filters.values())
        # Appended to page links so the filters survive paging.
        active = {key: value for key, value in filters.items() if value}
        ctx['page_suffix'] = f'&{urlencode(active)}' if active else ''
        actions = (
            AuditEvent.objects
            .filter(organization=self.org)
            .order_by('action')
            .values_list('action', flat=True)
            .distinct()
        )
        ctx['actions'] = actions
        ctx['action_choices'] = [(action, describe(action, terms)) for action in actions]
        return ctx
