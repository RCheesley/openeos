"""Organisation admins manage their members: role, hand-over of records, removal."""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import FormView

from apps.audit.services import record

from .forms_members import HandOverForm, MemberRoleForm, display_name
from .members import LastAdminError, change_role, is_last_admin, reassign_records, remove_member
from .models import Membership
from .scoping import get_org_object_or_404
from .views import AdminRequiredMixin


def only_admin_message(membership):
    return (
        f'{display_name(membership.user)} is the only admin of {membership.organization.name}. '
        f'Make someone else an admin first.'
    )


class MemberViewMixin(LoginRequiredMixin, AdminRequiredMixin):
    """Load a membership of the active organisation by pk; anything else is a 404."""

    success_url = reverse_lazy('accounts:user_list')

    def dispatch(self, request, *args, **kwargs):
        # The login and admin checks run first, so a non-admin gets 403 before any lookup.
        if request.user.is_authenticated and self.test_func():
            self.membership = get_org_object_or_404(
                request, Membership.objects.select_related('user', 'organization'),
                org_lookup='organization', pk=kwargs['pk'],
            )
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['membership'] = self.membership
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['membership'] = self.membership
        ctx['member'] = self.membership.user
        ctx['member_name'] = display_name(self.membership.user)
        ctx['org'] = self.membership.organization
        return ctx

    def audit_details(self, **extra):
        return {'user_id': self.membership.user_id, 'username': self.membership.user.username, **extra}


def hand_over_details(new_owner, moved):
    details = {'moved': moved}
    if new_owner is not None:
        details['new_owner_id'] = new_owner.pk
        details['new_owner'] = new_owner.username
    return details


class MemberRoleView(MemberViewMixin, FormView):
    form_class = MemberRoleForm
    template_name = 'accounts/member_role.html'

    def form_valid(self, form):
        membership = self.membership
        role = form.cleaned_data['role']
        try:
            previous = change_role(membership, role)
        except LastAdminError:
            form.add_error('role', only_admin_message(membership))
            return self.form_invalid(form)
        name = display_name(membership.user)
        if previous == role:
            messages.info(self.request, f'{name} is already {membership.get_role_display()}.')
            return redirect(self.get_success_url())
        record(
            'member.role_changed', request=self.request,
            organization=membership.organization, target=membership.user,
            details=self.audit_details(old_role=previous, new_role=role),
        )
        messages.success(self.request, f'{name} is now {membership.get_role_display()}.')
        if membership.user == self.request.user and role != Membership.ROLE_ADMIN:
            # They have just given up the right to see the user list.
            return redirect('home')
        return redirect(self.get_success_url())


class MemberReassignView(MemberViewMixin, FormView):
    """Hand a member's live records to someone else without removing them."""

    form_class = HandOverForm
    template_name = 'accounts/member_reassign.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['removing'] = False
        return kwargs

    def form_valid(self, form):
        membership = self.membership
        new_owner = form.cleaned_data['new_owner']
        moved = reassign_records(
            membership.user, membership.organization, new_owner, form.selected_kinds()
        )
        record(
            'member.records_reassigned', request=self.request,
            organization=membership.organization, target=membership.user,
            details=self.audit_details(**hand_over_details(new_owner, moved)),
        )
        total = sum(moved.values())
        messages.success(
            self.request,
            f'{total} record{"" if total == 1 else "s"} moved from '
            f'{display_name(membership.user)} to {display_name(new_owner)}.',
        )
        return redirect(self.get_success_url())


class MemberRemoveView(MemberViewMixin, FormView):
    """Confirm, hand on live records and end the membership, all in one step."""

    form_class = HandOverForm
    template_name = 'accounts/member_confirm_remove.html'

    def blocked_reason(self):
        membership = self.membership
        if membership.user == self.request.user:
            return 'You cannot remove yourself. Ask another admin to do it.'
        if is_last_admin(membership):
            return only_admin_message(membership)
        return ''

    def get(self, request, *args, **kwargs):
        reason = self.blocked_reason()
        if reason:
            messages.error(request, reason)
            return redirect(self.get_success_url())
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        reason = self.blocked_reason()
        if reason:
            messages.error(request, reason)
            return redirect(self.get_success_url())
        return super().post(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['removing'] = True
        return kwargs

    def form_valid(self, form):
        membership = self.membership
        user, org = membership.user, membership.organization
        new_owner = form.cleaned_data['new_owner']
        details = self.audit_details(role=membership.role)
        try:
            moved = remove_member(
                membership, new_owner=new_owner,
                vacate_seats=form.cleaned_data.get('vacate_seats', False),
            )
        except LastAdminError:
            messages.error(self.request, only_admin_message(membership))
            return redirect(self.get_success_url())
        if any(moved.values()):
            record(
                'member.records_reassigned', request=self.request, organization=org,
                target=user, details={**details, **hand_over_details(new_owner, moved)},
            )
        record(
            'member.removed', request=self.request, organization=org, target=user,
            details=details,
        )
        messages.success(
            self.request,
            f'{display_name(user)} has been removed from {org.name}. Their account is kept.',
        )
        return redirect(self.get_success_url())
