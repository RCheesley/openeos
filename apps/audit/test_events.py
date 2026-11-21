"""One test per audit event: it is written, to the right organisation, without secrets."""
import json
import re
from datetime import date
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.test import TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_static.models import StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accountability.models import AccountabilityNode, AccountabilityRole
from apps.accounts.models import Membership, Organization, Team
from apps.accounts.terminology import Terms
from apps.accounts.tests.test_two_factor import totp_code
from apps.issues.models import Issue
from apps.rocks.models import Rock
from apps.scorecards.models import Scorecard, ScorecardMetric
from apps.todos.models import ToDo
from apps.vision.models import VTO, VTOCoreValue, VTOSection
from apps.vision.structure import section_specs_for

from .events import EVENTS, describe
from .models import AuditEvent
from .services import record, record_for_user, snapshot

PASSWORD = 'correct-horse-battery'
NEW_PASSWORD = 'another-staple-entirely'


class AuditTestCase(TestCase):
    """Mine Org with an admin and a member on one team; Theirs Org alongside."""

    def setUp(self):
        self.org = Organization.objects.create(name='Mine Org')
        self.team = Team.objects.create(organization=self.org, name='Mine Team')
        self.admin = self.make_user('mineadmin', self.org, Membership.ROLE_ADMIN, self.team)
        self.member = self.make_user('minemember', self.org, Membership.ROLE_MEMBER, self.team)
        self.other_org = Organization.objects.create(name='Theirs Org')
        self.other_admin = self.make_user('theirsadmin', self.other_org, Membership.ROLE_ADMIN)
        self.client.force_login(self.admin)

    def make_user(self, username, org, role, team=None):
        user = User.objects.create_user(
            username=username, password=PASSWORD, email=f'{username}@example.com',
        )
        Membership.objects.create(user=user, organization=org, role=role)
        if team:
            user.profile.teams.add(team)
        return user

    def event(self, action, actor=None, organization=None, **filters):
        """The single event of this kind, checked for actor and organisation."""
        event = AuditEvent.objects.get(action=action, **filters)
        actor = actor or self.admin
        self.assertEqual(event.actor, actor)
        self.assertEqual(event.actor_label, actor.username)
        self.assertEqual(event.organization, organization or self.org)
        self.assertIn(action, EVENTS)
        return event

    def assertTarget(self, event, target_type, pk, label):
        self.assertEqual(
            (event.target_type, event.target_id, event.target_label),
            (target_type, str(pk), label),
        )

    def assertNoSecrets(self, event, *secrets):
        stored = json.dumps([
            event.details, event.target_label, event.target_id, event.actor_label,
        ])
        for secret in (PASSWORD, NEW_PASSWORD, *secrets):
            self.assertNotIn(str(secret), stored)

    def assertNothingRecorded(self, action):
        self.assertFalse(AuditEvent.objects.filter(action=action).exists())


class InvitationEventTest(AuditTestCase):
    def test_invitation_is_recorded_with_who_invited_whom(self):
        resp = self.client.post(reverse('accounts:user_invite'), {
            'username': 'newbie', 'email': 'newbie@example.com', 'first_name': 'New',
            'last_name': 'Bie', 'role': Membership.ROLE_LEADER, 'teams': [self.team.pk],
        })
        self.assertEqual(resp.status_code, 302)
        invited = User.objects.get(username='newbie')
        event = self.event('user.invited')
        self.assertTarget(event, 'auth.user', invited.pk, 'newbie')
        self.assertEqual(event.details, {
            'user_id': invited.pk, 'username': 'newbie', 'role': Membership.ROLE_LEADER,
            'team_ids': [self.team.pk], 'teams': ['Mine Team'],
        })
        # Neither the address nor anything from the set-password link is kept.
        self.assertNoSecrets(
            event, 'newbie@example.com', default_token_generator.make_token(invited),
            invited.password,
        )

    def test_rejected_invitation_records_nothing(self):
        self.client.post(reverse('accounts:user_invite'), {
            'username': 'minemember', 'email': 'x@example.com', 'role': Membership.ROLE_MEMBER,
        })
        self.assertNothingRecorded('user.invited')


