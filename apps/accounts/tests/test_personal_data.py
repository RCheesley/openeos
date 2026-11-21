"""One person's data: the copy they can download, and erasure by anonymisation."""
import io
import json
import zipfile
from datetime import date
from io import StringIO
from unittest import mock

from django.apps import apps
from django.contrib.admin.models import ADDITION, LogEntry
from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.core import serializers
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.models import Membership, Team, UserProfile
from apps.accounts.personal_data import erasure, relations
from apps.accounts.personal_data.erasure import (
    PLACEHOLDER_LABEL, PLACEHOLDER_USERNAME, ErasureRefused, PlaceholderConflict, erase,
    get_placeholder, is_erased, plan,
)
from apps.accounts.personal_data.export import build_personal_archive
from apps.accounts.personal_data.relations import (
    ERASE_DELETE, ERASE_KEEP, ERASE_REASSIGN, EXPORT_ACCOUNT, EXPORT_ACTIVITY, EXPORT_NEVER,
    EXPORT_RECORD, USER_RELATIONS, UnhandledRelation, discover,
)
from apps.accounts.two_factor import disable_two_factor
from apps.accounts.tests.test_portability import MediaRootMixin, populate_org
from apps.audit.models import AuditEvent
from apps.audit.services import record
from apps.issues.models import Issue, IssueActivity
from apps.meetings.models import Headline, Meeting, MeetingRating, SegueEntry
from apps.notifications.models import NotificationPreference
from apps.rocks.models import Rock
from apps.scorecards.models import ScorecardEntry
from apps.todos.models import ToDo

PASSWORD = 'correct horse battery'


def build_person():
    """Ada: admin of Alpha, member of Beta, former member of Gamma.

    Every relation to the user model has at least one row that names her
    (``test_fixture_names_the_person_on_every_relation`` insists on it), so the
    tests below exercise every decision in ``USER_RELATIONS``.
    """
    alpha, beta, gamma = populate_org('Alpha'), populate_org('Beta'), populate_org('Gamma')
    ada = alpha['admin']
    ada.username, ada.first_name, ada.last_name = 'ada', 'Ada', 'Lovelace'
    ada.email = 'ada@example.com'
    ada.set_password(PASSWORD)
    ada.save()

    # Alpha: the rows populate_org gives to other people.
    Issue.objects.create(title='Ada blocker', originating_team=alpha['team'], created_by=ada)
    ToDo.objects.create(title='Ada action', owner=ada, team=alpha['team'])
    ScorecardEntry.objects.create(
        metric=alpha['metric'], period_start=date(2026, 1, 12), value=3, entered_by=ada,
        notes='Ada figure',
    )
    Headline.objects.create(meeting=alpha['meeting'], author=ada, text='Ada headline')
    MeetingRating.objects.create(meeting=alpha['meeting'], participant=ada, score=8)

    # Beta: a member who owns one Priority there.
    Membership.objects.create(user=ada, organization=beta['org'], role=Membership.ROLE_MEMBER)
    ada.profile.teams.add(beta['team'])
    Rock.objects.create(
        title='Ada in Beta', owner=ada, team=beta['team'], quarter=1, year=2026,
        due_date=date(2026, 3, 31),
    )

    # Gamma: no membership any more, but one record still names her.
    Rock.objects.create(
        title='Gamma secret plan', owner=gamma['admin'], created_by=ada, team=gamma['team'],
        quarter=1, year=2026, due_date=date(2026, 3, 31),
    )

    # Site-wide rights, two-factor devices, the admin site's log, the audit log.
    ada.groups.add(Group.objects.create(name='Support'))
    ada.user_permissions.add(Permission.objects.first())
    totp = TOTPDevice.objects.create(user=ada, name='Authenticator app', confirmed=True)
    static = StaticDevice.objects.create(user=ada, name='Backup codes', confirmed=True)
    StaticToken.objects.create(device=static, token='backupcode1')
    LogEntry.objects.create(
        user=ada, content_type=ContentType.objects.get_for_model(Team),
        object_id=str(alpha['team'].pk), object_repr='Alpha Leadership', action_flag=ADDITION,
    )
    record('user.login', actor=ada, organization=alpha['org'])
    AuditEvent.objects.filter(actor=ada).update(ip_address='203.0.113.9', user_agent='AdaBrowser')
    record('user.login_failed', organization=alpha['org'], details={'username': 'ada'})
    record(
        'member.role_changed', actor=alpha['member'], organization=alpha['org'], target=ada,
        details={'role': 'admin', 'note': 'Mail sent to ada@example.com'},
    )
    return {'ada': ada, 'alpha': alpha, 'beta': beta, 'gamma': gamma, 'totp': totp}


