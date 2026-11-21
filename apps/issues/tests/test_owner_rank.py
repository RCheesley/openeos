import csv
import io
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Membership, Organization, Team
from apps.issues.models import Issue, IssueActivity
from apps.meetings.models import Meeting


class OwnerRankTestBase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Rank Org')
        self.team = Team.objects.create(organization=self.org, name='Rank Team')
        self.other_team = Team.objects.create(organization=self.org, name='Other Team')

        self.member = self.make_user('rankmember', self.team, first_name='Mina', last_name='Member')
        self.teammate = self.make_user('rankmate', self.team, first_name='Tom', last_name='Mate')
        self.outsider = self.make_user('rankoutsider', self.other_team)
        self.admin = self.make_user('rankadmin', self.other_team, role=Membership.ROLE_ADMIN)

        self.issue = Issue.objects.create(
            title='Slow invoices', originating_team=self.team, created_by=self.member,
        )
        self.client.force_login(self.member)

    def make_user(self, username, team, role=Membership.ROLE_MEMBER, **names):
        user = User.objects.create_user(username=username, password='pw', **names)
        Membership.objects.create(user=user, organization=self.org, role=role)
        user.profile.teams.add(team)
        return user

    def make_issue(self, title, rank=None, days_old=0, **kwargs):
        issue = Issue.objects.create(
            title=title, originating_team=self.team, created_by=self.member, rank=rank, **kwargs,
        )
        Issue.objects.filter(pk=issue.pk).update(
            created_at=timezone.now() - timedelta(days=days_old)
        )
        return issue

    def form_data(self, **overrides):
        data = {
            'title': 'Slow invoices', 'description': '', 'issue_type': Issue.TYPE_SHORT_TERM,
            'owner': '', 'delegated_to_team': '', 'linked_rocks': [],
            'target_quarter': '', 'target_year': '',
        }
        data.update(overrides)
        return data

    def last_activity(self, issue=None):
        return (issue or self.issue).activity.order_by('-pk').first()