class TeamEventTest(AuditTestCase):
    def test_team_created(self):
        resp = self.client.post(reverse('accounts:team_create'), {
            'name': 'Finance', 'description': 'Counts the beans',
        })
        self.assertEqual(resp.status_code, 302)
        team = Team.objects.get(name='Finance')
        event = self.event('team.created')
        self.assertTarget(event, 'accounts.team', team.pk, 'Finance')
        self.assertEqual(event.details, {'name': 'Finance'})

    def test_team_renamed_keeps_old_and_new_name(self):
        self.client.post(reverse('accounts:team_update', args=[self.team.pk]), {
            'name': 'Leadership', 'description': '',
        })
        event = self.event('team.updated')
        self.assertTarget(event, 'accounts.team', self.team.pk, 'Leadership')
        self.assertEqual(event.details, {
            'fields': ['name'], 'old_name': 'Mine Team', 'new_name': 'Leadership',
        })

    def test_team_description_change_is_noted_without_its_text(self):
        self.client.post(reverse('accounts:team_update', args=[self.team.pk]), {
            'name': 'Mine Team', 'description': 'A private remark about the team',
        })
        event = self.event('team.updated')
        self.assertEqual(event.details, {'fields': ['description']})
        self.assertNoSecrets(event, 'private remark')

    def test_team_saved_unchanged_records_nothing(self):
        self.client.post(reverse('accounts:team_update', args=[self.team.pk]), {
            'name': 'Mine Team', 'description': '',
        })
        self.assertNothingRecorded('team.updated')

    def test_member_added_to_team(self):
        joiner = self.make_user('joiner', self.org, Membership.ROLE_MEMBER)
        self.client.post(reverse('accounts:team_members', args=[self.team.pk]), {
            'users': [self.admin.pk, self.member.pk, joiner.pk],
        })
        event = self.event('team.member_added')
        self.assertTarget(event, 'auth.user', joiner.pk, 'joiner')
        self.assertEqual(event.details, {
            'user_id': joiner.pk, 'username': 'joiner',
            'team_id': self.team.pk, 'team': 'Mine Team',
        })
        self.assertNothingRecorded('team.member_removed')

    def test_member_removed_from_team(self):
        self.client.post(reverse('accounts:team_members', args=[self.team.pk]), {
            'users': [self.admin.pk],
        })
        event = self.event('team.member_removed')
        self.assertTarget(event, 'auth.user', self.member.pk, 'minemember')
        self.assertEqual(event.details, {
            'user_id': self.member.pk, 'username': 'minemember',
            'team_id': self.team.pk, 'team': 'Mine Team',
        })
        self.assertNothingRecorded('team.member_added')

    def test_team_members_saved_unchanged_records_nothing(self):
        self.client.post(reverse('accounts:team_members', args=[self.team.pk]), {
            'users': [self.admin.pk, self.member.pk],
        })
        self.assertNothingRecorded('team.member_added')
        self.assertNothingRecorded('team.member_removed')


class OrganisationEventTest(AuditTestCase):
    def test_organisation_created(self):
        root = User.objects.create_superuser(username='root', password=PASSWORD)
        self.client.force_login(root)
        resp = self.client.post(reverse('accounts:org_setup'), {'name': 'Brand New'})
        self.assertEqual(resp.status_code, 302)
        org = Organization.objects.get(name='Brand New')
        event = self.event('organization.created', actor=root, organization=org)
        self.assertTarget(event, 'accounts.organization', org.pk, 'Brand New')

    def branding(self, **changes):
        data = {
            'name': 'Mine Org', 'display_name': '', 'tagline': '', 'primary_color': '#0d6efd',
            'navbar_style': self.org.navbar_style, 'support_email': '', 'email_from_name': '',
        }
        data.update(changes)
        return self.client.post(reverse('accounts:org_settings'), data)

    def test_branding_change_lists_the_fields(self):
        resp = self.branding(tagline='We ship boats', support_email='help@example.com')
        self.assertEqual(resp.status_code, 302)
        event = self.event('organization.settings_changed')
        self.assertTarget(event, 'accounts.organization', self.org.pk, 'Mine Org')
        self.assertEqual(event.details, {'fields': ['support_email', 'tagline']})
        self.assertNoSecrets(event, 'We ship boats', 'help@example.com')

    def test_organisation_rename_keeps_old_and_new_name(self):
        self.branding(name='Mine Ltd')
        event = self.event('organization.settings_changed')
        self.assertEqual(event.details, {
            'fields': ['name'], 'old_name': 'Mine Org', 'new_name': 'Mine Ltd',
        })

    def test_branding_saved_unchanged_records_nothing(self):
        self.assertEqual(self.branding().status_code, 302)
        self.assertNothingRecorded('organization.settings_changed')

    def terminology(self, **changes):
        data = Terms().as_dict()
        data.update(changes)
        return self.client.post(reverse('accounts:org_terminology'), data)

    def test_terminology_change_lists_the_terms(self):
        resp = self.terminology(rock='Rock', rocks='Rocks')
        self.assertEqual(resp.status_code, 302)
        event = self.event('organization.terminology_changed')
        self.assertTarget(event, 'accounts.organization', self.org.pk, 'Mine Org')
        self.assertEqual(event.details, {'terms': ['rock', 'rocks']})

    def test_terminology_reset_is_marked(self):
        self.org.terminology = {'todo': 'Task'}
        self.org.save()
        self.client.post(reverse('accounts:org_terminology'), {'reset': '1'})
        event = self.event('organization.terminology_changed')
        self.assertEqual(event.details, {'terms': ['todo'], 'reset': True})

    def test_terminology_saved_unchanged_records_nothing(self):
        self.terminology()
        self.client.post(reverse('accounts:org_terminology'), {'reset': '1'})
        self.assertNothingRecorded('organization.terminology_changed')