def read_archive(data):
    archive = zipfile.ZipFile(io.BytesIO(data))
    return {name: archive.read(name) for name in archive.namelist()}


def snapshot():
    """Every row of every table, as text, to prove that nothing changed."""
    rows = []
    for model in apps.get_models(include_auto_created=True):
        if model._meta.proxy:
            continue
        rows.append(serializers.serialize('json', model._default_manager.order_by('pk')))
    return rows


class PersonMixin(MediaRootMixin):
    def setUp(self):
        super().setUp()
        self.world = build_person()
        self.ada = self.world['ada']
        self.alpha, self.beta, self.gamma = (
            self.world['alpha'], self.world['beta'], self.world['gamma'])


# ── the registry guard ─────────────────────────────────────────────────────

class RelationRegistryTests(PersonMixin, TestCase):
    def test_every_link_to_the_user_model_has_a_decision(self):
        discovered = {key for key, _, _ in discover()}
        self.assertEqual(
            discovered - set(USER_RELATIONS), set(),
            'A model points at the user account and USER_RELATIONS does not say what the '
            'personal export and the erasure do with it.',
        )
        self.assertEqual(
            set(USER_RELATIONS) - discovered, set(),
            'USER_RELATIONS lists a field that no longer exists.',
        )

    def test_every_decision_is_a_known_one(self):
        for key, handling in USER_RELATIONS.items():
            with self.subTest(key=key):
                self.assertIn(
                    handling.export,
                    {EXPORT_ACCOUNT, EXPORT_RECORD, EXPORT_ACTIVITY, EXPORT_NEVER})
                self.assertIn(handling.erase, {ERASE_REASSIGN, ERASE_KEEP, ERASE_DELETE})
                self.assertTrue(handling.reason)

    def test_rows_that_must_keep_an_owner_are_never_deleted_or_left(self):
        for key, _, field in discover():
            if field.remote_field.on_delete.__name__ == 'PROTECT':
                with self.subTest(key=key):
                    self.assertEqual(USER_RELATIONS[key].erase, ERASE_REASSIGN)

    def test_a_new_link_stops_the_export_and_the_erasure(self):
        extra = ('rocks.rockmilestone.signed_off_by', Rock, Rock._meta.get_field('owner'))
        with mock.patch.object(relations, 'discover', return_value=discover() + [extra]):
            with self.assertRaises(UnhandledRelation) as raised:
                plan(self.ada)
            self.assertIn('rocks.rockmilestone.signed_off_by', str(raised.exception))
            with self.assertRaises(UnhandledRelation):
                erase(self.ada, allow_last_admin=True)
            with self.assertRaises(UnhandledRelation):
                build_personal_archive(self.ada, fileobj=io.BytesIO())
            with self.assertRaises(CommandError):
                call_command('erase_user', 'ada', '--dry-run', stdout=StringIO())
        self.ada.refresh_from_db()
        self.assertEqual(self.ada.username, 'ada')

    def test_fixture_names_the_person_on_every_relation(self):
        for key, model, field in discover():
            with self.subTest(key=key):
                self.assertTrue(
                    model._default_manager.filter(**{field.name: self.ada}).exists(),
                    f'build_person() has no {key} row for the person, so the tests in this '
                    f'file would not notice if it were mishandled.',
                )

    def test_every_account_and_profile_column_is_cleared_or_named_as_kept(self):
        account = {f.name for f in User._meta.concrete_fields}
        self.assertEqual(
            account,
            set(erasure._account_target(self.ada)) | {'password'}
            | set(erasure.ACCOUNT_FIELDS_KEPT),
        )
        profile = {
            f.name for f in
            list(UserProfile._meta.concrete_fields) + list(UserProfile._meta.many_to_many)
        }
        self.assertEqual(
            profile, set(erasure.PROFILE_FIELDS_CLEARED) | set(erasure.PROFILE_FIELDS_KEPT))
        preference = {f.name for f in NotificationPreference._meta.concrete_fields}
        self.assertEqual(
            preference,
            set(erasure._boolean_preferences()) | set(erasure.PREFERENCE_FIELDS_KEPT),
        )


