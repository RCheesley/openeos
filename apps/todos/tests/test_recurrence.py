"""Repeating To-Dos: the next occurrence is created when the current one is completed."""
import io
import tempfile
from datetime import date, timedelta
from pathlib import Path

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase

from apps.accounts.models import Membership, Organization, Team
from apps.accounts.portability import build_archive
from apps.issues.models import Issue
from apps.meetings.models import Meeting
from apps.rocks.models import Rock
from apps.todos.models import ToDo


class RecurrenceTestBase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Repeat Org')
        self.team = Team.objects.create(organization=self.org, name='Repeat Team')
        self.user = User.objects.create_user(
            username='repeatuser', email='repeat@example.com', password='pw',
        )
        Membership.objects.create(user=self.user, organization=self.org)
        self.user.profile.teams.add(self.team)

    def make(self, due, recurrence=ToDo.RECURRENCE_WEEKLY, **extra):
        extra.setdefault('owner', self.user)
        return ToDo.objects.create(
            title='Send the weekly numbers', team=self.team,
            due_date=due, recurrence=recurrence, **extra,
        )

    def next_due(self, due, recurrence):
        return self.make(due, recurrence).mark_complete().due_date


class NextDueDateTest(RecurrenceTestBase):
    def test_weekly_is_seven_days_after_the_due_date(self):
        self.assertEqual(self.next_due(date(2026, 6, 5), 'weekly'), date(2026, 6, 12))

    def test_every_two_weeks_is_fourteen_days_after_the_due_date(self):
        self.assertEqual(self.next_due(date(2026, 6, 5), 'biweekly'), date(2026, 6, 19))

    def test_monthly_keeps_the_day_of_the_month(self):
        self.assertEqual(self.next_due(date(2026, 6, 15), 'monthly'), date(2026, 7, 15))

    def test_quarterly_is_three_months_on(self):
        self.assertEqual(self.next_due(date(2026, 6, 15), 'quarterly'), date(2026, 9, 15))

    def test_weekly_crosses_the_year_boundary(self):
        self.assertEqual(self.next_due(date(2026, 12, 28), 'weekly'), date(2027, 1, 4))

    def test_every_two_weeks_crosses_the_year_boundary(self):
        self.assertEqual(self.next_due(date(2026, 12, 25), 'biweekly'), date(2027, 1, 8))

    def test_monthly_crosses_the_year_boundary(self):
        self.assertEqual(self.next_due(date(2026, 12, 15), 'monthly'), date(2027, 1, 15))

    def test_quarterly_crosses_the_year_boundary(self):
        self.assertEqual(self.next_due(date(2026, 11, 15), 'quarterly'), date(2027, 2, 15))

    def test_monthly_from_31_january_lands_on_the_last_day_of_february(self):
        self.assertEqual(self.next_due(date(2026, 1, 31), 'monthly'), date(2026, 2, 28))

    def test_monthly_from_31_january_in_a_leap_year(self):
        self.assertEqual(self.next_due(date(2028, 1, 31), 'monthly'), date(2028, 2, 29))

    def test_quarterly_from_30_november_lands_on_the_last_day_of_february(self):
        self.assertEqual(self.next_due(date(2026, 11, 30), 'quarterly'), date(2027, 2, 28))

    def test_monthly_series_returns_to_the_31st_after_a_short_month(self):
        january = self.make(date(2026, 1, 31), 'monthly')
        february = january.mark_complete()
        march = february.mark_complete()
        april = march.mark_complete()
        self.assertEqual(
            [february.due_date, march.due_date, april.due_date],
            [date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)],
        )

    def test_quarterly_series_returns_to_the_30th_after_february(self):
        november = self.make(date(2026, 11, 30), 'quarterly')
        february = november.mark_complete()
        self.assertEqual(february.mark_complete().due_date, date(2027, 5, 30))

    def test_moving_the_due_date_resets_the_day_the_series_aims_for(self):
        february = self.make(date(2026, 1, 31), 'monthly').mark_complete()
        february.due_date = date(2026, 2, 10)
        february.save()
        self.assertEqual(february.mark_complete().due_date, date(2026, 3, 10))

    def test_due_date_is_counted_from_the_due_date_not_the_completion_date(self):
        # Three weeks late: the next one is still one week after the old due date.
        late = self.make(date.today() - timedelta(days=21), 'weekly')
        self.assertEqual(late.mark_complete().due_date, date.today() - timedelta(days=14))


