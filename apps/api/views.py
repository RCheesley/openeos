"""Read endpoints.

Who may see what is decided by the same helpers the web pages use
(``apps.accounts.scoping`` and ``team_scope``); nothing here adds a rule.

* A record reached by id is any record of the token's organisation, as on the
  web's detail pages (``OrgScopedMixin`` / ``get_org_object_or_404``). Anything
  else answers 404.
* A list covers the teams the caller may list on the web with "all teams"
  chosen (``get_visible_teams``): their own teams, or every team for an
  organisation admin.
* The vision document and the org chart belong to the organisation and not to
  a team: every member reads them whole, as on the web.

When a model gains its own visibility method (private priorities, #115), it is
applied in ``get_queryset`` here and in the web view alike.
"""
from datetime import timezone as dt_timezone

from django.db.models import Q
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.timezone import is_naive, make_aware
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import generics
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accountability.views import _build_tree
from apps.accounts.branding import brand_for
from apps.accounts.models import Membership, Team
from apps.accounts.scoping import OrgScopedMixin, get_active_org, get_org_object_or_404, is_org_admin
from apps.accounts.team_scope import get_visible_teams
from apps.accounts.terminology import terms_for
from apps.issues.models import Issue
from apps.meetings.models import Meeting
from apps.rocks.models import Rock, RockCheckin, RockMilestone
from apps.scorecards.models import Scorecard, ScorecardEntry, ScorecardMetric
from apps.todos.models import ToDo
from apps.vision.models import VTO
from apps.vision.structure import structure_for

from . import scopes
from .serializers import (
    ACTION_STATUSES, BLOCKER_STATUS_FROM_API, BLOCKER_STATUSES, BLOCKER_TYPES, MEETING_STATUSES,
    PRIORITY_STATUSES, ActionSerializer, BlockerSerializer, CheckInSerializer, EntrySerializer,
    MeetingSerializer, MeSerializer, MetricsBoardSerializer, MetricSerializer, OrganisationSerializer,
    OrgChartSerializer, PrioritySerializer, StepSerializer, TeamSerializer, VisionBoardSerializer,
)
from .terminology import vocabulary_for

ISSUE_ORG_LOOKUP = 'originating_team__organization'

UPDATED_SINCE = OpenApiParameter(
    'updated_since', OpenApiTypes.DATETIME,
    description='Only records changed at or after this time (ISO 8601). What a sync client polls with.',
)
TEAM = OpenApiParameter('team', OpenApiTypes.INT, description='Only records of this team.')
BY_ID = 'Any {} of the organisation, as on the web. Anything else answers 404.'
BOOLEANS = [('true', ''), ('false', '')]
ID_ORDERINGS = {'id': ('id',), '-id': ('-id',)}


def choice_parameter(name, choices, description):
    return OpenApiParameter(name, OpenApiTypes.STR, enum=[value for value, _ in choices], description=description)


# ── Query parameters ─────────────────────────────────────────────────────────

def updated_since(request):
    raw = request.query_params.get('updated_since')
    if raw is None:
        return None
    try:
        moment = parse_datetime(raw)
    except ValueError:
        moment = None
    if moment is None:
        raise ValidationError({'updated_since': 'Enter an ISO 8601 date and time, such as 2026-11-20T09:30:00Z.'})
    return make_aware(moment, dt_timezone.utc) if is_naive(moment) else moment


def integer_param(request, name):
    raw = request.query_params.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        raise ValidationError({name: 'Enter a whole number.'}) from None


def date_param(request, name):
    raw = request.query_params.get(name)
    if raw is None:
        return None
    try:
        day = parse_date(raw)
    except ValueError:
        day = None
    if day is None:
        raise ValidationError({name: 'Enter a date, such as 2026-11-20.'})
    return day


def boolean_param(request, name):
    raw = choice_param(request, name, BOOLEANS)
    return None if raw is None else raw == 'true'


def choice_param(request, name, choices):
    raw = request.query_params.get(name)
    if raw is None:
        return None
    allowed = [value for value, _ in choices]
    if raw not in allowed:
        raise ValidationError({name: f'Choose one of: {", ".join(allowed)}.'})
    return raw


class UpdatedSinceMixin:
    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        since = updated_since(self.request)
        return queryset if since is None else queryset.filter(updated_at__gte=since)


# ── Organisation and caller ──────────────────────────────────────────────────

