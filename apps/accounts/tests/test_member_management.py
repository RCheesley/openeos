from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.accountability.models import AccountabilityNode
from apps.accounts.members import (
    KIND_METRICS, KIND_ROCKS, KIND_SEATS, KIND_TODOS, LastAdminError, change_role,
    owned_records, remove_member,
)
from apps.accounts.models import Membership, Organization, OrganizationDomain, Team
from apps.audit.models import AuditEvent
from apps.issues.models import Issue
from apps.rocks.models import Rock
from apps.scorecards.models import Scorecard, ScorecardMetric
from apps.todos.models import ToDo


class MemberFixtureMixin:
    """Alpha Org with an admin, a leaver and a successor; the leaver also belongs to Beta Org."""

    def setUp(self):
        self.org = Organization.objects.create(name='Alpha Org')
        self.team = Team.objects.create(organization=self.org, name='Alpha Team')
        self.admin = self.make_user('boss', Membership.ROLE_ADMIN)
        self.leaver = self.make_user('leaver')
        self.successor = self.make_user('successor')
        self.leaver_membership = Membership.objects.get(user=self.leaver, organization=self.org)

        self.other_org = Organization.objects.create(name='Beta Org')
        self.other_team = Team.objects.create(organization=self.other_org, name='Beta Team')
        Membership.objects.create(
            user=self.leaver, organization=self.other_org, role=Membership.ROLE_ADMIN
        )
        self.leaver.profile.teams.add(self.other_team)
        self.client.force_login(self.admin)

    def make_user(self, username, role=Membership.ROLE_MEMBER, org=None, team=None):
        user = User.objects.create_user(username=username, password='pw')
        Membership.objects.create(user=user, organization=org or self.org, role=role)
        user.profile.teams.add(team or self.team)
        return user

    def rock(self, team=None, owner=None, **kwargs):
        return Rock.objects.create(
            title='A Rock', owner=owner or self.leaver, team=team or self.team,
            quarter=1, year=2026, due_date=date(2026, 3, 31), **kwargs,
        )

    def todo(self, team=None, **kwargs):
        return ToDo.objects.create(
            title='A To-Do', owner=self.leaver, team=team or self.team, **kwargs,
        )

    def metric(self, team=None, **kwargs):
        scorecard = Scorecard.objects.create(name='Board', team=team or self.team)
        return ScorecardMetric.objects.create(
            scorecard=scorecard, name='A metric', owner=self.leaver, goal_value=1, **kwargs,
        )

    def seat(self, org=None):
        return AccountabilityNode.objects.create(
            organization=org or self.org, name='A seat', owner=self.leaver,
        )

    def url(self, name, membership=None):
        return f'/users/{(membership or self.leaver_membership).pk}/{name}/'

    def events(self, action):
        return AuditEvent.objects.filter(action=action)


