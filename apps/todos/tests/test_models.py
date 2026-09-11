from datetime import date, timedelta
from django.test import TestCase
from django.contrib.auth.models import User
from apps.accounts.models import Organization, Team
from apps.todos.models import ToDo


def make_todo(title='Test ToDo', days_ago=0, **kwargs):
    org = Organization.objects.get_or_create(name='Todo Org')[0]
    team = Team.objects.get_or_create(organization=org, name='Todo Team')[0]
    user = User.objects.get_or_create(username='todouser')[0]
    due = date.today() + timedelta(days=7 - days_ago)
    todo = ToDo.objects.create(
        title=title, owner=user, team=team,
        due_date=due, **kwargs
    )
    if days_ago:
        # Simulate older todo by backdating created_at
        ToDo.objects.filter(pk=todo.pk).update(
            created_at=todo.created_at - timedelta(days=days_ago)
        )
        todo.refresh_from_db()
    return todo


class ToDoStatusTest(TestCase):
    def test_open_by_default(self):
        todo = make_todo()
        self.assertEqual(todo.status, ToDo.STATUS_OPEN)
        self.assertFalse(todo.is_complete)

    def test_mark_complete(self):
        todo = make_todo()
        todo.mark_complete()
        self.assertTrue(todo.is_complete)
        self.assertEqual(todo.status, ToDo.STATUS_COMPLETE)

    def test_mark_open(self):
        todo = make_todo()
        todo.mark_complete()
        todo.mark_open()
        self.assertFalse(todo.is_complete)
        self.assertEqual(todo.status, ToDo.STATUS_OPEN)

    def test_str(self):
        todo = make_todo(title='My Task')
        self.assertEqual(str(todo), 'My Task')


class ToDoEscalationTest(TestCase):
    def test_escalation_level_0_fresh(self):
        todo = make_todo(days_ago=0)
        self.assertEqual(todo.escalation_level, 0)

    def test_escalation_level_1_at_8_days(self):
        todo = make_todo(days_ago=8)
        self.assertEqual(todo.escalation_level, 1)

    def test_escalation_level_2_at_14_days(self):
        todo = make_todo(days_ago=14)
        self.assertEqual(todo.escalation_level, 2)

    def test_complete_always_level_0(self):
        todo = make_todo(days_ago=20)
        todo.mark_complete()
        self.assertEqual(todo.escalation_level, 0)

    def test_days_open_increases(self):
        todo = make_todo(days_ago=5)
        self.assertGreaterEqual(todo.days_open, 5)