class IssueOwnerTest(OwnerRankTestBase):
    def test_existing_issue_has_no_owner_and_no_rank(self):
        self.assertIsNone(self.issue.owner)
        self.assertIsNone(self.issue.rank)
        self.assertEqual(self.issue.rank_label, 'Not ranked')

    def test_form_offers_only_members_of_the_team_by_name(self):
        resp = self.client.get(f'/issues/{self.issue.pk}/edit/')
        owners = resp.context['form'].fields['owner'].queryset
        self.assertEqual(set(owners), {self.member, self.teammate})
        self.assertContains(resp, 'Mina Member</option>')
        self.assertContains(resp, 'No owner')

    def test_owner_is_optional_on_create(self):
        resp = self.client.post('/issues/new/', self.form_data(title='No owner needed'))
        issue = Issue.objects.get(title='No owner needed')
        self.assertRedirects(resp, f'/issues/{issue.pk}/')
        self.assertIsNone(issue.owner)
        self.assertFalse(
            issue.activity.filter(action=IssueActivity.ACTION_OWNER_CHANGED).exists()
        )

    def test_create_with_owner_records_it(self):
        self.client.post('/issues/new/', self.form_data(title='Owned', owner=self.teammate.pk))
        issue = Issue.objects.get(title='Owned')
        self.assertEqual(issue.owner, self.teammate)
        entry = issue.activity.get(action=IssueActivity.ACTION_OWNER_CHANGED)
        self.assertEqual(entry.notes, 'Owner set to Tom Mate.')
        self.assertEqual(entry.actor, self.member)

    def test_form_refuses_someone_who_is_not_on_the_team(self):
        resp = self.client.post(
            f'/issues/{self.issue.pk}/edit/', self.form_data(owner=self.outsider.pk),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.context['form'].errors['owner'], ['That person is not a member of Rank Team.'],
        )
        self.issue.refresh_from_db()
        self.assertIsNone(self.issue.owner)

    def test_edit_form_records_each_kind_of_change(self):
        url = f'/issues/{self.issue.pk}/edit/'
        self.client.post(url, self.form_data(owner=self.teammate.pk))
        self.assertEqual(self.last_activity().notes, 'Owner set to Tom Mate.')
        self.client.post(url, self.form_data(owner=self.member.pk))
        self.assertEqual(
            self.last_activity().notes, 'Owner changed from Tom Mate to Mina Member.',
        )
        self.client.post(url, self.form_data(owner=''))
        self.assertEqual(self.last_activity().notes, 'Owner removed (was Mina Member).')
        self.issue.refresh_from_db()
        self.assertIsNone(self.issue.owner)

    def test_edit_without_touching_the_owner_records_nothing(self):
        self.issue.owner = self.teammate
        self.issue.save()
        self.client.post(
            f'/issues/{self.issue.pk}/edit/',
            self.form_data(title='Renamed', owner=self.teammate.pk),
        )
        self.assertFalse(self.issue.activity.exists())

    def test_owner_address_sets_and_removes_the_owner(self):
        url = f'/issues/{self.issue.pk}/owner/'
        resp = self.client.post(url, {'owner': self.teammate.pk})
        self.assertRedirects(resp, f'/issues/{self.issue.pk}/')
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.owner, self.teammate)
        entry = self.last_activity()
        self.assertEqual(entry.action, IssueActivity.ACTION_OWNER_CHANGED)
        self.assertEqual(entry.notes, 'Owner set to Tom Mate.')

        self.client.post(url, {'owner': ''})
        self.issue.refresh_from_db()
        self.assertIsNone(self.issue.owner)
        self.assertEqual(self.last_activity().notes, 'Owner removed (was Tom Mate).')

    def test_owner_address_ignores_an_unchanged_owner(self):
        self.client.post(f'/issues/{self.issue.pk}/owner/', {'owner': ''})
        self.assertFalse(self.issue.activity.exists())

    def test_owner_address_refuses_someone_who_is_not_on_the_team(self):
        resp = self.client.post(
            f'/issues/{self.issue.pk}/owner/', {'owner': self.outsider.pk}, follow=True,
        )
        self.assertContains(resp, 'That person is not a member of Rank Team.')
        self.issue.refresh_from_db()
        self.assertIsNone(self.issue.owner)
        self.assertFalse(self.issue.activity.exists())

    def test_owner_address_is_post_only(self):
        self.assertEqual(self.client.get(f'/issues/{self.issue.pk}/owner/').status_code, 405)
        self.assertEqual(self.client.get(f'/issues/{self.issue.pk}/rank/').status_code, 405)

    def test_owner_shows_on_the_list_and_the_detail_page(self):
        self.issue.owner = self.teammate
        self.issue.save()
        self.assertContains(self.client.get('/issues/'), 'Owner: Tom Mate')
        resp = self.client.get(f'/issues/{self.issue.pk}/')
        self.assertContains(resp, '<dd class="col-6">Tom Mate</dd>', html=True)
        self.assertContains(resp, f'<option value="{self.teammate.pk}" selected>Tom Mate</option>',
                            html=True)

    def test_detail_page_says_when_there_is_no_owner(self):
        resp = self.client.get(f'/issues/{self.issue.pk}/')
        self.assertContains(resp, 'No owner')
        self.assertContains(resp, 'Not ranked')
        self.assertNotContains(self.client.get('/issues/'), 'Owner:')

    def test_owner_who_leaves_the_instance_leaves_the_issue_unowned(self):
        self.issue.owner = self.teammate
        self.issue.save()
        self.teammate.delete()
        self.issue.refresh_from_db()
        self.assertIsNone(self.issue.owner)