class OrganisationView(APIView):
    required_scopes = [scopes.ORGANISATION_READ]

    @extend_schema(
        operation_id='organisation_retrieve', tags=['Organisation'], responses=OrganisationSerializer,
        summary='The organisation this token acts in',
        description='Its name, branding and the words it uses for each building block.',
    )
    def get(self, request):
        org = get_active_org(request)
        brand = brand_for(org)
        absolute = lambda url: request.build_absolute_uri(url) if url else ''  # noqa: E731
        return Response(OrganisationSerializer({
            'id': org.pk, 'name': org.name, 'slug': org.slug,
            'branding': {
                'display_name': brand.name, 'tagline': brand.tagline,
                'primary_color': brand.primary_color, 'navbar_style': brand.navbar_style,
                'logo_url': absolute(brand.logo_url), 'favicon_url': absolute(brand.favicon_url),
            },
            'vocabulary': vocabulary_for(org),
            'created_at': org.created_at, 'updated_at': org.updated_at,
        }).data)


class MeView(APIView):
    """Needs a valid token and no particular scope."""

    required_scopes = []

    @extend_schema(
        operation_id='me_retrieve', tags=['Organisation'], responses=MeSerializer,
        summary='The caller, and their role in the organisation',
        description='Needs a valid token and no particular scope.',
    )
    def get(self, request):
        user, org = request.user, get_active_org(request)
        membership = Membership.objects.filter(user=user, organization=org).first()
        return Response(MeSerializer({
            'id': user.pk, 'username': user.get_username(),
            'name': user.get_full_name() or user.get_username(), 'email': user.email,
            'organisation': {'id': org.pk, 'name': org.name},
            'role': membership.role if membership else Membership.ROLE_MEMBER,
            'is_organisation_admin': is_org_admin(user, org),
            'team_ids': sorted(user.profile.teams.filter(organization=org).values_list('pk', flat=True)),
            'scopes': sorted(request.auth.scope.split()),
        }).data)


# ── Teams ────────────────────────────────────────────────────────────────────

class TeamQuerysetMixin(OrgScopedMixin):
    """Every team of the organisation, as on the web's team list."""

    queryset = Team.objects.all()
    org_lookup = 'organization'
    serializer_class = TeamSerializer
    required_scopes = [scopes.TEAMS_READ]


@extend_schema_view(get=extend_schema(
    tags=['Teams'], summary='List teams', parameters=[UPDATED_SINCE],
    description='Every team of the organisation.',
))
class TeamListView(UpdatedSinceMixin, TeamQuerysetMixin, generics.ListAPIView):
    pass


@extend_schema_view(get=extend_schema(
    tags=['Teams'], summary='Get one team', description=BY_ID.format('team'),
))
class TeamDetailView(TeamQuerysetMixin, generics.RetrieveAPIView):
    pass


# ── Priorities ───────────────────────────────────────────────────────────────

class PriorityQuerysetMixin(OrgScopedMixin):
    queryset = Rock.objects.select_related('owner', 'created_by')
    serializer_class = PrioritySerializer
    required_scopes = [scopes.PRIORITIES_READ]


@extend_schema_view(get=extend_schema(
    tags=['Priorities'], summary='List priorities',
    description=(
        'Priorities of the teams you may list on the web: your own, '
        'or every team if you are an organisation admin.'
    ),
    parameters=[
        UPDATED_SINCE, TEAM,
        choice_parameter('status', PRIORITY_STATUSES, 'Only priorities with this status.'),
        OpenApiParameter('quarter', OpenApiTypes.INT, enum=[1, 2, 3, 4], description='Only this quarter.'),
        OpenApiParameter('year', OpenApiTypes.INT, description='Only this year.'),
    ],
))
class PriorityListView(UpdatedSinceMixin, PriorityQuerysetMixin, generics.ListAPIView):
    def get_queryset(self):
        return super().get_queryset().filter(team__in=get_visible_teams(self.request))

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        request = self.request
        filters = {
            'team_id': integer_param(request, 'team'),
            'status': choice_param(request, 'status', PRIORITY_STATUSES),
            'quarter': integer_param(request, 'quarter'),
            'year': integer_param(request, 'year'),
        }
        return queryset.filter(**{key: value for key, value in filters.items() if value is not None})


@extend_schema_view(get=extend_schema(
    tags=['Priorities'], summary='Get one priority', description=BY_ID.format('priority'),
))
class PriorityDetailView(PriorityQuerysetMixin, generics.RetrieveAPIView):
    pass