# ── the export ─────────────────────────────────────────────────────────────

class PersonalExportTests(PersonMixin, TestCase):
    def export(self):
        buffer = io.BytesIO()
        manifest = build_personal_archive(self.ada, fileobj=buffer)
        files = read_archive(buffer.getvalue())
        return manifest, files

    def load(self, files, name):
        return json.loads(files[name])

    def test_account_profile_memberships_and_preferences(self):
        _, files = self.export()
        account = self.load(files, 'account.json')
        self.assertEqual(account['account']['username'], 'ada')
        self.assertEqual(account['account']['email'], 'ada@example.com')
        self.assertEqual(account['account']['first_name'], 'Ada')
        self.assertEqual(account['account']['groups'], ['Support'])
        self.assertEqual(account['profile']['avatar'], self.ada.profile.avatar.name)
        self.assertEqual(account['two_factor']['enabled'], True)
        self.assertEqual(account['two_factor']['backup_codes_remaining'], 1)
        self.assertEqual(account['notification_preferences']['overdue_todo_digest'], False)
        self.assertEqual(account['notification_preferences']['meeting_reminders'], True)

        memberships = self.load(files, 'memberships.json')['memberships']
        self.assertEqual(
            [(m['organisation'], m['role']) for m in memberships],
            [('Alpha Org', 'Admin'), ('Beta Org', 'Team Member')],
        )
        self.assertEqual(memberships[0]['teams'], ['Alpha Leadership', 'Alpha Sales'])
        self.assertEqual(memberships[1]['teams'], ['Beta Leadership'])
        self.assertIn(f'media/{self.ada.profile.avatar.name}', files)

    def test_records_from_both_organisations_with_context(self):
        _, files = self.export()
        alpha_rocks = self.load(files, 'organisations/alpha-org/rocks.rock.json')
        by_title = {row['fields']['title']: row for row in alpha_rocks}
        self.assertEqual(by_title['Alpha Rock']['you_are'], ['owner', 'created_by'])
        self.assertEqual(by_title['Alpha Rock']['organisation'], 'Alpha Org')
        self.assertEqual(by_title['Alpha Rock']['team'], 'Alpha Leadership')
        self.assertEqual(by_title['Alpha Rock']['fields']['due_date'], '2026-03-31')
        # Somebody else owns the child; Ada only created it, and the owner is not named.
        self.assertEqual(by_title['Alpha Child Rock']['you_are'], ['created_by'])
        self.assertNotIn('owner', by_title['Alpha Child Rock']['fields'])

        beta_rocks = self.load(files, 'organisations/beta-org/rocks.rock.json')
        self.assertEqual([row['fields']['title'] for row in beta_rocks], ['Ada in Beta'])
        self.assertEqual(beta_rocks[0]['team'], 'Beta Leadership')

        checkins = self.load(files, 'organisations/alpha-org/rocks.rockcheckin.json')
        self.assertEqual(checkins[0]['fields']['note'], 'Alpha slipping')
        self.assertEqual(checkins[0]['fields']['rock'], 'Alpha Rock')

    def test_every_record_relation_is_exported(self):
        _, files = self.export()
        for key, model, field, handling in relations.handled():
            if handling.export != EXPORT_RECORD:
                continue
            with self.subTest(key=key):
                name = f'organisations/alpha-org/{model._meta.app_label}.{model._meta.model_name}.json'
                rows = self.load(files, name)
                self.assertTrue(any(field.name in row['you_are'] for row in rows))

    def test_activity_logs(self):
        _, files = self.export()
        events = self.load(files, 'activity/audit-log.json')
        login = next(e for e in events if e['action'] == 'user.login')
        self.assertEqual(login['ip_address'], '203.0.113.9')
        self.assertEqual(login['user_agent'], 'AdaBrowser')
        about = next(e for e in events if e['action'] == 'member.role_changed')
        self.assertFalse(about['done_by_you'])
        self.assertNotIn('ip_address', about)
        admin_log = self.load(files, 'activity/admin-site-log.json')
        self.assertEqual(admin_log[0]['action'], 'added')
        self.assertEqual(admin_log[0]['record'], 'Alpha Leadership')

    def test_no_secrets(self):
        self.client.login(username='ada', password=PASSWORD)
        session_key = self.client.session.session_key
        self.ada.refresh_from_db()
        _, files = self.export()
        everything = b'\n'.join(files.values()).decode('utf-8', errors='replace')
        self.assertNotIn(self.ada.password, everything)
        self.assertNotIn('pbkdf2', everything)
        self.assertNotIn(self.world['totp'].key, everything)
        self.assertNotIn('backupcode1', everything)
        self.assertNotIn(session_key, everything)

    def test_nothing_about_other_people_or_other_organisations(self):
        _, files = self.export()
        everything = b'\n'.join(files.values()).decode('utf-8', errors='replace')
        for other in ('alphamember', 'Alpha Member', 'betaadmin', 'Beta Admin', 'gammaadmin',
                      'alphaformer', 'betamember'):
            self.assertNotIn(other, everything)
        # Beta records that do not name Ada stay in Beta.
        self.assertNotIn('Beta Rock', everything)
        self.assertNotIn('Beta headline', everything)
        self.assertNotIn('organisations/beta-org/meetings.meeting.json', files)

    def test_former_organisation_gives_counts_not_content(self):
        manifest, files = self.export()
        self.assertEqual(manifest['former_organizations'], {'Gamma Org': {'rocks.rock': 1}})
        self.assertEqual(
            self.load(files, 'former-organisations.json'), {'Gamma Org': {'rocks.rock': 1}})
        everything = b'\n'.join(files.values()).decode('utf-8', errors='replace')
        self.assertNotIn('Gamma secret plan', everything)
        self.assertFalse([name for name in files if 'gamma' in name])
        self.assertIn('Gamma Org: 1 record(s)', files['README.txt'].decode())

    def test_readme_summarises_the_archive(self):
        _, files = self.export()
        readme = files['README.txt'].decode()
        self.assertIn('Account      : ada', readme)
        self.assertIn('Alpha Org', readme)
        self.assertIn('Beta Org', readme)
        self.assertIn('organisations/alpha-org/rocks.rock.json', readme)