class IssueRankTest(OwnerRankTestBase):
    def rank(self, value, issue=None, **extra):
        issue = issue or self.issue
        return self.client.post(f'/issues/{issue.pk}/rank/', {'rank': value, **extra})

    def test_set_change_and_clear_are_each_recorded(self):
        self.rank(2)
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.rank, 2)
        entry = self.last_activity()
        self.assertEqual(entry.action, IssueActivity.ACTION_RANKED)
        self.assertEqual(entry.get_action_display(), 'Rank Changed')
        self.assertEqual(entry.notes, 'Rank set to 2.')
        self.assertEqual(entry.actor, self.member)

        self.rank(1)
        self.assertEqual(self.last_activity().notes, 'Rank changed from 2 to 1.')

        self.rank('')
        self.issue.refresh_from_db()
        self.assertIsNone(self.issue.rank)
        self.assertEqual(self.last_activity().notes, 'Rank cleared (was 1).')
        self.assertEqual(self.issue.activity.count(), 3)

    def test_same_rank_again_records_nothing(self):
        self.rank(3)
        self.rank(3)
        self.assertEqual(self.issue.activity.count(), 1)

    def test_a_rank_off_the_scale_is_ignored(self):
        for value in ('0', '4', '-1', 'high'):
            with self.subTest(value=value):
                self.rank(value)
                self.issue.refresh_from_db()
                self.assertIsNone(self.issue.rank)
        self.assertFalse(self.issue.activity.exists())

    def test_returns_to_the_row_on_the_page_it_was_set_from(self):
        resp = self.rank(1, next='/issues/?status=open')
        self.assertRedirects(
            resp, f'/issues/?status=open#issue-{self.issue.pk}', fetch_redirect_response=False,
        )

    def test_a_next_address_on_another_site_is_not_followed(self):
        resp = self.rank(1, next='https://example.com/elsewhere')
        self.assertRedirects(resp, f'/issues/{self.issue.pk}/')

    def test_list_puts_rank_one_first_unranked_last_and_the_oldest_first_within_a_rank(self):
        self.issue.delete()
        self.make_issue('Unranked new', days_old=1)
        self.make_issue('Unranked old', days_old=9)
        self.make_issue('Three', rank=3, days_old=5)
        self.make_issue('One new', rank=1, days_old=2)
        self.make_issue('One old', rank=1, days_old=8)
        self.make_issue('Two', rank=2, days_old=20)
        resp = self.client.get('/issues/')
        self.assertEqual(
            [issue.title for issue in resp.context['issues']],
            ['One old', 'One new', 'Two', 'Three', 'Unranked old', 'Unranked new'],
        )

    def test_rank_one_filter_narrows_the_list_and_the_csv(self):
        self.make_issue('Top', rank=1)
        self.make_issue('Second', rank=2)
        resp = self.client.get('/issues/?rank=1')
        self.assertEqual([issue.title for issue in resp.context['issues']], ['Top'])
        self.assertTrue(resp.context['rank_filter'])
        # The toggle now leads back to every rank.
        self.assertContains(resp, 'aria-current="true"')
        self.assertEqual(resp.context['rank_toggle_query'], '')

        rows = list(csv.reader(io.StringIO(
            self.client.get('/issues/export/?rank=1').content.decode()
        )))
        self.assertEqual([row[0] for row in rows[1:]], ['Top'])

    def test_rank_one_toggle_keeps_the_other_filters(self):
        resp = self.client.get('/issues/?status=all&type=short_term')
        self.assertFalse(resp.context['rank_filter'])
        self.assertEqual(resp.context['rank_toggle_query'], 'status=all&type=short_term&rank=1')
        resp = self.client.get('/issues/?status=all&rank=1')
        self.assertEqual(resp.context['rank_toggle_query'], 'status=all')

    def test_rank_one_filter_with_nothing_ranked_still_shows_the_toggle(self):
        resp = self.client.get('/issues/?rank=1')
        self.assertEqual(list(resp.context['issues']), [])
        self.assertContains(resp, 'Rank 1 only')

    def test_control_states_the_rank_in_words(self):
        self.issue.rank = 2
        self.issue.save()
        resp = self.client.get('/issues/')
        self.assertContains(resp, f'action="/issues/{self.issue.pk}/rank/"')
        self.assertContains(resp, 'aria-label="Rank for Slow invoices: Rank 2"')
        self.assertContains(resp, 'Rank 2, current rank. Press to clear.')
        self.assertContains(resp, 'Set rank 1 (top)')
        self.assertContains(resp, 'aria-pressed="true"', count=1)
        self.assertContains(resp, 'aria-pressed="false"', count=2)
        # The current rank's button sends an empty value, which clears it.
        self.assertContains(resp, 'name="rank" value=""', count=1)
        self.assertContains(resp, 'name="rank" value="1"', count=1)
        self.assertContains(resp, 'name="rank" value="3"', count=1)

    def test_control_is_on_the_detail_page_too(self):
        resp = self.client.get(f'/issues/{self.issue.pk}/')
        self.assertContains(resp, f'action="/issues/{self.issue.pk}/rank/"')
        self.assertContains(resp, 'aria-label="Rank for Slow invoices: Not ranked"')

    def test_closed_issue_shows_its_rank_without_the_control(self):
        self.issue.rank = 1
        self.issue.status = Issue.STATUS_RESOLVED
        self.issue.save()
        resp = self.client.get('/issues/?status=resolved')
        self.assertNotContains(resp, f'/issues/{self.issue.pk}/rank/')
        self.assertContains(resp, 'Rank 1 (top)')


