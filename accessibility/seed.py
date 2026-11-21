"""A small, realistic organisation for the accessibility check to look at.

Empty pages hide most problems (no badges, no tables, no status colours), so
every page the check visits gets a few records in each state it can show.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User

from apps.accountability.models import AccountabilityNode, AccountabilityRole
from apps.accounts.models import Membership, Organization, Team
from apps.issues.models import Issue
from apps.meetings.models import Headline, Meeting, MeetingRating
from apps.rocks.models import Rock, RockCheckin, RockMilestone
from apps.scorecards.models import Scorecard, ScorecardEntry, ScorecardMetric
from apps.todos.models import ToDo
from apps.vision.models import VTO, VTOCoreValue, VTOSection

USERNAME = 'morgan'
PASSWORD = 'a11y-check-passphrase'


def seed():
    """Create the organisation and return the ids the page list needs."""
    today = date.today()
    quarter = (today.month - 1) // 3 + 1
    quarter_end = date(today.year, *Rock.QUARTER_END[quarter])
    monday = today - timedelta(days=today.weekday())

    org = Organization.objects.create(name='Harbour Lights Ltd', tagline='Lighting for working harbours')
    leadership = Team.objects.create(organization=org, name='Leadership')
    operations = Team.objects.create(organization=org, name='Operations')

    admin = User.objects.create_user(
        username=USERNAME, password=PASSWORD, email='morgan@example.com',
        first_name='Morgan', last_name='Ellis',
    )
    colleague = User.objects.create_user(
        username='priya', password=PASSWORD, email='priya@example.com',
        first_name='Priya', last_name='Shah',
    )
    Membership.objects.create(user=admin, organization=org, role=Membership.ROLE_ADMIN)
    Membership.objects.create(user=colleague, organization=org)
    admin.profile.teams.add(leadership, operations)
    colleague.profile.teams.add(leadership)

    rocks = [
        Rock.objects.create(
            title=title, owner=owner, team=leadership, quarter=quarter, year=today.year,
            due_date=quarter_end, status=status, is_company_rock=company, created_by=admin,
            description='Agreed at the quarterly planning day.',
        )
        for title, owner, status, company in [
            ('Open the Plymouth depot', admin, Rock.STATUS_ON_TRACK, True),
            ('Replace the scheduling system', colleague, Rock.STATUS_OFF_TRACK, False),
            ('Hire two service engineers', admin, Rock.STATUS_COMPLETE, False),
            ('Launch the reseller programme', colleague, Rock.STATUS_DROPPED, False),
        ]
    ]
    rock = rocks[0]
    RockMilestone.objects.create(rock=rock, title='Sign the lease', is_complete=True, order=1)
    RockMilestone.objects.create(
        rock=rock, title='Fit out the workshop', due_date=today + timedelta(days=21), order=2,
    )
    RockCheckin.objects.create(rock=rock, note='Lease signed, fit-out quotes are in.', created_by=admin)
    RockCheckin.objects.create(
        rock=rocks[1], confidence=Rock.STATUS_OFF_TRACK,
        note='Supplier has slipped the pilot by three weeks.', created_by=colleague,
    )

    issues = [
        Issue.objects.create(
            title=title, originating_team=leadership, created_by=admin, status=status,
            issue_type=issue_type, description='Raised in the weekly meeting.',
        )
        for title, status, issue_type in [
            ('Engineers double-booked on Fridays', Issue.STATUS_OPEN, Issue.TYPE_SHORT_TERM),
            ('Quote turnaround is over five days', Issue.STATUS_IN_IDS, Issue.TYPE_SHORT_TERM),
            ('Van lease renewal terms', Issue.STATUS_RESOLVED, Issue.TYPE_SHORT_TERM),
            ('No succession plan for the workshop lead', Issue.STATUS_OPEN, Issue.TYPE_LONG_TERM),
        ]
    ]
    issues[0].linked_rocks.add(rocks[1])

    ToDo.objects.create(
        title='Send the fit-out quotes to finance', owner=admin, team=leadership,
        due_date=today + timedelta(days=3), linked_rock=rock,
    )
    ToDo.objects.create(
        title='Call the scheduling supplier', owner=colleague, team=leadership,
        due_date=today - timedelta(days=2), linked_issue=issues[0],
    )
    ToDo.objects.create(
        title='Book the planning day venue', owner=admin, team=leadership,
        due_date=today - timedelta(days=5), status=ToDo.STATUS_COMPLETE,
    )

    scorecard = Scorecard.objects.create(name='Leadership weekly numbers', team=leadership)
    metrics = [
        ScorecardMetric.objects.create(
            scorecard=scorecard, name=name, owner=owner, metric_type=metric_type,
            goal_value=Decimal(goal), goal_direction=direction, order=order,
        )
        for order, (name, owner, metric_type, goal, direction) in enumerate([
            ('Quotes sent', admin, ScorecardMetric.TYPE_INTEGER, '12', ScorecardMetric.DIR_ABOVE),
            ('First-visit fix rate', colleague, ScorecardMetric.TYPE_PERCENTAGE, '85', ScorecardMetric.DIR_ABOVE),
            ('Open complaints', admin, ScorecardMetric.TYPE_INTEGER, '3', ScorecardMetric.DIR_BELOW),
        ])
    ]
    history = [('14', '88', '2'), ('9', '81', '5'), ('13', '90', '3')]
    for weeks_ago, values in enumerate(history, start=1):
        for metric, value in zip(metrics, values):
            ScorecardEntry.objects.create(
                metric=metric, period_start=monday - timedelta(weeks=weeks_ago),
                value=Decimal(value), entered_by=admin,
            )

    past_meeting = Meeting.objects.create(
        team=leadership, scheduled_date=today - timedelta(days=7), created_by=admin,
    )
    past_meeting.start()
    past_meeting.complete(cascading_messages='Tell the depot team about the new rota.')
    MeetingRating.objects.create(meeting=past_meeting, participant=admin, score=8)
    Meeting.objects.create(team=leadership, scheduled_date=today + timedelta(days=7), created_by=admin)
    meeting = Meeting.objects.create(team=leadership, scheduled_date=today, created_by=admin)
    meeting.start()
    Headline.objects.create(
        meeting=meeting, author=admin, headline_type=Headline.TYPE_GOOD,
        text='Renewed the harbour authority contract',
    )
    Headline.objects.create(
        meeting=meeting, author=colleague, headline_type=Headline.TYPE_BAD,
        text='Lost the tender for the marina refit',
    )

    vto = VTO.for_org(org)
    VTOCoreValue.objects.create(vto=vto, name='Do it properly', description='No shortcuts on safety.', order=1)
    VTOCoreValue.objects.create(vto=vto, name='Say it straight', order=2)
    for key, content in [
        ('core_focus_purpose', 'Keep working harbours safely lit.'),
        ('core_focus_niche', 'Marine-grade lighting, installed and maintained.'),
        ('ten_year_target', 'Every commercial harbour in the South West on a service plan.'),
        ('target_market', 'Harbour authorities and marina operators.'),
        ('three_year_goals', 'Three depots\n40 service plans\n95% first-visit fix rate'),
        ('one_year_revenue', '£2.4m'),
        ('one_year_goals', 'Open Plymouth\nReplace scheduling\nHire two engineers'),
    ]:
        VTOSection.objects.create(vto=vto, key=key, content=content)

    visionary = AccountabilityNode.objects.create(organization=org, name='Managing Director', owner=admin)
    AccountabilityRole.objects.create(node=visionary, description='Sets direction', order=1)
    AccountabilityRole.objects.create(node=visionary, description='Key customer relationships', order=2)
    ops = AccountabilityNode.objects.create(
        organization=org, parent=visionary, name='Operations', owner=colleague, order=1,
    )
    AccountabilityRole.objects.create(node=ops, description='Runs the service schedule', order=1)
    AccountabilityNode.objects.create(organization=org, parent=visionary, name='Sales', order=2)

    return {
        'rock': rock.pk,
        'issue': issues[0].pk,
        'scorecard': scorecard.pk,
        'meeting': meeting.pk,
    }
