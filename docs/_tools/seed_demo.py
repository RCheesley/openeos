"""Invented demo data for the documentation screenshots: the "Harbour Lights" organisation.

Run it against an empty database, through the Django shell:

    python manage.py shell < docs/_tools/seed_demo.py

Every name, address and record here is made up. Harbour Lights is a fictional
harbour business; nothing comes from a real company or person. Dates are
worked out from today, so the screenshots always show the current quarter.

Running it twice is safe: every record is looked up before it is created.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.utils import timezone

from apps.accountability.models import AccountabilityNode, AccountabilityRole
from apps.accounts.models import Membership, Organization, Team
from apps.issues.models import Issue, IssueActivity
from apps.meetings.models import Headline, Meeting, MeetingNote, MeetingRating, SegueEntry
from apps.rocks.models import Rock, RockCheckin, RockMilestone
from apps.scorecards.models import Scorecard, ScorecardEntry, ScorecardMetric
from apps.todos.models import ToDo
from apps.vision.models import VTO, VTOCoreValue, VTOSection

PASSWORD = 'harbour-lights-demo'
TODAY = date.today()
QUARTER = (TODAY.month - 1) // 3 + 1
YEAR = TODAY.year
QUARTER_END = Rock.quarter_end_date(QUARTER, YEAR)
THIS_MONDAY = TODAY - timedelta(days=TODAY.weekday())


def days_ago(days, hour=9):
    moment = datetime.combine(TODAY - timedelta(days=days), time(hour, 0))
    return timezone.make_aware(moment)


org, _ = Organization.objects.get_or_create(slug='harbour-lights', defaults={'name': 'Harbour Lights'})
leadership, _ = Team.objects.get_or_create(
    organization=org, name='Leadership',
    defaults={'description': 'Sets the direction for the harbour.'},
)
operations, _ = Team.objects.get_or_create(
    organization=org, name='Operations',
    defaults={'description': 'Runs the quays, the fuel dock and the boatyard.'},
)


def person(username, first, last, role, *teams):
    user, created = User.objects.get_or_create(
        username=username,
        defaults={
            'first_name': first, 'last_name': last,
            'email': f'{first}.{last}@example.com'.lower(),
        },
    )
    if created:
        user.set_password(PASSWORD)
        user.save()
    Membership.objects.get_or_create(user=user, organization=org, defaults={'role': role})
    user.profile.teams.add(*teams)
    return user


ada = person('ada', 'Ada', 'Marsh', Membership.ROLE_ADMIN, leadership, operations)
priyanka = person('priyanka', 'Priyanka', 'Nair', Membership.ROLE_LEADER, operations, leadership)
tom = person('tom', 'Tom', 'Reyes', Membership.ROLE_MEMBER, operations)
bo = person('bo', 'Bo', 'Lindqvist', Membership.ROLE_MEMBER, operations)
christopher = person('christopher', 'Christopher', 'Okafor', Membership.ROLE_MEMBER, leadership)


# ── Priorities, Steps and check-ins ──────────────────────────────────────────

def priority(title, owner, team, steps, checkins=(), **extra):
    rock, created = Rock.objects.get_or_create(
        title=title, team=team,
        defaults={
            'owner': owner, 'quarter': QUARTER, 'year': YEAR, 'due_date': QUARTER_END,
            'created_by': ada, **extra,
        },
    )
    if created:
        Rock.objects.filter(pk=rock.pk).update(created_at=days_ago(40))
        for order, (step, done) in enumerate(steps):
            RockMilestone.objects.create(
                rock=rock, title=step, order=order, is_complete=done,
                completed_at=days_ago(10) if done else None,
            )
        for age, confidence, note in checkins:
            checkin = RockCheckin.objects.create(
                rock=rock, confidence=confidence, note=note, created_by=owner,
            )
            RockCheckin.objects.filter(pk=checkin.pk).update(created_at=days_ago(age))
    return rock


ON, OFF = Rock.STATUS_ON_TRACK, Rock.STATUS_OFF_TRACK

berths = priority(
    'Open the east quay to visiting boats', ada, leadership,
    [('Agree the mooring fees', True), ('Fit the new pontoon lighting', False),
     ('Publish the visitor guide', False)],
    checkins=[(15, ON, 'Fees agreed with the board.'), (8, ON, 'Lighting order placed.')],
    description='Twelve visitor berths ready before the season starts.',
    is_company_rock=True,
)
priority(
    'Agree next year\'s harbour dues', christopher, leadership,
    [('Compare dues at three nearby harbours', True), ('Draft the new price list', True),
     ('Board sign-off', False)],
    checkins=[(6, ON, 'Draft price list is with the board.')],
    description='A signed-off price list published to berth holders.',
)
fuel = priority(
    'Cut fuel dock waiting time to ten minutes', tom, operations,
    [('Time a normal Saturday', True), ('Add a second card reader', False),
     ('Train the weekend crew on the new queue', False)],
    checkins=[
        (15, ON, 'Timed four Saturdays. Average wait is 22 minutes.'),
        (8, ON, 'Second card reader ordered.'),
    ],
    description='Average wait at the fuel dock is ten minutes or less on a summer Saturday.',
)
drill = priority(
    'Train every deckhand on the new safety drill', priyanka, operations,
    [('Write the drill card', True), ('Run the first session', False),
     ('Sign off the whole crew', False)],
    checkins=[(9, OFF, 'First session moved back because of the crane inspection.')],
    description='Every deckhand has completed the drill and signed the register.',
    status=OFF,
)
priority(
    'Replace the boatyard hoist slings', bo, operations,
    [('Get two quotes', True), ('Fit and load-test the new slings', True)],
    checkins=[(12, ON, 'New slings fitted and tested.')],
    description='New slings fitted, tested and certified.',
    status=Rock.STATUS_COMPLETE,
)


# ── Blockers ─────────────────────────────────────────────────────────────────

def blocker(title, creator, team, age=3, **extra):
    issue, created = Issue.objects.get_or_create(
        title=title, originating_team=team, defaults={'created_by': creator, **extra},
    )
    if created:
        Issue.objects.filter(pk=issue.pk).update(created_at=days_ago(age))
        activity = IssueActivity.objects.create(
            issue=issue, actor=creator, action=IssueActivity.ACTION_CREATED,
        )
        IssueActivity.objects.filter(pk=activity.pk).update(created_at=days_ago(age))
    return issue


crane = blocker(
    'Crane is out of service until the inspector visits', tom, operations, age=6,
    description='No lifts over two tonnes until the certificate is renewed.',
)
reader = blocker(
    'Card reader on the fuel dock drops its connection', priyanka, operations, age=4,
    description='Customers have to pay at the office when the reader is offline.',
)
reader.linked_rocks.add(fuel)
blocker(
    'Not enough trained crew for bank holiday weekends', bo, operations, age=2,
    issue_type=Issue.TYPE_LONG_TERM, target_quarter=QUARTER, target_year=YEAR,
)
blocker('Nobody owns the winter berth waiting list', ada, leadership, age=5)
resolved = blocker(
    'Slipway gate does not lock', tom, operations, age=20,
    status=Issue.STATUS_RESOLVED,
    resolution_notes='New padlock fitted. Bo holds the spare key.',
)
if not resolved.activity.filter(action=IssueActivity.ACTION_RESOLVED).exists():
    IssueActivity.objects.create(
        issue=resolved, actor=bo, action=IssueActivity.ACTION_RESOLVED,
        notes=resolved.resolution_notes,
    )


# ── Actions ──────────────────────────────────────────────────────────────────

def action(title, owner, team, days, **extra):
    todo, _ = ToDo.objects.get_or_create(
        title=title, team=team,
        defaults={'owner': owner, 'due_date': TODAY + timedelta(days=days), **extra},
    )
    return todo


action('Order replacement fenders for the east quay', tom, operations, 3)
action('Check the lifebuoy stations', tom, operations, 2)
action('Ask the supplier about a wired card reader', tom, operations, 5,
       linked_rock=fuel, linked_issue=reader)
action('Book the electrician for the pontoon lights', priyanka, operations, 5)
action('Print the new drill cards', priyanka, operations, 1, linked_rock=drill)
action('Chase the crane inspector for a date', bo, operations, -2, linked_issue=crane)
action('Send the mooring fee proposal to the board', ada, leadership, 7, linked_rock=berths)
action('Draft the visitor guide', christopher, leadership, 10, linked_rock=berths)
done = action('Update the tide tables on the noticeboard', tom, operations, -1)
if not done.is_complete:
    done.mark_complete()


# ── Metrics Board ────────────────────────────────────────────────────────────

board, _ = Scorecard.objects.get_or_create(
    name='Harbour operations', team=operations,
    defaults={'description': 'The numbers the Operations team checks every week.'},
)

# (name, owner, type, goal, direction, values for the eight weeks before this one)
METRICS = [
    ('Visitor berth nights', tom, ScorecardMetric.TYPE_INTEGER, '60', ScorecardMetric.DIR_ABOVE,
     [48, 52, 61, 58, 64, 70, 66, 72]),
    ('Fuel dock waiting time (minutes)', tom, ScorecardMetric.TYPE_INTEGER, '10',
     ScorecardMetric.DIR_BELOW, [22, 21, 19, 18, 16, 15, 14, 13]),
    ('Fuel sold (litres)', bo, ScorecardMetric.TYPE_INTEGER, '9000', ScorecardMetric.DIR_ABOVE,
     [8200, 8650, 9100, 9400, 8900, 9600, 10100, 9800]),
    ('Boatyard lifts completed', bo, ScorecardMetric.TYPE_INTEGER, '12', ScorecardMetric.DIR_ABOVE,
     [14, 13, 12, 15, 12, 9, 6, 5]),
    ('Safety checks completed on time', priyanka, ScorecardMetric.TYPE_PERCENTAGE, '95',
     ScorecardMetric.DIR_ABOVE, [96, 98, 94, 97, 100, 96, 92, 97]),
    ('Customer complaints', priyanka, ScorecardMetric.TYPE_INTEGER, '2', ScorecardMetric.DIR_BELOW,
     [1, 0, 2, 1, 3, 1, 0, 1]),
]
for order, (name, owner, metric_type, goal, direction, values) in enumerate(METRICS):
    metric, created = ScorecardMetric.objects.get_or_create(
        scorecard=board, name=name,
        defaults={
            'owner': owner, 'metric_type': metric_type, 'goal_value': Decimal(goal),
            'goal_direction': direction, 'order': order,
        },
    )
    if created:
        for weeks_back, value in zip(range(len(values), 0, -1), values):
            ScorecardEntry.objects.create(
                metric=metric, period_start=THIS_MONDAY - timedelta(weeks=weeks_back),
                value=Decimal(value), entered_by=owner,
            )


# ── Weekly Meetings: one completed last week, one scheduled for today ────────

last_week = TODAY - timedelta(days=7)
past, created = Meeting.objects.get_or_create(
    team=operations, scheduled_date=last_week, defaults={'created_by': priyanka},
)
if created:
    past.status = Meeting.STATUS_COMPLETE
    past.started_at = days_ago(7, hour=9)
    past.ended_at = past.started_at + timedelta(minutes=86)
    past.current_segment = len(past.agenda) - 1
    past.cascading_messages = (
        'The crane is out of service until the inspector has visited.\n'
        'Fuel dock card payments may be slow this weekend. The office can take payment.'
    )
    past.save()
    SegueEntry.objects.create(
        meeting=past, participant=tom,
        personal_best='Took my daughter sailing for the first time.',
        business_best='A visiting skipper wrote in to thank the fuel dock crew.',
    )
    SegueEntry.objects.create(
        meeting=past, participant=bo,
        personal_best='Finished painting the kitchen.',
        business_best='New hoist slings passed the load test.',
    )
    Headline.objects.create(
        meeting=past, author=bo, headline_type=Headline.TYPE_GOOD,
        text='Hoist slings replaced a week early.',
    )
    Headline.objects.create(
        meeting=past, author=priyanka, headline_type=Headline.TYPE_BAD,
        text='Two crew are away for the bank holiday weekend.',
    )
    MeetingNote.objects.create(
        meeting=past, segment=5, updated_by=priyanka,
        text='Crane: Bo to chase the inspector. Card reader: Tom to ask about a wired model.',
    )
    for participant, score in ((priyanka, 9), (tom, 8), (bo, 9), (ada, 8)):
        MeetingRating.objects.create(meeting=past, participant=participant, score=score)

Meeting.objects.get_or_create(
    team=operations, scheduled_date=TODAY, defaults={'created_by': priyanka},
)
Meeting.objects.get_or_create(
    team=leadership, scheduled_date=TODAY + timedelta(days=2), defaults={'created_by': ada},
)


# ── Vision and Delivery Board ────────────────────────────────────────────────

vision = VTO.for_org(org)
for order, (name, description) in enumerate([
    ('Safe first', 'Nobody takes a risk to save time.'),
    ('Leave it shipshape', 'We hand over every berth, tool and job tidier than we found it.'),
    ('Warm welcome', 'Every visitor is greeted by name before they have tied up.'),
]):
    VTOCoreValue.objects.get_or_create(
        vto=vision, name=name, defaults={'description': description, 'order': order},
    )
VISION = {
    'core_focus_purpose': 'Make time on the water simple for everyone who visits.',
    'core_focus_niche': 'A friendly working harbour for leisure boats under fifteen metres.',
    'ten_year_target': 'The first choice for visiting boats on this coast.',
    'target_market': 'Cruising sailors and motor boat owners within two days of the harbour.',
    'three_uniques_1': 'A berth is always ready when you arrive.',
    'three_uniques_2': 'Fuel, water and repairs on one quay.',
    'three_uniques_3': 'Crew who know your boat by name.',
    'three_year_picture': 'Forty visitor berths, a second fuel pump and a year-round boatyard.',
    'three_year_goals': '6,000 visitor berth nights a year\nBoatyard booked nine months of the year',
    'one_year_revenue': '1.4 million',
    'one_year_profit': '180,000',
    'one_year_goals': (
        'Open the east quay to visiting boats\n'
        'Fuel dock wait under ten minutes\n'
        'Every deckhand trained on the new safety drill'
    ),
}
for key, content in VISION.items():
    section, _ = VTOSection.objects.get_or_create(vto=vision, key=key)
    if not section.content:
        section.save_content(content, ada)


# ── Org Chart ────────────────────────────────────────────────────────────────

def chart_node(name, owner, parent=None, order=0, roles=()):
    node, created = AccountabilityNode.objects.get_or_create(
        organization=org, name=name, defaults={'owner': owner, 'parent': parent, 'order': order},
    )
    if created:
        for position, description in enumerate(roles):
            AccountabilityRole.objects.create(node=node, description=description, order=position)
    return node


harbour_master = chart_node(
    'Harbour Master', ada, roles=('Sets the direction', 'Chairs the board meeting'),
)
chart_node('Operations Lead', priyanka, harbour_master, 0, ('Safety', 'Crew rota'))
chart_node('Fuel Dock Lead', tom, harbour_master, 1, ('Fuel dock', 'Visitor berths'))
chart_node('Boatyard Lead', bo, harbour_master, 2, ('Lifts and storage', 'Repairs'))
chart_node('Finance Lead', christopher, harbour_master, 3, ('Harbour dues', 'Budget'))

print(
    f'Seeded {org.name}: {Team.objects.filter(organization=org).count()} teams, '
    f'{Membership.objects.filter(organization=org).count()} people, '
    f'{Rock.objects.filter(team__organization=org).count()} Priorities, '
    f'{ToDo.objects.filter(team__organization=org).count()} Actions, '
    f'{Issue.objects.filter(originating_team__organization=org).count()} Blockers, '
    f'{ScorecardEntry.objects.filter(metric__scorecard__team__organization=org).count()} '
    f'Metrics Board entries, '
    f'{Meeting.objects.filter(team__organization=org).count()} Weekly Meetings.'
)
print(f'Sign in as any of: ada, priyanka, tom, bo, christopher. Password: {PASSWORD}')