class RoleChangeTest(MemberFixtureMixin, TestCase):
    def test_admin_changes_a_members_role(self):
        resp = self.client.post(self.url('role'), {'role': Membership.ROLE_LEADER})
        self.assertRedirects(resp, '/users/')
        self.leaver_membership.refresh_from_db()
        self.assertEqual(self.leaver_membership.role, Membership.ROLE_LEADER)

    def test_role_in_another_organisation_is_untouched(self):
        self.client.post(self.url('role'), {'role': Membership.ROLE_LEADER})
        other = Membership.objects.get(user=self.leaver, organization=self.other_org)
        self.assertEqual(other.role, Membership.ROLE_ADMIN)

    def test_role_change_is_audited_with_actor_and_target(self):
        self.client.post(self.url('role'), {'role': Membership.ROLE_ADMIN})
        event = self.events('member.role_changed').get()
        self.assertEqual(event.actor, self.admin)
        self.assertEqual(event.organization, self.org)
        self.assertEqual(event.target_type, 'auth.user')
        self.assertEqual(event.target_id, str(self.leaver.pk))
        self.assertEqual(event.details['old_role'], Membership.ROLE_MEMBER)
        self.assertEqual(event.details['new_role'], Membership.ROLE_ADMIN)

    def test_saving_the_same_role_writes_no_audit_event(self):
        self.client.post(self.url('role'), {'role': Membership.ROLE_MEMBER})
        self.assertFalse(self.events('member.role_changed').exists())

    def test_last_admin_cannot_demote_themselves(self):
        mine = Membership.objects.get(user=self.admin, organization=self.org)
        resp = self.client.post(self.url('role', mine), {'role': Membership.ROLE_MEMBER})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'is the only admin of Alpha Org')
        mine.refresh_from_db()
        self.assertEqual(mine.role, Membership.ROLE_ADMIN)
        self.assertFalse(self.events('member.role_changed').exists())

    def test_last_admin_cannot_be_demoted_by_a_superuser(self):
        root = User.objects.create_superuser(username='root', password='pw')
        self.client.force_login(root)
        mine = Membership.objects.get(user=self.admin, organization=self.org)
        Membership.objects.create(user=root, organization=self.org)
        resp = self.client.post(self.url('role', mine), {'role': Membership.ROLE_LEADER})
        self.assertEqual(resp.status_code, 200)
        mine.refresh_from_db()
        self.assertEqual(mine.role, Membership.ROLE_ADMIN)

    def test_admin_may_step_down_when_another_admin_exists(self):
        self.leaver_membership.role = Membership.ROLE_ADMIN
        self.leaver_membership.save()
        mine = Membership.objects.get(user=self.admin, organization=self.org)
        resp = self.client.post(self.url('role', mine), {'role': Membership.ROLE_MEMBER})
        self.assertRedirects(resp, '/', fetch_redirect_response=False)
        mine.refresh_from_db()
        self.assertEqual(mine.role, Membership.ROLE_MEMBER)
        self.assertEqual(self.client.get('/users/').status_code, 403)

    def test_service_refuses_to_demote_the_last_admin(self):
        mine = Membership.objects.get(user=self.admin, organization=self.org)
        with self.assertRaises(LastAdminError):
            change_role(mine, Membership.ROLE_MEMBER)

    def test_unknown_role_is_rejected(self):
        resp = self.client.post(self.url('role'), {'role': 'owner'})
        self.assertEqual(resp.status_code, 200)
        self.leaver_membership.refresh_from_db()
        self.assertEqual(self.leaver_membership.role, Membership.ROLE_MEMBER)