class CompletionTest(RecurrenceTestBase):
    def test_a_to_do_that_does_not_repeat_creates_nothing(self):
        todo = self.make(date(2026, 6, 5), ToDo.RECURRENCE_NONE)
        self.assertIsNone(todo.mark_complete())
        self.assertEqual(ToDo.objects.count(), 1)

    def test_next_occurrence_copies_the_details_and_repeats_in_turn(self):
        rock = Rock.objects.create(
            title='Repeat Rock', owner=self.user, team=self.team,
            quarter=2, year=2026, due_date=date(2026, 6, 30),
        )
        issue = Issue.objects.create(
            title='Repeat Issue', originating_team=self.team, created_by=self.user,
        )
        other = User.objects.create_user(username='repeatowner', password='pw')
        todo = self.make(
            date(2026, 6, 5), description='From the finance sheet', owner=other,
            linked_rock=rock, linked_issue=issue,
        )
        nxt = todo.mark_complete()

        self.assertEqual(ToDo.objects.count(), 2)
        self.assertEqual(
            (nxt.title, nxt.description, nxt.owner, nxt.team, nxt.linked_rock, nxt.linked_issue),
            ('Send the weekly numbers', 'From the finance sheet', other, self.team, rock, issue),
        )
        self.assertEqual(nxt.recurrence, ToDo.RECURRENCE_WEEKLY)
        self.assertEqual(nxt.status, ToDo.STATUS_OPEN)
        self.assertIsNone(nxt.completed_at)
        self.assertEqual(nxt.previous_occurrence, todo)
        todo.refresh_from_db()
        self.assertTrue(todo.is_complete)
        # ...and the new one repeats when it is completed in turn.
        third = nxt.mark_complete()
        self.assertEqual(third.due_date, date(2026, 6, 19))
        self.assertEqual(ToDo.objects.count(), 3)

    def test_completing_twice_creates_one_next_occurrence(self):
        todo = self.make(date(2026, 6, 5))
        stale = ToDo.objects.get(pk=todo.pk)
        todo.mark_complete()
        self.assertIsNone(stale.mark_complete())
        self.assertTrue(stale.is_complete)
        self.assertEqual(ToDo.objects.count(), 2)

    def test_reopening_removes_the_open_next_occurrence(self):
        todo = self.make(date(2026, 6, 5))
        todo.mark_complete()
        self.assertTrue(todo.mark_open())
        self.assertEqual(list(ToDo.objects.all()), [todo])
        self.assertFalse(todo.is_complete)
        # Completing it again creates exactly one next occurrence, on the same date.
        again = todo.mark_complete()
        self.assertEqual(again.due_date, date(2026, 6, 12))
        self.assertEqual(ToDo.objects.count(), 2)

    def test_reopening_keeps_a_next_occurrence_that_was_completed(self):
        first = self.make(date(2026, 6, 5))
        second = first.mark_complete()
        third = second.mark_complete()
        self.assertFalse(first.mark_open())
        self.assertEqual(ToDo.objects.count(), 3)
        # The series has moved on, so completing the first again adds nothing.
        self.assertIsNone(first.mark_complete())
        self.assertEqual(ToDo.objects.count(), 3)
        third.refresh_from_db()
        self.assertEqual(third.status, ToDo.STATUS_OPEN)

    def test_reopening_a_to_do_that_does_not_repeat_removes_nothing(self):
        todo = self.make(date(2026, 6, 5), ToDo.RECURRENCE_NONE)
        other = self.make(date(2026, 6, 12), ToDo.RECURRENCE_NONE)
        todo.mark_complete()
        self.assertFalse(todo.mark_open())
        self.assertTrue(ToDo.objects.filter(pk=other.pk).exists())

    def test_deleting_the_open_occurrence_ends_the_series(self):
        first = self.make(date(2026, 6, 5))
        second = first.mark_complete()
        second.delete()
        self.assertEqual(list(ToDo.objects.all()), [first])
        first.refresh_from_db()
        self.assertTrue(first.is_complete)

    def test_deleting_an_earlier_occurrence_leaves_the_later_one(self):
        first = self.make(date(2026, 6, 5))
        second = first.mark_complete()
        first.delete()
        second.refresh_from_db()
        self.assertIsNone(second.previous_occurrence)
        self.assertEqual(second.recurrence, ToDo.RECURRENCE_WEEKLY)