class PriorityChildListView(generics.ListAPIView):
    """A list that hangs off one priority, which must be in the token's organisation."""

    required_scopes = [scopes.PRIORITIES_READ]

    def get_priority(self):
        return get_org_object_or_404(self.request, Rock, pk=self.kwargs['pk'])


@extend_schema_view(get=extend_schema(
    tags=['Steps'], summary='List the steps of a priority', description='In the order they are shown on the web.',
))
class StepListView(PriorityChildListView):
    queryset = RockMilestone.objects.none()  # for the schema; get_queryset decides
    serializer_class = StepSerializer
    orderings = {'order': ('order', 'id'), '-order': ('-order', '-id'), 'id': ('id',), '-id': ('-id',)}
    default_ordering = 'order'

    def get_queryset(self):
        return self.get_priority().milestones.all()


@extend_schema_view(get=extend_schema(
    tags=['Check-ins'], summary='List the check-ins on a priority', description='Newest first.',
))
class CheckInListView(PriorityChildListView):
    queryset = RockCheckin.objects.none()
    serializer_class = CheckInSerializer
    orderings = {'-id': ('-id',), 'id': ('id',)}
    default_ordering = '-id'

    def get_queryset(self):
        return self.get_priority().checkins.select_related('created_by')


# ── Actions ──────────────────────────────────────────────────────────────────

class ActionQuerysetMixin(OrgScopedMixin):
    queryset = ToDo.objects.select_related('owner')
    serializer_class = ActionSerializer
    required_scopes = [scopes.ACTIONS_READ]


@extend_schema_view(get=extend_schema(
    tags=['Actions'], summary='List actions',
    description='Actions of the teams you may list on the web, plus any you own.',
    parameters=[
        UPDATED_SINCE, TEAM,
        choice_parameter('status', ACTION_STATUSES, 'Only actions with this status.'),
        OpenApiParameter('mine', OpenApiTypes.BOOL, description='`true` for only the caller\'s own actions.'),
    ],
))
class ActionListView(UpdatedSinceMixin, ActionQuerysetMixin, generics.ListAPIView):
    def get_queryset(self):
        # The teams the caller may list, plus anything they own, as the dashboard counts them.
        return super().get_queryset().filter(
            Q(team__in=get_visible_teams(self.request)) | Q(owner=self.request.user)
        )

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        request = self.request
        team, status = integer_param(request, 'team'), choice_param(request, 'status', ACTION_STATUSES)
        mine = choice_param(request, 'mine', BOOLEANS)
        if team is not None:
            queryset = queryset.filter(team_id=team)
        if status is not None:
            queryset = queryset.filter(status=status)
        if mine == 'true':
            queryset = queryset.filter(owner=request.user)
        return queryset


@extend_schema_view(get=extend_schema(
    tags=['Actions'], summary='Get one action', description=BY_ID.format('action'),
))
class ActionDetailView(ActionQuerysetMixin, generics.RetrieveAPIView):
    pass


# ── Blockers ─────────────────────────────────────────────────────────────────

class BlockerQuerysetMixin(OrgScopedMixin):
    queryset = Issue.objects.select_related('created_by').prefetch_related('linked_rocks')
    org_lookup = ISSUE_ORG_LOOKUP
    serializer_class = BlockerSerializer
    required_scopes = [scopes.BLOCKERS_READ]


@extend_schema_view(get=extend_schema(
    tags=['Blockers'], summary='List blockers',
    description='Blockers raised by, or handed to, the teams you may list on the web.',
    parameters=[
        UPDATED_SINCE,
        OpenApiParameter(
            'team', OpenApiTypes.INT,
            description='Only blockers raised by this team or handed to it.',
        ),
        choice_parameter('status', BLOCKER_STATUSES, 'Only blockers with this status.'),
        choice_parameter('type', BLOCKER_TYPES, 'Only short-term or long-term blockers.'),
    ],
))
class BlockerListView(UpdatedSinceMixin, BlockerQuerysetMixin, generics.ListAPIView):
    def get_queryset(self):
        # Raised by a team the caller may list, or handed to one: the web's
        # blocker list and its "delegated" view together.
        teams = get_visible_teams(self.request)
        return super().get_queryset().filter(
            Q(originating_team__in=teams) | Q(delegated_to_team__in=teams)
        )

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        request = self.request
        team = integer_param(request, 'team')
        status = choice_param(request, 'status', BLOCKER_STATUSES)
        issue_type = choice_param(request, 'type', BLOCKER_TYPES)
        if team is not None:
            queryset = queryset.filter(Q(originating_team_id=team) | Q(delegated_to_team_id=team))
        if status is not None:
            queryset = queryset.filter(status=BLOCKER_STATUS_FROM_API.get(status, status))
        if issue_type is not None:
            queryset = queryset.filter(issue_type=issue_type)
        return queryset


