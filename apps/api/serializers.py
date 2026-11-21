"""What each resource looks like over the API.

Names are the generic ones (priority, action, blocker, step) and never change
with an organisation's vocabulary. Status values are fixed strings.
"""
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accountability.models import AccountabilityNode
from apps.accounts.models import Membership, Team
from apps.issues.models import Issue
from apps.meetings.models import Headline, Meeting
from apps.rocks.models import Rock, RockCheckin, RockMilestone
from apps.scorecards.models import Scorecard, ScorecardEntry, ScorecardMetric
from apps.todos.models import ToDo
from apps.vision import structure as vision_structure

from .terminology import SEGMENT_TYPES, agenda_for

PRIORITY_STATUSES = [
    ('on_track', 'On track'), ('off_track', 'Off track'), ('complete', 'Complete'), ('dropped', 'Dropped'),
]
CONFIDENCE_CHOICES = [('on_track', 'On track'), ('off_track', 'Off track')]
ACTION_STATUSES = [('open', 'Open'), ('complete', 'Complete')]
BLOCKER_STATUSES = [
    ('open', 'Open'), ('in_discussion', 'Being worked through'), ('resolved', 'Resolved'), ('dropped', 'Dropped'),
]
BLOCKER_TYPES = [('short_term', 'Short-term'), ('long_term', 'Long-term')]
METRIC_TYPES = [('integer', 'Whole number'), ('float', 'Decimal number'), ('percentage', 'Percentage')]
GOAL_DIRECTIONS = [
    ('above', 'At or above the goal'), ('below', 'At or below the goal'), ('equal', 'Equal to the goal'),
]
METRIC_FREQUENCIES = ScorecardMetric.FREQ_CHOICES
MEETING_STATUSES = Meeting.STATUS_CHOICES
UPDATE_TYPES = [(Headline.TYPE_GOOD, 'Good news'), (Headline.TYPE_BAD, 'Concern')]
SECTION_FORMATS = [
    (vision_structure.RENDER_TEXT, 'Paragraph'),
    (vision_structure.RENDER_SINGLE_LINE, 'Single line'),
    (vision_structure.RENDER_LIST, 'List, one item per line'),
]
ORG_CHART_NODE_TYPES = [('role', 'Role'), ('department', 'Department')]
ROLES = Membership.ROLE_CHOICES
QUARTERS = Rock.QUARTER_CHOICES

# The stored value for a blocker that is being worked through is an internal
# name; the API has its own fixed word for it.
BLOCKER_STATUS_TO_API = {Issue.STATUS_IN_IDS: 'in_discussion'}
BLOCKER_STATUS_FROM_API = {api: stored for stored, api in BLOCKER_STATUS_TO_API.items()}
# Likewise for a place on the chart that one person holds.
ORG_CHART_NODE_TYPE_TO_API = {AccountabilityNode.TYPE_SEAT: 'role'}


class PersonSerializer(serializers.Serializer):
    """A user, as far as another member of the organisation needs to know them."""

    id = serializers.IntegerField()
    name = serializers.SerializerMethodField()

    def get_name(self, user) -> str:
        return user.get_full_name() or user.get_username()


class TermSerializer(serializers.Serializer):
    singular = serializers.CharField()
    plural = serializers.CharField()


class BrandingSerializer(serializers.Serializer):
    display_name = serializers.CharField()
    tagline = serializers.CharField(allow_blank=True)
    primary_color = serializers.CharField(allow_blank=True, help_text='A hex colour such as #0d6efd, or empty.')
    navbar_style = serializers.CharField()
    logo_url = serializers.CharField(allow_blank=True)
    favicon_url = serializers.CharField(allow_blank=True)


class OrganisationSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.CharField()
    branding = BrandingSerializer()
    vocabulary = serializers.DictField(
        child=TermSerializer(),
        help_text='What this organisation calls each building block, keyed by the fixed API name.',
    )
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class MeOrganisationSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class MeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    name = serializers.CharField()
    email = serializers.CharField(allow_blank=True)
    organisation = MeOrganisationSerializer()
    role = serializers.ChoiceField(choices=ROLES)
    is_organisation_admin = serializers.BooleanField()
    team_ids = serializers.ListField(child=serializers.IntegerField())
    scopes = serializers.ListField(child=serializers.CharField(), help_text='The scopes this token carries.')


class TeamSerializer(serializers.ModelSerializer):
    class Meta:
        model = Team
        fields = ['id', 'name', 'description', 'created_at', 'updated_at']


class PrioritySerializer(serializers.ModelSerializer):
    owner = PersonSerializer()
    created_by = PersonSerializer(allow_null=True)
    team_id = serializers.IntegerField()
    parent_id = serializers.IntegerField(source='parent_rock_id', allow_null=True)
    is_company_wide = serializers.BooleanField(source='is_company_rock')
    status = serializers.ChoiceField(choices=PRIORITY_STATUSES)

    class Meta:
        model = Rock
        fields = [
            'id', 'title', 'description', 'status', 'owner', 'team_id', 'is_company_wide',
            'quarter', 'year', 'due_date', 'parent_id', 'created_by', 'created_at', 'updated_at',
        ]