class IssueOwnerRankPermissionTest(OwnerRankTestBase):
    """Ranking and assigning follow the rule for changing the status:
    the originating team and organisation admins."""

    def attempt(self, user):
        self.client.force_login(user)
        return (
            self.client.post(f'/issues/{self.issue.pk}/status/', {'status': Issue.STATUS_IN_IDS}),
            self.client.post(f'/issues/{self.issue.pk}/rank/', {'rank': 1}),
            self.client.post(f'/issues/{self.issue.pk}/owner/', {'owner': self.teammate.pk}),
        )

    def test_member_of_another_team_is_refused_like_a_status_change(self):
        responses = self.attempt(self.outsider)
        self.assertEqual([r.status_code for r in responses], [403, 403, 403])
        self.issue.refresh_from_db()
        self.assertIsNone(self.issue.rank)
        self.assertIsNone(self.issue.owner)
        self.assertFalse(self.issue.activity.exists())

    def test_team_the_issue_is_delegated_to_is_refused_like_a_status_change(self):
        self.issue.delegated_to_team = self.other_team
        self.issue.save()
        responses = self.attempt(self.outsider)
        self.assertEqual([r.status_code for r in responses], [403, 403, 403])

    def test_admin_who_is_not_on_the_team_may_rank_and_assign(self):
        responses = self.attempt(self.admin)
        self.assertEqual([r.status_code for r in responses], [302, 302, 302])
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.rank, 1)
        self.assertEqual(self.issue.owner, self.teammate)

    def test_anonymous_is_sent_to_sign_in(self):
        self.client.logout()
        for name in ('rank', 'owner'):
            resp = self.client.post(f'/issues/{self.issue.pk}/{name}/', {'rank': 1})
            self.assertEqual(resp.status_code, 302)
            self.assertIn('/login', resp['Location'])
        self.issue.refresh_from_db()
        self.assertIsNone(self.issue.rank)

    def test_delegated_view_shows_the_rank_but_no_control_to_the_other_team(self):
        self.issue.delegated_to_team = self.other_team
        self.issue.rank = 1
        self.issue.save()
        self.client.force_login(self.outsider)
        resp = self.client.get('/issues/?view=delegated')
        self.assertContains(resp, 'Slow invoices')
        self.assertContains(resp, 'Rank 1 (top)')
        self.assertNotContains(resp, f'/issues/{self.issue.pk}/rank/')

    def test_detail_page_hides_both_controls_from_someone_who_may_not_change_it(self):
        self.client.force_login(self.outsider)
        resp = self.client.get(f'/issues/{self.issue.pk}/')
        self.assertNotContains(resp, f'/issues/{self.issue.pk}/rank/')
        self.assertNotContains(resp, f'/issues/{self.issue.pk}/owner/')


class IssueCsvOwnerRankTest(OwnerRankTestBase):
    def test_csv_has_owner_and_rank_columns(self):
        self.issue.owner = self.teammate
        self.issue.rank = 2
        self.issue.save()
        self.make_issue('Bare')
        rows = list(csv.reader(io.StringIO(self.client.get('/issues/export/').content.decode())))
        self.assertEqual(rows[0][-2:], ['Owner', 'Rank'])
        self.assertEqual(rows[0][:7], [
            'Title', 'Type', 'Status', 'Originating Team', 'Delegated To', 'Created By',
            'Created At',
        ])
        by_title = {row[0]: row for row in rows[1:]}
        self.assertEqual(by_title['Slow invoices'][-2:], ['Tom Mate', '2'])
        self.assertEqual(by_title['Bare'][-2:], ['', ''])


class MeetingIssueSegmentTest(OwnerRankTestBase):
    def setUp(self):
        super().setUp()
        self.meeting = Meeting.objects.create(
            team=self.team, scheduled_date=date(2026, 1, 5), created_by=self.member,
        )
        self.meeting.start()
        self.meeting.current_segment = next(
            i for i, entry in enumerate(self.meeting.agenda) if entry['segment_type'] == 'ids'
        )
        self.meeting.save(update_fields=['current_segment'])
        self.url = f'/meetings/{self.meeting.pk}/'

    def test_segment_sorts_by_rank_then_age_with_unranked_last(self):
        self.issue.delete()
        self.make_issue('Unranked long-term', days_old=3, issue_type=Issue.TYPE_LONG_TERM)
        self.make_issue('Unranked old', days_old=9)
        self.make_issue('Two', rank=2, days_old=30)
        self.make_issue('One new', rank=1, days_old=1)
        self.make_issue('One old', rank=1, days_old=4)
        resp = self.client.get(self.url)
        self.assertEqual(
            [issue.title for issue in resp.context['issues']],
            ['One old', 'One new', 'Two', 'Unranked old', 'Unranked long-term'],
        )

    def test_rank_set_from_the_segment_returns_to_the_meeting(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, f'action="/issues/{self.issue.pk}/rank/"')
        self.assertContains(resp, f'name="next" value="{self.url}"')
        resp = self.client.post(f'/issues/{self.issue.pk}/rank/', {'rank': 1, 'next': self.url})
        self.assertRedirects(
            resp, f'{self.url}#issue-{self.issue.pk}', fetch_redirect_response=False,
        )
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.rank, 1)
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Rank 1 (top), current rank. Press to clear.')

    def test_segment_shows_the_owner(self):
        self.issue.owner = self.teammate
        self.issue.save()
        self.assertContains(self.client.get(self.url), 'Owner: Tom Mate')

    def test_issue_delegated_in_from_another_team_has_no_control(self):
        theirs = Issue.objects.create(
            title='Handed over', originating_team=self.other_team, delegated_to_team=self.team,
            created_by=self.outsider, rank=3,
        )
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Handed over')
        self.assertNotContains(resp, f'/issues/{theirs.pk}/rank/')
        self.assertContains(resp, f'/issues/{self.issue.pk}/rank/')