class RecurrenceViewTest(RecurrenceTestBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self.due = date.today() + timedelta(days=7)

    def post_data(self, **overrides):
        data = {
            'title': 'Send the weekly numbers', 'description': '', 'owner': self.user.pk,
            'team': self.team.pk, 'due_date': self.due.isoformat(),
            'linked_rock': '', 'linked_issue': '', 'recurrence': 'weekly',
        }
        data.update(overrides)
        return data

    # -- form -----------------------------------------------------------------

    def test_form_offers_the_five_choices_and_defaults_to_none(self):
        resp = self.client.get('/todos/new/')
        field = resp.context['form'].fields['recurrence']
        self.assertEqual(
            [label for _, label in field.choices],
            ['Does not repeat', 'Weekly', 'Every two weeks', 'Monthly', 'Quarterly'],
        )
        self.assertFalse(field.required)
        self.assertContains(resp, '<option value="" selected>Does not repeat</option>', html=True)
        self.assertContains(resp, 'for="id_recurrence"')

    def test_creating_without_the_field_does_not_repeat(self):
        data = self.post_data()
        del data['recurrence']
        self.client.post('/todos/new/', data)
        self.assertEqual(ToDo.objects.get().recurrence, ToDo.RECURRENCE_NONE)

    def test_creating_a_repeating_to_do(self):
        self.client.post('/todos/new/', self.post_data(recurrence='monthly'))
        self.assertEqual(ToDo.objects.get().recurrence, ToDo.RECURRENCE_MONTHLY)

    def test_an_unknown_interval_is_rejected(self):
        resp = self.client.post('/todos/new/', self.post_data(recurrence='daily'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('recurrence', resp.context['form'].errors)
        self.assertFalse(ToDo.objects.exists())

    def test_edit_form_marks_a_repeating_to_do_and_selects_its_interval(self):
        todo = self.make(self.due, 'biweekly')
        resp = self.client.get(f'/todos/{todo.pk}/edit/')
        self.assertContains(resp, 'Repeats every two weeks.')
        self.assertContains(
            resp, '<option value="biweekly" selected>Every two weeks</option>', html=True,
        )

    def test_redisplayed_form_keeps_the_chosen_interval(self):
        resp = self.client.post('/todos/new/', self.post_data(title='', recurrence='quarterly'))
        self.assertContains(
            resp, '<option value="quarterly" selected>Quarterly</option>', html=True,
        )

    def test_stopping_the_repeat_is_an_edit_to_the_current_occurrence(self):
        first = self.make(self.due)
        current = first.mark_complete()
        self.client.post(
            f'/todos/{current.pk}/edit/',
            self.post_data(recurrence='', due_date=current.due_date.isoformat()),
        )
        current.refresh_from_db()
        self.assertEqual(current.recurrence, ToDo.RECURRENCE_NONE)
        self.client.post(f'/todos/{current.pk}/complete/')
        current.refresh_from_db()
        self.assertTrue(current.is_complete)
        self.assertEqual(ToDo.objects.count(), 2)

    # -- complete toggle ------------------------------------------------------

    def test_completing_creates_the_next_occurrence_and_says_so(self):
        todo = self.make(date(2026, 6, 5), 'monthly')
        resp = self.client.post(f'/todos/{todo.pk}/complete/', follow=True)
        nxt = ToDo.objects.get(previous_occurrence=todo)
        self.assertEqual(nxt.due_date, date(2026, 7, 5))
        self.assertContains(resp, 'repeats monthly: the next one is due 5 July 2026.')

    def test_toggling_complete_twice_leaves_no_duplicate(self):
        todo = self.make(self.due)
        self.client.post(f'/todos/{todo.pk}/complete/')
        resp = self.client.post(f'/todos/{todo.pk}/complete/', follow=True)
        self.assertContains(resp, 'is open again, so its next occurrence was removed.')
        self.assertEqual(list(ToDo.objects.all()), [todo])
        self.client.post(f'/todos/{todo.pk}/complete/')
        self.assertEqual(ToDo.objects.count(), 2)

    def test_completing_an_ordinary_to_do_shows_no_repeat_message(self):
        todo = self.make(self.due, ToDo.RECURRENCE_NONE)
        resp = self.client.post(f'/todos/{todo.pk}/complete/', follow=True)
        self.assertNotContains(resp, 'the next one is due')
        self.assertEqual(ToDo.objects.count(), 1)

    # -- markers --------------------------------------------------------------

    def test_list_marks_repeating_to_dos_in_words(self):
        self.make(self.due, 'weekly')
        resp = self.client.get('/todos/')
        self.assertContains(resp, 'Repeats weekly')
        resp = self.client.get('/todos/', {'view': 'team'})
        self.assertContains(resp, 'Repeats weekly')

    def test_list_does_not_mark_an_ordinary_to_do(self):
        self.make(self.due, ToDo.RECURRENCE_NONE)
        self.assertNotContains(self.client.get('/todos/'), 'Repeats')

    def test_completed_list_keeps_the_marker(self):
        self.make(self.due, 'quarterly').mark_complete()
        resp = self.client.get('/todos/', {'status': 'complete'})
        self.assertContains(resp, 'Repeats quarterly')

    def test_meeting_review_segment_marks_repeating_to_dos_in_words(self):
        self.make(self.due, 'biweekly')
        ToDo.objects.create(title='One-off', owner=self.user, team=self.team)
        meeting = Meeting.objects.create(
            team=self.team, scheduled_date=date.today(), created_by=self.user,
        )
        meeting.start()
        meeting.current_segment = 4
        meeting.save(update_fields=['current_segment'])
        resp = self.client.get(f'/meetings/{meeting.pk}/')
        self.assertContains(resp, 'Review open Actions for team members')
        self.assertContains(resp, 'Repeats every two weeks', count=1)

    # -- delete ---------------------------------------------------------------

    def test_delete_page_says_the_series_ends(self):
        todo = self.make(self.due)
        resp = self.client.get(f'/todos/{todo.pk}/delete/')
        self.assertContains(resp, 'Repeats weekly.')
        self.assertContains(resp, 'Only this occurrence will be deleted, and the series ends with it')

    def test_delete_page_for_a_completed_occurrence_says_the_next_one_stays(self):
        first = self.make(date(2026, 6, 5))
        first.mark_complete()
        resp = self.client.get(f'/todos/{first.pk}/delete/')
        self.assertContains(resp, 'The next one, due')
        self.assertContains(resp, '12 June 2026')
        self.assertNotContains(resp, 'the series ends with it')

    def test_delete_page_for_an_ordinary_to_do_says_nothing_about_repeating(self):
        todo = self.make(self.due, ToDo.RECURRENCE_NONE)
        resp = self.client.get(f'/todos/{todo.pk}/delete/')
        self.assertNotContains(resp, 'occurrence')

    def test_deleting_removes_only_that_occurrence(self):
        first = self.make(self.due)
        second = first.mark_complete()
        self.client.post(f'/todos/{second.pk}/delete/')
        self.assertEqual(list(ToDo.objects.all()), [first])


class OrdinaryTreatmentTest(RecurrenceTestBase):
    """Each occurrence ages, goes overdue and is chased like any other To-Do."""

    def test_next_occurrence_starts_its_own_age(self):
        todo = self.make(date.today() - timedelta(days=1))
        ToDo.objects.filter(pk=todo.pk).update(
            created_at=todo.created_at - timedelta(days=20)
        )
        todo.refresh_from_db()
        self.assertEqual(todo.escalation_level, 2)
        nxt = todo.mark_complete()
        self.assertEqual(nxt.days_open, 0)
        self.assertEqual(nxt.escalation_level, 0)

    def test_overdue_occurrence_is_in_the_digest(self):
        late = self.make(date.today() - timedelta(days=30))
        nxt = late.mark_complete()
        self.assertTrue(nxt.is_overdue)
        call_command('send_daily_notifications')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Send the weekly numbers', mail.outbox[0].body)


class PortabilityTest(RecurrenceTestBase):
    def test_export_and_import_keep_the_interval_and_the_chain(self):
        first = self.make(date(2026, 1, 31), 'monthly')
        second = first.mark_complete()
        self.make(date(2026, 3, 1), ToDo.RECURRENCE_NONE)

        with tempfile.TemporaryDirectory() as out:
            archive = Path(out, 'repeat.zip')
            with archive.open('wb') as handle:
                build_archive(self.org, fileobj=handle)
            call_command(
                'import_organization', str(archive), '--slug', 'repeat-copy',
                stdout=io.StringIO(),
            )

        copy = Organization.objects.get(slug='repeat-copy')
        todos = ToDo.objects.filter(team__organization=copy).order_by('due_date')
        self.assertEqual(
            [(t.due_date, t.recurrence, t.recurrence_day, t.status) for t in todos],
            [
                (date(2026, 1, 31), 'monthly', None, ToDo.STATUS_COMPLETE),
                (date(2026, 2, 28), 'monthly', 31, ToDo.STATUS_OPEN),
                (date(2026, 3, 1), '', None, ToDo.STATUS_OPEN),
            ],
        )
        copied_first, copied_second, _ = todos
        self.assertEqual(copied_second.previous_occurrence, copied_first)
        self.assertNotEqual(copied_first.pk, first.pk)
        # The source chain still points at the source rows.
        second.refresh_from_db()
        self.assertEqual(second.previous_occurrence, first)
        # The imported series carries on from where it was, back on the 31st.
        self.assertEqual(copied_second.mark_complete().due_date, date(2026, 3, 31))