class AccountSecurityEventTest(AuditTestCase):
    """Changes a user makes to their own account, here as the plain member."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.member)

    def own_event(self, action):
        event = self.event(action, actor=self.member)
        self.assertTarget(event, 'auth.user', self.member.pk, 'minemember')
        return event

    def verified_device(self):
        device = TOTPDevice.objects.create(
            user=self.member, name='Authenticator app', confirmed=True,
        )
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()
        return device

    def test_two_factor_enabled(self):
        self.client.get(reverse('accounts:two_factor_setup'))
        device = TOTPDevice.objects.get(user=self.member)
        resp = self.client.post(reverse('accounts:two_factor_setup'), {'token': totp_code(device)})
        self.assertContains(resp, 'backup-codes')
        event = self.own_event('user.two_factor_enabled')
        self.assertEqual(event.details, {'replaced_existing': False})
        codes = StaticToken.objects.filter(device__user=self.member).values_list('token', flat=True)
        self.assertEqual(len(codes), 10)
        self.assertNoSecrets(event, device.key, *codes)

    def test_two_factor_disabled(self):
        device = self.verified_device()
        resp = self.client.post(reverse('accounts:two_factor_disable'), {'password': PASSWORD})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(TOTPDevice.objects.filter(user=self.member).exists())
        event = self.own_event('user.two_factor_disabled')
        self.assertNoSecrets(event, device.key)

    def test_two_factor_not_disabled_with_wrong_password_records_nothing(self):
        self.verified_device()
        self.client.post(reverse('accounts:two_factor_disable'), {'password': 'wrong'})
        self.assertNothingRecorded('user.two_factor_disabled')

    def test_backup_codes_regenerated(self):
        self.verified_device()
        resp = self.client.post(
            reverse('accounts:two_factor_backup_codes'), {'password': PASSWORD},
        )
        self.assertEqual(resp.status_code, 200)
        codes = StaticToken.objects.filter(device__user=self.member).values_list('token', flat=True)
        self.assertEqual(len(codes), 10)
        event = self.own_event('user.backup_codes_regenerated')
        self.assertNoSecrets(event, *codes)

    def test_password_changed(self):
        resp = self.client.post(reverse('password_change'), {
            'old_password': PASSWORD, 'new_password1': NEW_PASSWORD,
            'new_password2': NEW_PASSWORD,
        })
        self.assertRedirects(resp, reverse('password_change_done'), fetch_redirect_response=False)
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password(NEW_PASSWORD))
        event = self.own_event('user.password_changed')
        self.assertNoSecrets(event, self.member.password)

    def test_password_change_that_fails_records_nothing(self):
        self.client.post(reverse('password_change'), {
            'old_password': 'wrong', 'new_password1': NEW_PASSWORD,
            'new_password2': NEW_PASSWORD,
        })
        self.assertNothingRecorded('user.password_changed')

    def test_password_reset_completed(self):
        self.client.logout()
        AuditEvent.objects.all().delete()
        token = default_token_generator.make_token(self.member)
        uid = urlsafe_base64_encode(force_bytes(self.member.pk))
        resp = self.client.get(reverse('password_reset_confirm', args=[uid, token]))
        self.assertEqual(resp.status_code, 302)
        resp = self.client.post(resp['Location'], {
            'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD,
        })
        self.assertRedirects(resp, reverse('password_reset_complete'), fetch_redirect_response=False)
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password(NEW_PASSWORD))
        event = self.own_event('user.password_reset')
        self.assertNoSecrets(event, token, uid, self.member.password)

    def test_password_reset_with_a_bad_link_records_nothing(self):
        self.client.logout()
        uid = urlsafe_base64_encode(force_bytes(self.member.pk))
        self.client.post(
            reverse('password_reset_confirm', args=[uid, 'set-password']),
            {'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD},
        )
        self.assertNothingRecorded('user.password_reset')

    def test_email_change_is_noted_without_the_addresses(self):
        resp = self.client.post(reverse('accounts:profile_edit'), {
            'first_name': '', 'last_name': '', 'email': 'elsewhere@example.org',
        })
        self.assertEqual(resp.status_code, 302)
        event = self.own_event('user.email_changed')
        self.assertEqual(event.details, {})
        self.assertNoSecrets(event, 'elsewhere@example.org', 'minemember@example.com')

    def test_profile_saved_with_the_same_email_records_nothing(self):
        self.client.post(reverse('accounts:profile_edit'), {
            'first_name': 'Min', 'last_name': '', 'email': 'minemember@example.com',
        })
        self.assertNothingRecorded('user.email_changed')

    def test_account_change_is_shown_to_every_organisation_the_user_belongs_to(self):
        Membership.objects.create(user=self.member, organization=self.other_org)
        record_for_user('user.password_changed', self.member)
        events = AuditEvent.objects.filter(action='user.password_changed')
        self.assertEqual(
            sorted(e.organization.name for e in events), ['Mine Org', 'Theirs Org'],
        )

    def test_account_change_for_a_user_without_an_organisation_is_unattributed(self):
        loner = User.objects.create_user(username='loner', password=PASSWORD)
        [event] = record_for_user('user.password_changed', loner)
        self.assertIsNone(event.organization)
        self.assertEqual(event.actor, loner)


class DeletionEventTest(AuditTestCase):
    """Each deletion keeps the record's type, id, title and team as they were."""

    def assertDeletion(self, action, target_type, pk, label, **details):
        event = self.event(action)
        self.assertTarget(event, target_type, pk, label)
        self.assertEqual(event.details, details)
        return event

    def team_details(self, title):
        return {'title': title, 'team_id': self.team.pk, 'team': 'Mine Team'}

    def test_priority_deleted(self):
        rock = Rock.objects.create(
            title='Open Lisbon office', description='Confidential plan', owner=self.member,
            team=self.team, quarter=1, year=2026, due_date=date(2026, 3, 31),
        )
        pk = rock.pk
        resp = self.client.post(reverse('rocks:delete', args=[pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Rock.objects.filter(pk=pk).exists())
        event = self.assertDeletion(
            'rock.deleted', 'rocks.rock', pk, 'Open Lisbon office',
            **self.team_details('Open Lisbon office'),
        )
        self.assertNoSecrets(event, 'Confidential plan')

    def test_action_deleted(self):
        todo = ToDo.objects.create(title='Call the bank', owner=self.member, team=self.team)
        pk = todo.pk
        self.client.post(reverse('todos:delete', args=[pk]))
        self.assertFalse(ToDo.objects.filter(pk=pk).exists())
        self.assertDeletion(
            'todo.deleted', 'todos.todo', pk, 'Call the bank',
            **self.team_details('Call the bank'),
        )

    def test_blocker_deleted(self):
        second = Team.objects.create(organization=self.org, name='Second Team')
        issue = Issue.objects.create(
            title='Slow invoicing', originating_team=self.team, delegated_to_team=second,
            created_by=self.member,
        )
        pk = issue.pk
        self.client.post(reverse('issues:delete', args=[pk]))
        self.assertFalse(Issue.objects.filter(pk=pk).exists())
        self.assertDeletion(
            'issue.deleted', 'issues.issue', pk, 'Slow invoicing',
            delegated_to_team_id=second.pk, delegated_to_team='Second Team',
            **self.team_details('Slow invoicing'),
        )

    def scorecard(self):
        scorecard = Scorecard.objects.create(name='Sales', team=self.team)
        metric = ScorecardMetric.objects.create(
            scorecard=scorecard, name='Calls made', owner=self.member, goal_value=10,
        )
        return scorecard, metric

    def test_metrics_board_deleted(self):
        scorecard, _ = self.scorecard()
        pk = scorecard.pk
        self.client.post(reverse('scorecards:delete', args=[pk]))
        self.assertFalse(Scorecard.objects.filter(pk=pk).exists())
        self.assertDeletion(
            'scorecard.deleted', 'scorecards.scorecard', pk, 'Sales (Mine Team)',
            metrics=1, **self.team_details('Sales'),
        )

    def test_metric_removed(self):
        scorecard, metric = self.scorecard()
        self.client.post(reverse('scorecards:metric_delete', args=[metric.pk]))
        metric.refresh_from_db()
        self.assertFalse(metric.is_active)
        self.assertDeletion(
            'scorecard.metric_removed', 'scorecards.scorecardmetric', metric.pk,
            'Calls made (Sales)', scorecard_id=scorecard.pk, scorecard='Sales',
            **self.team_details('Calls made'),
        )

    def test_chart_node_deleted_counts_what_went_with_it(self):
        node = AccountabilityNode.objects.create(organization=self.org, name='Operations')
        child = AccountabilityNode.objects.create(
            organization=self.org, name='Warehouse', parent=node,
        )
        AccountabilityNode.objects.create(organization=self.org, name='Picker', parent=child)
        pk = node.pk
        self.client.post(reverse('accountability:node_delete', args=[pk]))
        self.assertFalse(AccountabilityNode.objects.filter(organization=self.org).exists())
        self.assertDeletion(
            'chart.node_deleted', 'accountability.accountabilitynode', pk,
            'Operations (Mine Org)', title='Operations', node_type='seat', nodes_beneath=2,
        )

    def test_chart_accountability_deleted(self):
        node = AccountabilityNode.objects.create(organization=self.org, name='Operations')
        role = AccountabilityRole.objects.create(node=node, description='Ship on time')
        pk = role.pk
        self.client.post(reverse('accountability:role_delete', args=[pk]))
        self.assertFalse(AccountabilityRole.objects.filter(pk=pk).exists())
        self.assertDeletion(
            'chart.role_deleted', 'accountability.accountabilityrole', pk, 'Ship on time',
            title='Ship on time', node_id=node.pk, node='Operations',
        )

    def test_core_value_deleted(self):
        value = VTOCoreValue.objects.create(
            vto=VTO.for_org(self.org), name='Candour', description='Say the hard thing',
        )
        pk = value.pk
        self.client.post(reverse('vision:cv_delete', args=[pk]))
        self.assertFalse(VTOCoreValue.objects.filter(pk=pk).exists())
        event = self.assertDeletion(
            'vision.core_value_deleted', 'vto.vtocorevalue', pk, 'Candour', title='Candour',
        )
        self.assertNoSecrets(event, 'Say the hard thing')

    def test_vision_section_cleared(self):
        key, spec = next(iter(section_specs_for(self.org).items()))
        section = VTOSection.objects.create(
            vto=VTO.for_org(self.org), key=key, content='Our ten year target',
        )
        url = reverse('vision:section_edit', args=[key])
        self.client.post(url, {'content': 'Our eleven year target'})
        self.assertNothingRecorded('vision.section_cleared')
        self.client.post(url, {'content': ''})
        event = self.event('vision.section_cleared')
        self.assertEqual(event.target_type, 'vto.vtosection')
        self.assertEqual(event.target_id, str(section.pk))
        self.assertEqual(event.details, {'title': spec.edit_label, 'key': key})
        self.assertNoSecrets(event, 'year target')
        # Saving an already empty section again is not another clearing.
        self.client.post(url, {'content': ''})
        self.event('vision.section_cleared')

    def test_another_organisations_record_is_not_deleted_or_recorded(self):
        their_team = Team.objects.create(organization=self.other_org, name='Theirs Team')
        todo = ToDo.objects.create(title='Theirs', owner=self.other_admin, team=their_team)
        resp = self.client.post(reverse('todos:delete', args=[todo.pk]))
        self.assertEqual(resp.status_code, 404)
        self.assertNothingRecorded('todo.deleted')

    def test_snapshot_outlives_the_row(self):
        todo = ToDo.objects.create(title='Short-lived', owner=self.member, team=self.team)
        kept = snapshot(todo)
        pk = todo.pk
        todo.delete()
        event = record('todo.deleted', target=kept)
        self.assertTarget(event, 'todos.todo', pk, 'Short-lived')


class AuditPageTest(AuditTestCase):
    """Who may read these events, and finding one among many."""

    def setUp(self):
        super().setUp()
        self.url = reverse('audit:event_list')
        todo = ToDo.objects.create(title='Call the bank', owner=self.member, team=self.team)
        self.client.post(reverse('todos:delete', args=[todo.pk]))
        self.client.post(reverse('accounts:team_create'), {'name': 'Finance'})
        self.client.post(reverse('accounts:team_members', args=[self.team.pk]), {
            'users': [self.admin.pk],
        })

    def actions(self, **params):
        resp = self.client.get(self.url, params)
        self.assertEqual(resp.status_code, 200)
        return sorted(e.action for e in resp.context['events'])

    def test_admin_sees_the_new_events(self):
        self.assertEqual(self.actions(), [
            'team.created', 'team.member_removed', 'todo.deleted', 'user.login',
        ])

    def test_member_cannot_read_the_log(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.get(self.url, {'q': 'bank'}).status_code, 403)

    def test_another_organisations_admin_sees_none_of_them(self):
        # A fresh browser: the admin's one-off notices travel in this client's cookies.
        self.client = self.client_class()
        self.client.force_login(self.other_admin)
        resp = self.client.get(self.url)
        self.assertEqual([e.action for e in resp.context['events']], ['user.login'])
        self.assertNotContains(resp, 'Call the bank')
        self.assertNotContains(resp, 'Finance')
        self.assertNotContains(resp, 'minemember')
        for params in ({'q': 'bank'}, {'q': 'minemember'}, {'action': 'todo.deleted'}):
            self.assertEqual(len(self.client.get(self.url, params).context['events']), 0)
        self.assertNotIn('todo.deleted', list(resp.context['actions']))

    def test_filter_by_action(self):
        self.assertEqual(self.actions(action='todo.deleted'), ['todo.deleted'])

    def test_search_finds_a_deleted_records_title(self):
        self.assertEqual(self.actions(q='call the BANK'), ['todo.deleted'])

    def test_search_finds_a_person_as_target_and_inside_details(self):
        self.assertEqual(self.actions(q='minemember'), ['team.member_removed'])

    def test_search_finds_a_team_name_inside_details(self):
        self.assertEqual(self.actions(q='Mine Team'), ['team.member_removed', 'todo.deleted'])

    def test_search_and_action_filter_combine(self):
        self.assertEqual(self.actions(q='Mine Team', action='todo.deleted'), ['todo.deleted'])
        self.assertEqual(self.actions(q='Finance', action='todo.deleted'), [])

    def test_no_match_shows_the_empty_state_with_a_way_back(self):
        resp = self.client.get(self.url, {'q': 'nothing like this'})
        self.assertContains(resp, 'No events match this filter')
        self.assertContains(resp, 'Show all events')

    def test_paging_keeps_search_and_action(self):
        for _ in range(55):
            record(
                'todo.deleted', organization=self.org, actor=self.admin,
                details={'title': 'Bulk tidy'},
            )
        resp = self.client.get(self.url, {'q': 'bulk', 'action': 'todo.deleted'})
        self.assertTrue(resp.context['is_paginated'])
        self.assertContains(resp, '?page=2&amp;action=todo.deleted&amp;q=bulk')
        resp = self.client.get(self.url, {'q': 'bulk', 'action': 'todo.deleted', 'page': 2})
        self.assertEqual(len(resp.context['events']), 5)

    def test_page_describes_events_in_the_organisations_words(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Action deleted')
        self.assertContains(resp, '<label for="audit-q"')
        self.org.terminology = {'todo': 'Task'}
        self.org.save()
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Task deleted')
        self.assertContains(resp, 'Task deleted (todo.deleted)')


class EventCatalogueTest(TestCase):
    def test_describe(self):
        self.assertEqual(describe('rock.deleted'), 'Priority deleted')
        self.assertEqual(describe('rock.deleted', Terms({'rock': 'Goal'})), 'Goal deleted')
        self.assertEqual(describe('user.login'), 'Signed in')
        self.assertEqual(describe('made.up'), '')

    def test_every_description_can_be_filled_in(self):
        for action in EVENTS:
            self.assertTrue(describe(action), action)

    def test_readme_lists_every_event(self):
        readme = Path(settings.BASE_DIR, 'README.md').read_text()
        for action in EVENTS:
            self.assertIn(f'`{action}`', readme, f'{action} is missing from the README')

    def test_every_recorded_action_is_in_the_catalogue(self):
        recorded = set()
        for path in Path(settings.BASE_DIR, 'apps').rglob('*.py'):
            if 'test' in path.name or 'tests' in path.parts:
                continue
            recorded.update(re.findall(
                r"""record(?:_for_user)?\(\s*'([a-z_]+(?:\.[a-z_]+)+)'""", path.read_text(),
            ))
        self.assertEqual(recorded, set(EVENTS))