@extend_schema_view(get=extend_schema(
    tags=['Blockers'], summary='Get one blocker', description=BY_ID.format('blocker'),
))
class BlockerDetailView(BlockerQuerysetMixin, generics.RetrieveAPIView):
    pass


# ── Metrics boards ───────────────────────────────────────────────────────────

class MetricsBoardQuerysetMixin(OrgScopedMixin):
    queryset = Scorecard.objects.all()
    serializer_class = MetricsBoardSerializer
    required_scopes = [scopes.METRICS_BOARDS_READ]


@extend_schema_view(get=extend_schema(
    tags=['Metrics Boards'], summary='List metrics boards',
    description=(
        'Metrics boards of the teams you may list on the web: your own, or every team if you are '
        'an organisation admin. The web lists the active ones; pass `is_active=true` for the same.'
    ),
    parameters=[
        UPDATED_SINCE, TEAM,
        OpenApiParameter('is_active', OpenApiTypes.BOOL, description='Only boards that are, or are not, in use.'),
    ],
))
class MetricsBoardListView(UpdatedSinceMixin, MetricsBoardQuerysetMixin, generics.ListAPIView):
    def get_queryset(self):
        return super().get_queryset().filter(team__in=get_visible_teams(self.request))

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        filters = {
            'team_id': integer_param(self.request, 'team'),
            'is_active': boolean_param(self.request, 'is_active'),
        }
        return queryset.filter(**{key: value for key, value in filters.items() if value is not None})


@extend_schema_view(get=extend_schema(
    tags=['Metrics Boards'], summary='Get one metrics board', description=BY_ID.format('metrics board'),
))
class MetricsBoardDetailView(MetricsBoardQuerysetMixin, generics.RetrieveAPIView):
    pass


@extend_schema_view(get=extend_schema(
    tags=['Metrics'], summary='List the metrics on a board',
    description='In the order they are shown on the web. The web shows the active ones.',
    parameters=[
        OpenApiParameter('is_active', OpenApiTypes.BOOL, description='Only metrics that are, or are not, in use.'),
    ],
))
class MetricListView(generics.ListAPIView):
    """The metrics of one board, which must be in the token's organisation."""

    queryset = ScorecardMetric.objects.none()  # for the schema; get_queryset decides
    serializer_class = MetricSerializer
    required_scopes = [scopes.METRICS_BOARDS_READ]
    orderings = {'order': ('order', 'id'), '-order': ('-order', '-id'), **ID_ORDERINGS}
    default_ordering = 'order'

    def get_queryset(self):
        board = get_org_object_or_404(self.request, Scorecard, pk=self.kwargs['pk'])
        return board.metrics.select_related('owner')

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        is_active = boolean_param(self.request, 'is_active')
        return queryset if is_active is None else queryset.filter(is_active=is_active)


@extend_schema_view(get=extend_schema(
    tags=['Entries'], summary='List the values entered for a metric',
    description='One entry per week or month, newest period first.',
    parameters=[
        OpenApiParameter('from', OpenApiTypes.DATE, description='Only periods starting on or after this date.'),
        OpenApiParameter('to', OpenApiTypes.DATE, description='Only periods starting on or before this date.'),
    ],
))
class EntryListView(generics.ListAPIView):
    """The entries of one metric, which must sit on the named board in the token's organisation."""

    queryset = ScorecardEntry.objects.none()
    serializer_class = EntrySerializer
    required_scopes = [scopes.METRICS_BOARDS_READ]
    orderings = {
        '-period_start': ('-period_start', '-id'), 'period_start': ('period_start', 'id'), **ID_ORDERINGS,
    }
    default_ordering = '-period_start'

    def get_queryset(self):
        metric = get_org_object_or_404(
            self.request, ScorecardMetric, org_lookup='scorecard__team__organization',
            pk=self.kwargs['metric_id'], scorecard_id=self.kwargs['pk'],
        )
        return metric.entries.select_related('entered_by')

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        start, end = date_param(self.request, 'from'), date_param(self.request, 'to')
        if start is not None:
            queryset = queryset.filter(period_start__gte=start)
        if end is not None:
            queryset = queryset.filter(period_start__lte=end)
        return queryset


# ── Meetings ─────────────────────────────────────────────────────────────────

