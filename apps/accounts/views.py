from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import (
    TemplateView, CreateView, UpdateView, ListView, DetailView, FormView, View,
)
from django.db import models
from django.shortcuts import redirect, get_object_or_404, render
from django.db.models import Q
from django.utils.crypto import get_random_string
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from django.contrib.auth.models import User

from .models import Organization, Team, UserProfile
from .forms import OrganizationForm, TeamForm, UserProfileForm, InviteUserForm, TeamMemberForm


class AdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        user = self.request.user
        if not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        try:
            return user.profile.is_admin()
        except UserProfile.DoesNotExist:
            return False


def get_active_team(request):
    """Return the session-pinned team if valid, else the user's first team."""
    try:
        user_teams = request.user.profile.teams.all()
    except AttributeError:
        return None
    if not user_teams.exists():
        return None
    stored_id = request.session.get('active_team_id')
    if stored_id:
        team = user_teams.filter(pk=stored_id).first()
        if team:
            return team
    team = user_teams.first()
    request.session['active_team_id'] = team.pk
    return team


def get_user_org(user):
    try:
        return user.profile.organization
    except (UserProfile.DoesNotExist, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Home / first-run
# ---------------------------------------------------------------------------

class HomeView(LoginRequiredMixin, TemplateView):
    template_name = 'home.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if not Organization.objects.exists() and request.user.is_superuser:
                return redirect('accounts:org_setup')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        from apps.rocks.models import Rock
        from apps.issues.models import Issue
        from apps.todos.models import ToDo
        from apps.meetings.models import Meeting
        from apps.scorecards.models import ScorecardEntry, _current_week_start

        ctx = super().get_context_data(**kwargs)
        org = get_user_org(self.request.user)
        ctx['org'] = org
        team = get_active_team(self.request)

        if team:
            teams = [team]

            ctx['active_rocks'] = Rock.objects.filter(team__in=teams).exclude(
                status__in=[Rock.STATUS_COMPLETE, Rock.STATUS_DROPPED]
            ).count()
            ctx['off_track_rocks'] = Rock.objects.filter(
                team__in=teams, status=Rock.STATUS_OFF_TRACK
            ).count()

            ctx['open_issues'] = Issue.objects.filter(
                originating_team__in=teams
            ).exclude(
                status__in=[Issue.STATUS_RESOLVED, Issue.STATUS_DROPPED]
            ).count()

            ctx['open_todos'] = ToDo.objects.filter(
                status=ToDo.STATUS_OPEN
            ).filter(
                models.Q(team__in=teams) | models.Q(owner=self.request.user)
            ).count()

            ctx['next_meeting'] = Meeting.objects.filter(
                team__in=teams,
                status__in=[Meeting.STATUS_SCHEDULED, Meeting.STATUS_ACTIVE],
            ).order_by('scheduled_date').first()

            week_start = _current_week_start()
            total_entries = ScorecardEntry.objects.filter(
                metric__scorecard__team__in=teams, period_start=week_start
            ).count()
            off_track_entries = ScorecardEntry.objects.filter(
                metric__scorecard__team__in=teams, period_start=week_start, on_track=False
            ).count()
            ctx['scorecard_total'] = total_entries
            ctx['scorecard_off_track'] = off_track_entries

        return ctx


# ---------------------------------------------------------------------------
# Organization
# ---------------------------------------------------------------------------

class OrgSetupView(LoginRequiredMixin, CreateView):
    model = Organization
    form_class = OrganizationForm
    template_name = 'accounts/org_setup.html'
    success_url = reverse_lazy('home')

    def dispatch(self, request, *args, **kwargs):
        if Organization.objects.exists():
            return redirect('home')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        org = form.save()
        profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
        profile.organization = org
        profile.role = UserProfile.ROLE_ADMIN
        profile.save()
        messages.success(self.request, f'Organisation "{org.name}" is set up. Now create your first team.')
        return redirect(reverse('accounts:team_create'))


class OrgDetailView(LoginRequiredMixin, TemplateView):
    template_name = 'accounts/org_detail.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        org = get_user_org(self.request.user)
        ctx['org'] = org
        if org:
            ctx['teams'] = Team.objects.filter(organization=org).prefetch_related('members')
            ctx['members'] = (
                UserProfile.objects
                .filter(organization=org)
                .select_related('user')
                .order_by('user__first_name', 'user__username')
            )
        return ctx


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------

class TeamListView(LoginRequiredMixin, ListView):
    model = Team
    template_name = 'accounts/team_list.html'
    context_object_name = 'teams'

    def get_queryset(self):
        org = get_user_org(self.request.user)
        if not org:
            return Team.objects.none()
        return Team.objects.filter(organization=org).prefetch_related('members')


class TeamCreateView(LoginRequiredMixin, AdminRequiredMixin, CreateView):
    model = Team
    form_class = TeamForm
    template_name = 'accounts/team_form.html'
    success_url = reverse_lazy('accounts:team_list')

    def form_valid(self, form):
        org = get_user_org(self.request.user)
        if not org:
            messages.error(self.request, 'You must belong to an organisation first.')
            return redirect('home')
        form.instance.organization = org
        messages.success(self.request, f'Team "{form.instance.name}" created.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action'] = 'Create'
        return ctx


class TeamUpdateView(LoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = Team
    form_class = TeamForm
    template_name = 'accounts/team_form.html'

    def get_success_url(self):
        messages.success(self.request, 'Team updated.')
        return reverse('accounts:team_detail', kwargs={'pk': self.object.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action'] = 'Edit'
        return ctx


class TeamDetailView(LoginRequiredMixin, DetailView):
    model = Team
    template_name = 'accounts/team_detail.html'
    context_object_name = 'team'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        members = self.object.members.select_related('user').order_by('user__first_name', 'user__username')
        ctx['members'] = members
        ctx['member_form'] = TeamMemberForm(
            organization=self.object.organization,
            initial={'users': [p.user for p in members]},
        )
        ctx['is_admin'] = (
            self.request.user.is_superuser or
            getattr(getattr(self.request.user, 'profile', None), 'is_admin', lambda: False)()
        )
        return ctx


class TeamMembersUpdateView(LoginRequiredMixin, AdminRequiredMixin, FormView):
    form_class = TeamMemberForm

    def get_team(self):
        return get_object_or_404(Team, pk=self.kwargs['pk'])

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['organization'] = self.get_team().organization
        return kwargs

    def form_valid(self, form):
        team = self.get_team()
        selected_users = set(form.cleaned_data['users'])
        org_profiles = UserProfile.objects.filter(organization=team.organization)
        for profile in org_profiles:
            if profile.user in selected_users:
                profile.teams.add(team)
            else:
                profile.teams.remove(team)
        messages.success(self.request, 'Team members updated.')
        return redirect('accounts:team_detail', pk=team.pk)

    def form_invalid(self, form):
        return redirect('accounts:team_detail', pk=self.kwargs['pk'])


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = 'accounts/profile.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
        ctx['profile'] = profile
        ctx['teams'] = profile.teams.all()
        return ctx


class ProfileEditView(LoginRequiredMixin, UpdateView):
    model = UserProfile
    form_class = UserProfileForm
    template_name = 'accounts/profile_edit.html'
    success_url = reverse_lazy('accounts:profile')

    def get_object(self, queryset=None):
        profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
        return profile

    def form_valid(self, form):
        messages.success(self.request, 'Profile updated.')
        return super().form_valid(form)


# ---------------------------------------------------------------------------
# Users (admin only)
# ---------------------------------------------------------------------------

class UserListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = UserProfile
    template_name = 'accounts/user_list.html'
    context_object_name = 'profiles'

    def get_queryset(self):
        org = get_user_org(self.request.user)
        if not org:
            return UserProfile.objects.none()
        return (
            UserProfile.objects
            .filter(organization=org)
            .select_related('user')
            .prefetch_related('teams')
            .order_by('user__first_name', 'user__username')
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['org'] = get_user_org(self.request.user)
        return ctx


class UserInviteView(LoginRequiredMixin, AdminRequiredMixin, FormView):
    form_class = InviteUserForm
    template_name = 'accounts/user_invite.html'
    success_url = reverse_lazy('accounts:user_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['organization'] = get_user_org(self.request.user)
        return kwargs

    def form_valid(self, form):
        org = get_user_org(self.request.user)
        if not org:
            messages.error(self.request, 'No organisation found.')
            return redirect('home')

        user = User.objects.create_user(
            username=form.cleaned_data['username'],
            email=form.cleaned_data['email'],
            first_name=form.cleaned_data['first_name'],
            last_name=form.cleaned_data['last_name'],
            password=get_random_string(20),
        )
        profile = user.profile
        profile.organization = org
        profile.role = form.cleaned_data['role']
        profile.save()

        for team in form.cleaned_data['teams']:
            profile.teams.add(team)

        self._send_invite_email(user, org)

        messages.success(
            self.request,
            f'User "{user.username}" added. They can set their password via the '
            f'"Forgot password?" link on the login page — make sure their email is correct.',
        )
        return super().form_valid(form)

    def _send_invite_email(self, user, org):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        from apps.notifications.emails import send_user_invite_email

        reset_url = self.request.build_absolute_uri(reverse('password_reset_confirm', kwargs={
            'uidb64': urlsafe_base64_encode(force_bytes(user.pk)),
            'token': default_token_generator.make_token(user),
        }))
        send_user_invite_email(user, org, reset_url)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['org'] = get_user_org(self.request.user)
        return ctx


# ---------------------------------------------------------------------------
# Team Switcher
# ---------------------------------------------------------------------------

class TeamSwitchView(LoginRequiredMixin, View):
    """POST-only: switch the active team stored in the session."""

    def post(self, request, pk):
        try:
            team = request.user.profile.teams.get(pk=pk)
            request.session['active_team_id'] = team.pk
        except Exception:
            pass
        next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or '/'
        return redirect(next_url)


# ---------------------------------------------------------------------------
# Global search
# ---------------------------------------------------------------------------

class SearchView(LoginRequiredMixin, View):
    template_name = 'search/results.html'

    def get(self, request):
        query = request.GET.get('q', '').strip()

        if len(query) < 2:
            return render(request, self.template_name, {'query': query, 'too_short': len(query) > 0})

        # All teams the user belongs to — scope every query to this set
        try:
            user_teams = list(request.user.profile.teams.all())
        except AttributeError:
            user_teams = []

        if not user_teams:
            return render(request, self.template_name, {'query': query, 'no_teams': True})

        from apps.rocks.models import Rock
        from apps.issues.models import Issue
        from apps.todos.models import ToDo

        rocks = (
            Rock.objects
            .filter(team__in=user_teams)
            .filter(Q(title__icontains=query) | Q(description__icontains=query))
            .select_related('owner', 'team')
            .order_by('status', 'title')[:10]
        )

        issues = (
            Issue.objects
            .filter(
                Q(originating_team__in=user_teams) | Q(delegated_to_team__in=user_teams)
            )
            .filter(Q(title__icontains=query) | Q(description__icontains=query))
            .select_related('originating_team')
            .order_by('status', '-created_at')[:10]
        )

        todos = (
            ToDo.objects
            .filter(team__in=user_teams)
            .filter(Q(title__icontains=query) | Q(description__icontains=query))
            .select_related('owner', 'team')
            .order_by('status', 'due_date')[:10]
        )

        return render(request, self.template_name, {
            'query': query,
            'rocks': rocks,
            'issues': issues,
            'todos': todos,
            'total': rocks.count() + issues.count() + todos.count(),
        })