class PersonalExportViewTests(PersonMixin, TestCase):
    url = reverse('accounts:personal_data_export')

    def setUp(self):
        super().setUp()
        # The test client signs in without the second step, so these tests run
        # with two-factor sign-in off; the archive contents are covered above.
        disable_two_factor(self.ada)

    def test_sign_in_required(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])

    def test_profile_links_to_the_page(self):
        self.client.login(username='ada', password=PASSWORD)
        self.assertContains(self.client.get(reverse('accounts:profile')), self.url)
        response = self.client.get(self.url)
        self.assertContains(response, 'Alpha Org')
        self.assertContains(response, 'Beta Org')
        self.assertContains(response, 'for="id_password"')

    def test_wrong_password_sends_nothing_and_records_nothing(self):
        self.client.login(username='ada', password=PASSWORD)
        response = self.client.post(self.url, {'password': 'nope'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'That password is not right')
        self.assertFalse(AuditEvent.objects.filter(action='user.personal_data_exported').exists())

    def test_right_password_downloads_own_data_and_is_audited(self):
        self.client.login(username='ada', password=PASSWORD)
        self.client.post(reverse('accounts:org_switch', args=[self.alpha['org'].pk]))
        response = self.client.post(self.url, {'password': PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/zip')
        self.assertIn('empresadence-personal-data-', response['Content-Disposition'])
        files = read_archive(b''.join(response.streaming_content))
        self.assertEqual(json.loads(files['account.json'])['account']['username'], 'ada')

        event = AuditEvent.objects.get(action='user.personal_data_exported')
        self.assertEqual(event.actor, self.ada)
        self.assertEqual(event.organization, self.alpha['org'])
        self.assertEqual(event.target_id, str(self.ada.pk))
        self.assertEqual(event.details['via'], 'web')
        self.assertGreater(event.details['size_bytes'], 0)
        self.assertEqual(
            event.details['record_counts']['organisations/beta-org/rocks.rock.json'], 1)

    def test_another_member_gets_their_own_data_not_ada_s(self):
        self.client.login(username='alphamember', password='pw')
        response = self.client.post(self.url, {'password': 'pw'})
        files = read_archive(b''.join(response.streaming_content))
        everything = b'\n'.join(files.values()).decode('utf-8', errors='replace')
        self.assertEqual(json.loads(files['account.json'])['account']['username'], 'alphamember')
        self.assertNotIn('ada@example.com', everything)
        self.assertNotIn('Lovelace', everything)

    def test_command_writes_the_same_archive(self):
        out = StringIO()
        call_command('export_personal_data', 'ada@example.com', '--out', self.media_root, stdout=out)
        path = out.getvalue().strip()
        with open(path, 'rb') as fh:
            files = read_archive(fh.read())
        self.assertIn('organisations/alpha-org/rocks.rock.json', files)
        event = AuditEvent.objects.get(action='user.personal_data_exported')
        self.assertEqual(event.details['via'], 'command')
        self.assertIsNone(event.actor)


# ── the erasure ────────────────────────────────────────────────────────────

class ErasureTests(PersonMixin, TestCase):
    def run_command(self, *args):
        out = StringIO()
        call_command('erase_user', *args, stdout=out)
        return out.getvalue()

    def erase_ada(self):
        return self.run_command('ada', '--yes', '--allow-last-admin')

    def test_dry_run_lists_the_changes_and_changes_nothing(self):
        self.client.login(username='ada', password=PASSWORD)
        before = snapshot()
        avatar = self.ada.profile.avatar.name
        output = self.run_command('ada', '--dry-run')
        self.assertEqual(snapshot(), before)
        self.assertTrue(default_storage.exists(avatar))
        self.assertIsNone(get_placeholder())
        self.assertIn('Dry run: nothing was changed.', output)
        self.assertIn('username, first_name, last_name, email', output)
        self.assertIn(f'Avatar file removed: {avatar}', output)
        self.assertRegex(output, r'2\s+Memberships \(user\): deleted')
        self.assertRegex(output, r'2\s+Rocks \(owner\): shown as "Former member"')
        self.assertRegex(output, r'1\s+Sign-in sessions ended')
        self.assertIn('only admin of "Alpha Org"', output)
        self.assertIn('--allow-last-admin', output)

    def test_every_relation_is_handled_as_decided(self):
        before = {
            key: set(model._default_manager.filter(**{field.name: self.ada})
                     .values_list('pk', flat=True))
            for key, model, field in discover()
        }
        self.erase_ada()
        placeholder = get_placeholder()
        for key, model, field in discover():
            decision = USER_RELATIONS[key].erase
            rows = model._default_manager
            with self.subTest(key=key, decision=decision):
                mine = set(rows.filter(**{field.name: self.ada}).values_list('pk', flat=True))
                if decision == ERASE_KEEP:
                    self.assertEqual(mine, before[key])
                    continue
                self.assertEqual(mine, set())
                survivors = rows.filter(pk__in=before[key])
                if decision == ERASE_DELETE:
                    self.assertFalse(survivors.exists())
                else:
                    self.assertEqual(survivors.count(), len(before[key]))
                    self.assertEqual(
                        set(survivors.values_list(field.attname, flat=True)), {placeholder.pk})

    def test_account_is_emptied_and_switched_off(self):
        avatar = self.ada.profile.avatar.name
        self.erase_ada()
        self.ada.refresh_from_db()
        self.assertEqual(self.ada.username, f'erased-{self.ada.pk}')
        self.assertEqual(self.ada.get_full_name(), 'Former member')
        self.assertEqual(self.ada.email, '')
        self.assertFalse(self.ada.is_active)
        self.assertFalse(self.ada.has_usable_password())
        self.assertIsNone(self.ada.last_login)
        self.assertTrue(is_erased(self.ada))
        profile = UserProfile.objects.get(user=self.ada)
        self.assertFalse(profile.avatar)
        self.assertEqual(profile.teams.count(), 0)
        self.assertFalse(default_storage.exists(avatar))
        preference = NotificationPreference.objects.get(user=self.ada)
        self.assertFalse(preference.overdue_todo_digest)
        self.assertFalse(preference.meeting_reminders)
        self.assertFalse(preference.rock_off_track_alerts)
        self.assertFalse(StaticToken.objects.filter(token='backupcode1').exists())

    def test_superuser_rights_are_removed(self):
        self.ada.is_superuser = self.ada.is_staff = True
        self.ada.save()
        self.run_command('ada', '--yes', '--allow-last-admin', '--allow-superuser')
        self.ada.refresh_from_db()
        self.assertFalse(self.ada.is_superuser)
        self.assertFalse(self.ada.is_staff)

    def test_sessions_end_and_sign_in_is_blocked(self):
        self.client.login(username='ada', password=PASSWORD)
        other = self.client_class()
        other.login(username='alphamember', password='pw')
        self.assertEqual(Session.objects.count(), 2)
        self.erase_ada()
        self.assertEqual(Session.objects.count(), 1)
        response = self.client.get(reverse('accounts:profile'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])
        self.assertFalse(self.client.login(username='ada', password=PASSWORD))
        self.assertFalse(self.client.login(username=f'erased-{self.ada.pk}', password=PASSWORD))
        self.assertEqual(other.get(reverse('accounts:profile')).status_code, 200)

    def test_placeholder_cannot_sign_in_and_belongs_nowhere(self):
        self.erase_ada()
        placeholder = get_placeholder()
        self.assertEqual(placeholder.username, PLACEHOLDER_USERNAME)
        self.assertEqual(placeholder.get_full_name(), PLACEHOLDER_LABEL)
        self.assertFalse(placeholder.is_active)
        self.assertFalse(placeholder.has_usable_password())
        self.assertEqual(placeholder.email, '')
        self.assertFalse(Membership.objects.filter(user=placeholder).exists())
        self.assertFalse(
            NotificationPreference.objects.get(user=placeholder).overdue_todo_digest)

    def test_running_twice_changes_nothing_the_second_time(self):
        self.erase_ada()
        self.ada.refresh_from_db()
        self.assertFalse(plan(self.ada).has_changes)
        before = snapshot()
        output = self.run_command(f'erased-{self.ada.pk}', '--yes')
        self.assertIn('Already erased: nothing to change.', output)
        self.assertEqual(snapshot(), before)
        erase(self.ada)
        self.assertEqual(snapshot(), before)
        self.assertEqual(User.objects.filter(username=PLACEHOLDER_USERNAME).count(), 1)

    def test_history_stays_readable_without_the_name(self):
        self.erase_ada()
        self.client.login(username='alphamember', password='pw')
        response = self.client.get(reverse('rocks:detail', args=[self.alpha['rock'].pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Alpha Rock')
        self.assertContains(response, 'Alpha slipping')      # her check-in text stays
        self.assertContains(response, PLACEHOLDER_LABEL)
        self.assertNotContains(response, 'Lovelace')
        response = self.client.get(reverse('issues:detail', args=[self.alpha['issue'].pk]))
        self.assertContains(response, 'Alpha note')          # her comment stays
        self.assertContains(response, PLACEHOLDER_LABEL)
        self.assertNotContains(response, 'Lovelace')
        response = self.client.get(reverse('meetings:detail', args=[self.alpha['meeting'].pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Lovelace')
        # What she wrote is kept word for word.
        self.assertEqual(IssueActivity.objects.get(pk=self.alpha['activity'].pk).notes, 'Alpha note')
        segue = SegueEntry.objects.get(pk=self.alpha['segue'].pk)
        self.assertEqual((segue.personal_best, segue.participant_id), ('Slept', self.ada.pk))
        self.assertEqual(MeetingRating.objects.get(participant=self.ada).score, 8)

    def test_audit_log_keeps_the_events_without_the_person(self):
        self.erase_ada()
        login = AuditEvent.objects.get(action='user.login')
        self.assertEqual(login.actor, get_placeholder())
        self.assertEqual(login.actor_label, PLACEHOLDER_LABEL)
        self.assertIsNone(login.ip_address)
        self.assertEqual(login.user_agent, '')
        failed = AuditEvent.objects.get(action='user.login_failed')
        self.assertEqual(failed.details, {'username': PLACEHOLDER_LABEL})
        changed = AuditEvent.objects.get(action='member.role_changed')
        self.assertEqual(changed.target_label, PLACEHOLDER_LABEL)
        # A value is only a person under a key that says so; the email goes anywhere.
        self.assertEqual(
            changed.details, {'role': 'admin', 'note': f'Mail sent to {PLACEHOLDER_LABEL}'})
        self.assertEqual(changed.actor, self.alpha['member'])

    def test_erasure_is_audited_without_personal_data(self):
        self.erase_ada()
        events = AuditEvent.objects.filter(action='user.erased')
        self.assertEqual(
            {e.organization for e in events}, {None, self.alpha['org'], self.beta['org']})
        for event in events:
            text = json.dumps([
                event.actor_label, event.target_label, event.details, event.user_agent,
            ]).lower()
            for personal in ('ada', 'lovelace', 'example.com'):
                self.assertNotIn(personal, text)
            self.assertEqual(event.target_id, str(self.ada.pk))
            self.assertIsNone(event.actor)
        instance = events.get(organization=None)
        self.assertEqual(instance.details['changed']['accounts.membership.user'], 2)
        self.assertEqual(instance.details['changed']['rocks.rock.owner'], 2)

    def test_nothing_personal_is_left_anywhere(self):
        self.erase_ada()
        everything = '\n'.join(snapshot())
        for personal in ('ada@example.com', 'Lovelace', '"ada"', '203.0.113.9', 'AdaBrowser',
                         'alpha-avatar'):
            self.assertNotIn(personal, everything)

    def test_last_admin_is_refused_without_the_flag(self):
        before = snapshot()
        with self.assertRaises(CommandError) as raised:
            self.run_command('ada', '--yes')
        self.assertIn('only admin of "Alpha Org"', str(raised.exception))
        with self.assertRaises(ErasureRefused):
            erase(self.ada)
        self.assertEqual(snapshot(), before)

    def test_another_active_admin_lifts_the_refusal(self):
        Membership.objects.filter(user=self.alpha['member']).update(role=Membership.ROLE_ADMIN)
        self.run_command('ada', '--yes')
        self.ada.refresh_from_db()
        self.assertTrue(is_erased(self.ada))

    def test_superuser_is_refused_without_the_flag(self):
        self.ada.is_superuser = True
        self.ada.save()
        before = snapshot()
        with self.assertRaises(CommandError) as raised:
            self.run_command('ada', '--yes', '--allow-last-admin')
        self.assertIn('superuser', str(raised.exception))
        self.assertEqual(snapshot(), before)

    def test_confirmation_must_repeat_the_username(self):
        before = snapshot()
        with mock.patch('builtins.input', return_value='yes'):
            with self.assertRaises(CommandError):
                self.run_command('ada', '--allow-last-admin')
        self.assertEqual(snapshot(), before)
        with mock.patch('builtins.input', return_value='ada'):
            self.run_command('ada', '--allow-last-admin')
        self.ada.refresh_from_db()
        self.assertTrue(is_erased(self.ada))

    def test_person_can_be_found_by_email_and_unknown_is_an_error(self):
        output = self.run_command('ADA@example.com', '--dry-run')
        self.assertIn('Erasing "ada"', output)
        with self.assertRaises(CommandError):
            self.run_command('nobody', '--dry-run')

    def test_two_former_members_of_one_meeting(self):
        member = self.alpha['member']
        SegueEntry.objects.create(meeting=self.alpha['meeting'], participant=member)
        self.erase_ada()
        self.run_command('alphamember', '--yes')
        meeting = Meeting.objects.get(pk=self.alpha['meeting'].pk)
        self.assertEqual(meeting.segue_entries.count(), 2)
        self.assertEqual(meeting.ratings.count(), 2)
        self.assertEqual(
            {entry.participant.get_full_name() for entry in meeting.segue_entries.all()},
            {PLACEHOLDER_LABEL},
        )
        self.assertEqual(User.objects.filter(username=PLACEHOLDER_USERNAME).count(), 1)

    def test_a_real_account_with_the_placeholder_name_stops_the_erasure(self):
        User.objects.create_user(username=PLACEHOLDER_USERNAME, password='pw')
        before = snapshot()
        with self.assertRaises(PlaceholderConflict):
            erase(self.ada, allow_last_admin=True)
        with self.assertRaises(CommandError):
            self.erase_ada()
        self.assertEqual(snapshot(), before)

    def test_the_placeholder_itself_cannot_be_erased(self):
        self.erase_ada()
        with self.assertRaises(CommandError):
            self.run_command(PLACEHOLDER_USERNAME, '--yes')