class MeetingQuerysetMixin(OrgScopedMixin):
    queryset = Meeting.objects.select_related('created_by').prefetch_related(
        'notes__updated_by', 'headlines__author', 'ratings__participant',
    )
    serializer_class = MeetingSerializer
    required_scopes = [scopes.MEETINGS_READ]

    def get_serializer_context(self):
        # Agenda items take their names from the organisation's current vocabulary.
        return {**super().get_serializer_context(), 'terms': terms_for(get_active_org(self.request))}


@extend_schema_view(get=extend_schema(
    tags=['Meetings'], summary='List meetings',
    description=(
        'Meetings of the teams you may list on the web: your own, or every team if you are an '
        'organisation admin. A meeting records no time of last change, so this list has no '
        '`updated_since`; narrow it by date instead.'
    ),
    parameters=[
        TEAM,
        choice_parameter('status', MEETING_STATUSES, 'Only meetings with this status.'),
        OpenApiParameter('from', OpenApiTypes.DATE, description='Only meetings scheduled on or after this date.'),
        OpenApiParameter('to', OpenApiTypes.DATE, description='Only meetings scheduled on or before this date.'),
    ],
))
class MeetingListView(MeetingQuerysetMixin, generics.ListAPIView):
    orderings = {
        **ID_ORDERINGS,
        'scheduled_date': ('scheduled_date', 'id'), '-scheduled_date': ('-scheduled_date', '-id'),
    }

    def get_queryset(self):
        return super().get_queryset().filter(team__in=get_visible_teams(self.request))

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        request = self.request
        filters = {
            'team_id': integer_param(request, 'team'),
            'status': choice_param(request, 'status', MEETING_STATUSES),
            'scheduled_date__gte': date_param(request, 'from'),
            'scheduled_date__lte': date_param(request, 'to'),
        }
        return queryset.filter(**{key: value for key, value in filters.items() if value is not None})


@extend_schema_view(get=extend_schema(
    tags=['Meetings'], summary='Get one meeting', description=BY_ID.format('meeting'),
))
class MeetingDetailView(MeetingQuerysetMixin, generics.RetrieveAPIView):
    pass


# ── Vision document and org chart ────────────────────────────────────────────

class VisionBoardView(APIView):
    required_scopes = [scopes.VISION_BOARD_READ]

    @extend_schema(
        operation_id='vision_board_retrieve', tags=['Vision Board'], responses=VisionBoardSerializer,
        summary='The organisation\'s vision document',
        description=(
            'Its values, then its sections in the organisation\'s own layout. Every member of the '
            'organisation sees the whole document, as on the web. A section nobody has written yet '
            'is returned with empty content.'
        ),
    )
    def get(self, request):
        org = get_active_org(request)
        # Reading must not create the document, so there may be none yet.
        board = VTO.objects.filter(organization=org).first()
        stored = {s.key: s for s in board.sections.select_related('last_edited_by')} if board else {}

        def section(spec):
            row = stored.get(spec.key)
            return {
                'key': spec.key, 'label': spec.label, 'format': spec.render_as,
                'content': row.content if row else '',
                'last_edited_by': row.last_edited_by if row else None,
                'last_edited_at': row.last_edited_at if row else None,
            }

        return Response(VisionBoardSerializer({
            'values': board.core_values.all() if board else [],
            'pages': [
                {
                    'label': page.label,
                    'groups': [
                        {
                            'label': group.label, 'hint': group.hint,
                            'sections': [section(spec) for spec in group.sections],
                        }
                        for group in page.groups
                    ],
                }
                for page in structure_for(org)
            ],
        }).data)


class OrgChartView(APIView):
    required_scopes = [scopes.ORG_CHART_READ]

    @extend_schema(
        operation_id='org_chart_retrieve', tags=['Org Chart'], responses=OrgChartSerializer,
        summary='The organisation\'s chart of roles',
        description=(
            'The whole chart as a tree: each node, who holds it and what it is responsible for. '
            'Every member of the organisation sees it, as on the web.'
        ),
    )
    def get(self, request):
        # The same tree the web's chart page draws.
        return Response(OrgChartSerializer({'nodes': _build_tree(get_active_org(request))}).data)


# ── Anything else under /api/v1/ ─────────────────────────────────────────────

class NotFoundView(APIView):
    """An unknown API address answers in the API's error format, not with an HTML page."""

    authentication_classes = []
    permission_classes = []
    throttle_classes = []
    schema = None

    def initial(self, request, *args, **kwargs):
        raise NotFound()