class RemoveMemberTest(MemberFixtureMixin, TestCase):
    def test_removal_without_owned_records(self):
        resp = self.client.get(self.url('remove'))
        self.assertContains(resp, 'owns nothing open in Alpha Org')
        self.assertNotContains(resp, 'Who takes over?')

        resp = self.client.post(self.url('remove'), {})
        self.assertRedirects(resp, '/users/')
        self.assertFalse(Membership.objects.filter(pk=self.leaver_membership.pk).exists())
        self.assertNotIn(self.team, self.leaver.profile.teams.all())

    def test_removal_keeps_the_account_and_the_other_organisation(self):
        self.client.post(self.url('remove'), {})
        self.leaver.refresh_from_db()
        self.assertTrue(self.leaver.is_active)
        self.assertTrue(
            Membership.objects.filter(user=self.leaver, organization=self.other_org).exists()
        )
        self.assertIn(self.other_team, self.leaver.profile.teams.all())

    def test_confirmation_lists_what_the_member_owns(self):
        self.rock()
        self.rock()
        self.todo()
        self.metric()
        self.seat()
        Issue.objects.create(title='Raised', originating_team=self.team, created_by=self.leaver)
        resp = self.client.get(self.url('remove'))
        form = resp.context['form']
        self.assertEqual(
            form.counts, {KIND_ROCKS: 2, KIND_TODOS: 1, KIND_METRICS: 1, KIND_SEATS: 1}
        )
        self.assertEqual(form.issues_raised, 1)
        self.assertContains(resp, 'Open Priorities')
        self.assertContains(resp, 'Who takes over?')
        self.assertNotIn(self.leaver, form.fields['new_owner'].queryset)
        self.assertIn(self.successor, form.fields['new_owner'].queryset)

    def test_removal_with_owned_records_needs_a_new_owner(self):
        rock = self.rock()
        resp = self.client.post(self.url('remove'), {})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Choose who takes over these records.')
        self.assertTrue(Membership.objects.filter(pk=self.leaver_membership.pk).exists())
        rock.refresh_from_db()
        self.assertEqual(rock.owner, self.leaver)

    def test_removal_hands_over_live_records_and_keeps_history(self):
        rock = self.rock()
        done_rock = self.rock(status=Rock.STATUS_COMPLETE)
        dropped_rock = self.rock(status=Rock.STATUS_DROPPED)
        todo = self.todo()
        done_todo = self.todo(status=ToDo.STATUS_COMPLETE)
        metric = self.metric()
        old_metric = self.metric(is_active=False)
        seat = self.seat()
        issue = Issue.objects.create(
            title='Raised', originating_team=self.team, created_by=self.leaver,
        )

        resp = self.client.post(self.url('remove'), {'new_owner': self.successor.pk})
        self.assertRedirects(resp, '/users/')

        for moved in (rock, todo, metric, seat):
            moved.refresh_from_db()
            self.assertEqual(moved.owner, self.successor, moved)
        for kept in (done_rock, dropped_rock, done_todo, old_metric):
            kept.refresh_from_db()
            self.assertEqual(kept.owner, self.leaver, kept)
        issue.refresh_from_db()
        self.assertEqual(issue.created_by, self.leaver)
        self.assertFalse(Membership.objects.filter(pk=self.leaver_membership.pk).exists())

    def test_removal_leaves_another_organisations_records_alone(self):
        self.rock()
        other_rock = self.rock(team=self.other_team)
        other_todo = self.todo(team=self.other_team)
        other_metric = self.metric(team=self.other_team)
        other_seat = self.seat(org=self.other_org)
        self.client.post(self.url('remove'), {'new_owner': self.successor.pk})
        for record in (other_rock, other_todo, other_metric, other_seat):
            record.refresh_from_db()
            self.assertEqual(record.owner, self.leaver, record)

    def test_seats_can_be_left_vacant(self):
        seat = self.seat()
        resp = self.client.post(self.url('remove'), {'vacate_seats': 'on'})
        self.assertRedirects(resp, '/users/')
        seat.refresh_from_db()
        self.assertIsNone(seat.owner)

    def test_seats_need_an_owner_unless_left_vacant(self):
        seat = self.seat()
        resp = self.client.post(self.url('remove'), {})
        self.assertEqual(resp.status_code, 200)
        seat.refresh_from_db()
        self.assertEqual(seat.owner, self.leaver)

    def test_new_owner_must_be_a_member_of_this_organisation(self):
        self.rock()
        outsider = self.make_user('outsider', org=self.other_org, team=self.other_team)
        resp = self.client.post(self.url('remove'), {'new_owner': outsider.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Membership.objects.filter(pk=self.leaver_membership.pk).exists())

    def test_member_cannot_take_over_their_own_records(self):
        self.rock()
        resp = self.client.post(self.url('remove'), {'new_owner': self.leaver.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Membership.objects.filter(pk=self.leaver_membership.pk).exists())

    def test_new_owner_must_be_in_the_records_team(self):
        second_team = Team.objects.create(organization=self.org, name='Second Team')
        self.leaver.profile.teams.add(second_team)
        rock = self.rock(team=second_team)
        resp = self.client.post(self.url('remove'), {'new_owner': self.successor.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'is not in Second Team')
        rock.refresh_from_db()
        self.assertEqual(rock.owner, self.leaver)
        self.assertTrue(Membership.objects.filter(pk=self.leaver_membership.pk).exists())

    def test_nothing_changes_if_removal_fails_part_way(self):
        rock = self.rock()
        with self.assertRaises(ValueError):
            remove_member(self.leaver_membership, new_owner=None)
        rock.refresh_from_db()
        self.assertEqual(rock.owner, self.leaver)
        self.assertTrue(Membership.objects.filter(pk=self.leaver_membership.pk).exists())
        self.assertIn(self.team, self.leaver.profile.teams.all())

    def test_last_admin_cannot_be_removed(self):
        root = User.objects.create_superuser(username='root', password='pw')
        self.client.force_login(root)
        mine = Membership.objects.get(user=self.admin, organization=self.org)
        Membership.objects.create(user=root, organization=self.org)
        for method in (self.client.get, self.client.post):
            resp = method(self.url('remove', mine), follow=True)
            self.assertContains(resp, 'is the only admin of Alpha Org')
        self.assertTrue(Membership.objects.filter(pk=mine.pk).exists())
        with self.assertRaises(LastAdminError):
            remove_member(mine)

    def test_admin_cannot_remove_themselves(self):
        self.leaver_membership.role = Membership.ROLE_ADMIN
        self.leaver_membership.save()
        mine = Membership.objects.get(user=self.admin, organization=self.org)
        resp = self.client.post(self.url('remove', mine), {}, follow=True)
        self.assertContains(resp, 'You cannot remove yourself')
        self.assertTrue(Membership.objects.filter(pk=mine.pk).exists())

    def test_removal_and_hand_over_are_audited(self):
        self.rock()
        self.todo()
        self.client.post(self.url('remove'), {'new_owner': self.successor.pk})
        removed = self.events('member.removed').get()
        self.assertEqual(removed.actor, self.admin)
        self.assertEqual(removed.organization, self.org)
        self.assertEqual(removed.target_id, str(self.leaver.pk))
        self.assertEqual(removed.details['username'], 'leaver')
        moved = self.events('member.records_reassigned').get()
        self.assertEqual(moved.target_id, str(self.leaver.pk))
        self.assertEqual(moved.details['new_owner'], 'successor')
        self.assertEqual(moved.details['moved'][KIND_ROCKS], 1)
        self.assertEqual(moved.details['moved'][KIND_TODOS], 1)

    def test_removal_with_nothing_to_move_writes_only_the_removal_event(self):
        self.client.post(self.url('remove'), {})
        self.assertTrue(self.events('member.removed').exists())
        self.assertFalse(self.events('member.records_reassigned').exists())

    def test_user_list_offers_the_actions(self):
        resp = self.client.get('/users/')
        self.assertContains(resp, self.url('role'))
        self.assertContains(resp, self.url('reassign'))
        self.assertContains(resp, self.url('remove'))
        mine = Membership.objects.get(user=self.admin, organization=self.org)
        self.assertNotContains(resp, self.url('remove', mine))


class ReassignTest(MemberFixtureMixin, TestCase):
    def test_hands_over_chosen_kinds_and_keeps_the_member(self):
        rock = self.rock()
        todo = self.todo()
        metric = self.metric()
        seat = self.seat()
        resp = self.client.post(self.url('reassign'), {
            'new_owner': self.successor.pk, 'kinds': [KIND_ROCKS, KIND_METRICS],
        })
        self.assertRedirects(resp, '/users/')
        for moved in (rock, metric):
            moved.refresh_from_db()
            self.assertEqual(moved.owner, self.successor, moved)
        for kept in (todo, seat):
            kept.refresh_from_db()
            self.assertEqual(kept.owner, self.leaver, kept)
        self.assertTrue(Membership.objects.filter(pk=self.leaver_membership.pk).exists())
        self.assertIn(self.team, self.leaver.profile.teams.all())

    def test_moves_nothing_finished_and_nothing_in_another_organisation(self):
        self.rock()
        done_rock = self.rock(status=Rock.STATUS_COMPLETE)
        done_todo = self.todo(status=ToDo.STATUS_COMPLETE)
        other_rock = self.rock(team=self.other_team)
        other_seat = self.seat(org=self.other_org)
        someone_elses = self.rock(owner=self.admin)
        self.client.post(self.url('reassign'), {
            'new_owner': self.successor.pk, 'kinds': [KIND_ROCKS],
        })
        for kept in (done_rock, done_todo, other_rock, other_seat):
            kept.refresh_from_db()
            self.assertEqual(kept.owner, self.leaver, kept)
        someone_elses.refresh_from_db()
        self.assertEqual(someone_elses.owner, self.admin)
        self.assertEqual(Rock.objects.filter(owner=self.successor).count(), 1)

    def test_needs_a_new_owner_and_a_kind(self):
        rock = self.rock()
        for data in ({'kinds': [KIND_ROCKS]}, {'new_owner': self.successor.pk}):
            resp = self.client.post(self.url('reassign'), data)
            self.assertEqual(resp.status_code, 200)
        rock.refresh_from_db()
        self.assertEqual(rock.owner, self.leaver)

    def test_kind_the_member_owns_nothing_of_is_not_offered(self):
        self.rock()
        resp = self.client.get(self.url('reassign'))
        kinds = [value for value, _ in resp.context['form'].fields['kinds'].choices]
        self.assertEqual(kinds, [KIND_ROCKS])

    def test_page_says_so_when_there_is_nothing_to_hand_over(self):
        resp = self.client.get(self.url('reassign'))
        self.assertContains(resp, 'there is nothing to hand over')

    def test_hand_over_is_audited(self):
        self.rock()
        self.client.post(self.url('reassign'), {
            'new_owner': self.successor.pk, 'kinds': [KIND_ROCKS],
        })
        event = self.events('member.records_reassigned').get()
        self.assertEqual(event.actor, self.admin)
        self.assertEqual(event.organization, self.org)
        self.assertEqual(event.target_id, str(self.leaver.pk))
        self.assertEqual(event.details['new_owner_id'], self.successor.pk)
        self.assertEqual(event.details['moved'], {KIND_ROCKS: 1})

    def test_owned_records_ignores_other_organisations(self):
        self.rock(team=self.other_team)
        self.assertFalse(owned_records(self.leaver, self.org)[KIND_ROCKS].exists())
        self.assertEqual(owned_records(self.leaver, self.other_org)[KIND_ROCKS].count(), 1)


class MemberManagementAccessTest(MemberFixtureMixin, TestCase):
    def test_non_admins_get_403(self):
        self.rock()
        for user in (self.successor, self.leaver):
            self.client.force_login(user)
            if user == self.leaver:
                self.client.post(f'/org/{self.org.pk}/switch/')
            for name in ('role', 'reassign', 'remove'):
                with self.subTest(user=user.username, name=name):
                    self.assertEqual(self.client.get(self.url(name)).status_code, 403)
                    resp = self.client.post(self.url(name), {
                        'role': Membership.ROLE_ADMIN, 'new_owner': self.successor.pk,
                        'kinds': [KIND_ROCKS],
                    })
                    self.assertEqual(resp.status_code, 403)
        self.leaver_membership.refresh_from_db()
        self.assertEqual(self.leaver_membership.role, Membership.ROLE_MEMBER)
        self.assertEqual(Rock.objects.get().owner, self.leaver)

    def test_anonymous_is_sent_to_login(self):
        self.client.logout()
        resp = self.client.get(self.url('remove'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login/', resp['Location'])

    def test_admin_of_another_organisation_gets_404(self):
        # The leaver is an admin of Beta Org; with Beta active, Alpha's members are out of reach.
        self.client.force_login(self.leaver)
        self.client.post(f'/org/{self.other_org.pk}/switch/')
        target = Membership.objects.get(user=self.successor, organization=self.org)
        for name in ('role', 'reassign', 'remove'):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(self.url(name, target)).status_code, 404)
                resp = self.client.post(self.url(name, target), {'role': Membership.ROLE_ADMIN})
                self.assertEqual(resp.status_code, 404)
        target.refresh_from_db()
        self.assertEqual(target.role, Membership.ROLE_MEMBER)


class RemovedMemberAccessTest(MemberFixtureMixin, TestCase):
    """Someone signed in when they are removed is refused on their next request."""

    def setUp(self):
        super().setUp()
        self.only_alpha = self.make_user('onlyalpha')
        self.rock_pk = self.rock(owner=self.admin).pk

    def remove(self, user):
        remove_member(Membership.objects.get(user=user, organization=self.org))

    def test_member_of_one_organisation_loses_its_records(self):
        self.client.force_login(self.only_alpha)
        self.assertEqual(self.client.get(f'/rocks/{self.rock_pk}/').status_code, 200)
        self.remove(self.only_alpha)
        self.assertEqual(self.client.get(f'/rocks/{self.rock_pk}/').status_code, 404)
        resp = self.client.get('/')
        self.assertIsNone(resp.context['active_org'])
        self.assertIsNone(resp.context['active_team'])

    def test_member_of_two_organisations_falls_back_to_the_other(self):
        self.client.force_login(self.leaver)
        self.client.post(f'/org/{self.org.pk}/switch/')
        self.assertEqual(self.client.get(f'/rocks/{self.rock_pk}/').status_code, 200)
        self.remove(self.leaver)
        self.assertEqual(self.client.get(f'/rocks/{self.rock_pk}/').status_code, 404)
        resp = self.client.get('/')
        self.assertEqual(resp.context['active_org'], self.other_org)
        # Switching back is refused too.
        self.assertEqual(self.client.post(f'/org/{self.org.pk}/switch/').status_code, 404)

    def test_removed_admin_loses_the_user_list(self):
        self.leaver_membership.role = Membership.ROLE_ADMIN
        self.leaver_membership.save()
        self.client.force_login(self.leaver)
        self.client.post(f'/org/{self.org.pk}/switch/')
        self.assertContains(self.client.get('/users/'), 'Alpha Org')
        self.remove(self.leaver)
        # Beta Org, where they are still an admin, is now the active one.
        resp = self.client.get('/users/')
        self.assertContains(resp, 'Beta Org')
        self.assertNotContains(resp, 'Alpha Org')

    @override_settings(ALLOWED_HOSTS=['alpha.example.com', 'testserver'])
    def test_removed_member_is_refused_on_the_organisations_own_hostname(self):
        OrganizationDomain.objects.create(organization=self.org, hostname='alpha.example.com')
        self.client.force_login(self.only_alpha)
        host = {'HTTP_HOST': 'alpha.example.com'}
        self.assertEqual(self.client.get(f'/rocks/{self.rock_pk}/', **host).status_code, 200)
        self.remove(self.only_alpha)
        self.assertEqual(self.client.get(f'/rocks/{self.rock_pk}/', **host).status_code, 403)
        self.assertEqual(self.client.get('/', **host).status_code, 403)