class StepSerializer(serializers.ModelSerializer):
    priority_id = serializers.IntegerField(source='rock_id')

    class Meta:
        model = RockMilestone
        fields = [
            'id', 'priority_id', 'title', 'description', 'due_date', 'is_complete',
            'completed_at', 'order', 'created_at',
        ]


class CheckInSerializer(serializers.ModelSerializer):
    priority_id = serializers.IntegerField(source='rock_id')
    confidence = serializers.ChoiceField(choices=CONFIDENCE_CHOICES)
    created_by = PersonSerializer(allow_null=True)

    class Meta:
        model = RockCheckin
        fields = ['id', 'priority_id', 'confidence', 'note', 'created_by', 'created_at']


class ActionSerializer(serializers.ModelSerializer):
    owner = PersonSerializer()
    team_id = serializers.IntegerField()
    priority_id = serializers.IntegerField(source='linked_rock_id', allow_null=True)
    blocker_id = serializers.IntegerField(source='linked_issue_id', allow_null=True)
    status = serializers.ChoiceField(choices=ACTION_STATUSES)

    class Meta:
        model = ToDo
        fields = [
            'id', 'title', 'description', 'status', 'owner', 'team_id', 'due_date',
            'completed_at', 'priority_id', 'blocker_id', 'created_at', 'updated_at',
        ]


@extend_schema_field(serializers.ChoiceField(choices=BLOCKER_STATUSES))
class BlockerStatusField(serializers.Field):
    def to_representation(self, value):
        return BLOCKER_STATUS_TO_API.get(value, value)


class BlockerSerializer(serializers.ModelSerializer):
    team_id = serializers.IntegerField(source='originating_team_id')
    delegated_to_team_id = serializers.IntegerField(allow_null=True)
    created_by = PersonSerializer(allow_null=True)
    type = serializers.ChoiceField(source='issue_type', choices=BLOCKER_TYPES)
    is_company_wide = serializers.BooleanField(source='is_company_issue')
    status = BlockerStatusField()
    priority_ids = serializers.SerializerMethodField()

    class Meta:
        model = Issue
        fields = [
            'id', 'title', 'description', 'status', 'type', 'team_id', 'delegated_to_team_id',
            'is_company_wide', 'priority_ids', 'target_quarter', 'target_year',
            'resolution_notes', 'created_by', 'created_at', 'updated_at',
        ]

    def get_priority_ids(self, blocker) -> list[int]:
        return sorted(rock.pk for rock in blocker.linked_rocks.all())


# ── Metrics boards ───────────────────────────────────────────────────────────

class MetricsBoardSerializer(serializers.ModelSerializer):
    team_id = serializers.IntegerField()

    class Meta:
        model = Scorecard
        fields = ['id', 'name', 'description', 'team_id', 'is_active', 'created_at', 'updated_at']


class MetricSerializer(serializers.ModelSerializer):
    metrics_board_id = serializers.IntegerField(source='scorecard_id')
    owner = PersonSerializer()
    type = serializers.ChoiceField(source='metric_type', choices=METRIC_TYPES)
    goal_direction = serializers.ChoiceField(choices=GOAL_DIRECTIONS)
    frequency = serializers.ChoiceField(choices=METRIC_FREQUENCIES)

    class Meta:
        model = ScorecardMetric
        fields = [
            'id', 'metrics_board_id', 'name', 'owner', 'type', 'goal_value', 'goal_direction',
            'frequency', 'order', 'is_active',
        ]


class EntrySerializer(serializers.ModelSerializer):
    metric_id = serializers.IntegerField()
    note = serializers.CharField(source='notes', allow_blank=True)
    entered_by = PersonSerializer(allow_null=True)

    class Meta:
        model = ScorecardEntry
        fields = ['id', 'metric_id', 'period_start', 'value', 'on_track', 'note', 'entered_by', 'created_at']
        extra_kwargs = {
            'period_start': {'help_text': 'The first day of the week or month the value is for.'},
            'on_track': {'help_text': 'Whether the value met the metric\'s goal when it was entered.'},
        }


# ── Meetings ─────────────────────────────────────────────────────────────────

class AgendaItemSerializer(serializers.Serializer):
    position = serializers.IntegerField(help_text='Place in the agenda, from 0. Notes refer to it.')
    type = serializers.ChoiceField(choices=SEGMENT_TYPES)
    name = serializers.CharField(help_text='What the organisation calls this part of the meeting.')
    duration_minutes = serializers.IntegerField()


class MeetingNoteSerializer(serializers.Serializer):
    position = serializers.IntegerField(source='segment', help_text='The agenda item the note belongs to.')
    text = serializers.CharField()
    updated_by = PersonSerializer(allow_null=True)
    updated_at = serializers.DateTimeField()


class MeetingUpdateSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    type = serializers.ChoiceField(source='headline_type', choices=UPDATE_TYPES)
    text = serializers.CharField()
    author = PersonSerializer(allow_null=True)
    blocker_id = serializers.IntegerField(
        source='escalated_issue_id', allow_null=True, help_text='The blocker this update was turned into, if any.',
    )
    created_at = serializers.DateTimeField()


class MeetingRatingSerializer(serializers.Serializer):
    participant = PersonSerializer()
    score = serializers.IntegerField(min_value=1, max_value=10)
    note = serializers.CharField(source='improvement_note', allow_blank=True)


class MeetingSerializer(serializers.ModelSerializer):
    team_id = serializers.IntegerField()
    status = serializers.ChoiceField(choices=MEETING_STATUSES)
    current_position = serializers.IntegerField(
        source='current_segment', help_text='The agenda item the meeting has reached.',
    )
    duration_minutes = serializers.IntegerField(allow_null=True, help_text='How long it ran, once it has ended.')
    agenda = serializers.SerializerMethodField(
        help_text='The agenda as it stood when the meeting was created. Later changes to the '
                  'organisation\'s agenda do not alter it.',
    )
    notes = MeetingNoteSerializer(many=True)
    updates = MeetingUpdateSerializer(source='headlines', many=True)
    ratings = MeetingRatingSerializer(many=True)
    average_rating = serializers.SerializerMethodField()
    key_messages = serializers.CharField(
        source='cascading_messages', allow_blank=True,
        help_text='What the team agreed to pass on to the rest of the organisation.',
    )
    created_by = PersonSerializer(allow_null=True)

    class Meta:
        model = Meeting
        fields = [
            'id', 'team_id', 'scheduled_date', 'status', 'started_at', 'ended_at', 'duration_minutes',
            'current_position', 'agenda', 'notes', 'updates', 'ratings', 'average_rating',
            'key_messages', 'created_by', 'created_at',
        ]

    @extend_schema_field(AgendaItemSerializer(many=True))
    def get_agenda(self, meeting):
        return agenda_for(meeting, self.context['terms'])

    @extend_schema_field(serializers.FloatField(allow_null=True))
    def get_average_rating(self, meeting):
        # From the ratings already loaded, rounded as the web shows it.
        scores = [rating.score for rating in meeting.ratings.all()]
        return round(sum(scores) / len(scores), 1) if scores else None


# ── Vision document ──────────────────────────────────────────────────────────

class ValueSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    order = serializers.IntegerField()


class VisionSectionSerializer(serializers.Serializer):
    key = serializers.CharField(help_text='Fixed name of the section within this organisation\'s document.')
    label = serializers.CharField(allow_blank=True, help_text='Empty when the group\'s label is label enough.')
    format = serializers.ChoiceField(choices=SECTION_FORMATS)
    content = serializers.CharField(allow_blank=True)
    last_edited_by = PersonSerializer(allow_null=True)
    last_edited_at = serializers.DateTimeField(allow_null=True)


class VisionGroupSerializer(serializers.Serializer):
    label = serializers.CharField()
    hint = serializers.CharField(allow_blank=True)
    sections = VisionSectionSerializer(many=True)


class VisionPageSerializer(serializers.Serializer):
    label = serializers.CharField()
    groups = VisionGroupSerializer(many=True)


class VisionBoardSerializer(serializers.Serializer):
    values = ValueSerializer(many=True)
    pages = VisionPageSerializer(
        many=True, help_text='The document in the organisation\'s own layout: pages, groups, then sections.',
    )


# ── Org chart ────────────────────────────────────────────────────────────────

class ResponsibilitySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    description = serializers.CharField()
    order = serializers.IntegerField()


@extend_schema_field(serializers.ChoiceField(choices=ORG_CHART_NODE_TYPES))
class OrgChartNodeTypeField(serializers.Field):
    def to_representation(self, value):
        return ORG_CHART_NODE_TYPE_TO_API.get(value, value)


class OrgChartNodeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    parent_id = serializers.IntegerField(allow_null=True)
    name = serializers.CharField()
    type = OrgChartNodeTypeField(source='node_type')
    owner = PersonSerializer(allow_null=True)
    is_vacant = serializers.BooleanField()
    order = serializers.IntegerField()
    responsibilities = ResponsibilitySerializer(source='roles', many=True)
    children = serializers.SerializerMethodField(help_text='The nodes directly beneath this one, in chart order.')

    @extend_schema_field({'type': 'array', 'items': {'$ref': '#/components/schemas/OrgChartNode'}})
    def get_children(self, node):
        return OrgChartNodeSerializer(node.child_nodes, many=True).data


class OrgChartSerializer(serializers.Serializer):
    nodes = OrgChartNodeSerializer(many=True, help_text='The top of the chart; each node carries its own children.')


class ProblemSerializer(serializers.Serializer):
    """RFC 9457 problem details. Every error has this shape."""

    type = serializers.CharField(default='about:blank')
    title = serializers.CharField()
    status = serializers.IntegerField()
    detail = serializers.CharField(required=False)
    errors = serializers.DictField(required=False, help_text='Present when a parameter was not valid.')
