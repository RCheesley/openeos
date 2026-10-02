from datetime import date

from django.core import mail
from django.test import TestCase
from django.contrib.auth.models import User

from apps.accounts.models import Membership, Organization, Team
from apps.rocks.models import Rock


class RockStatusOffTrackAlertTest(TestCase):
    def setUp(self):
        org = Organization.objects.create(name='Alert Org')
        self.team = Team.objects.create(organization=org, name='Alert Team')
        self.owner = User.objects.create_user(
            username='alertowner', email='owner@example.com', password='pw'
        )
        self.other = User.objects.create_user(
            username='alertother', email='other@example.com', password='pw'
        )
        for user in (self.owner, self.other):
            Membership.objects.create(user=user, organization=org)
        self.rock = Rock.objects.create(
            title='Ship it', owner=self.owner, team=self.team,
            quarter=1, year=2026, due_date=date(2026, 3, 31),
            status=Rock.STATUS_ON_TRACK,
        )

    def test_marking_off_track_sends_alert(self):
        self.client.force_login(self.owner)
        self.client.post(f'/rocks/{self.rock.pk}/status/', {'status': 'off_track'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Ship it', mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, [self.owner.email])

    def test_repeated_off_track_does_not_resend(self):
        self.rock.status = Rock.STATUS_OFF_TRACK
        self.rock.save()
        self.client.force_login(self.owner)
        self.client.post(f'/rocks/{self.rock.pk}/status/', {'status': 'off_track'})
        self.assertEqual(len(mail.outbox), 0)

    def test_marking_on_track_does_not_send_alert(self):
        self.rock.status = Rock.STATUS_OFF_TRACK
        self.rock.save()
        self.client.force_login(self.owner)
        self.client.post(f'/rocks/{self.rock.pk}/status/', {'status': 'on_track'})
        self.assertEqual(len(mail.outbox), 0)

    def test_non_owner_forbidden_and_no_alert(self):
        self.client.force_login(self.other)
        resp = self.client.post(f'/rocks/{self.rock.pk}/status/', {'status': 'off_track'})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)


class RockCompanyRockFormPermissionTest(TestCase):
    """Only org admins can see or set is_company_rock (#3, #4)."""

    def setUp(self):
        self.org = Organization.objects.create(name='Flag Org')
        self.team = Team.objects.create(organization=self.org, name='Flag Team')

        self.admin = User.objects.create_user(username='flagadmin', password='pw')
        Membership.objects.create(
            user=self.admin, organization=self.org, role=Membership.ROLE_ADMIN
        )
        self.admin.profile.teams.add(self.team)

        self.member = User.objects.create_user(username='flagmember', password='pw')
        Membership.objects.create(
            user=self.member, organization=self.org, role=Membership.ROLE_MEMBER
        )
        self.member.profile.teams.add(self.team)

        self.rock = Rock.objects.create(
            title='Existing Rock', owner=self.member, team=self.team,
            quarter=1, year=2026, due_date=date(2026, 3, 31),
        )

    def _rock_post_data(self, **overrides):
        data = {
            'title': 'A Rock',
            'description': '',
            'owner': self.member.pk,
            'quarter': 1,
            'year': 2026,
            'due_date': '2026-03-31',
            'parent_rock': '',
        }
        data.update(overrides)
        return data

    def test_admin_sees_company_rock_checkbox_on_create(self):
        self.client.force_login(self.admin)
        resp = self.client.get('/rocks/new/')
        self.assertContains(resp, 'is_company_rock')

    def test_member_does_not_see_company_rock_checkbox_on_create(self):
        self.client.force_login(self.member)
        resp = self.client.get('/rocks/new/')
        self.assertNotContains(resp, 'is_company_rock')

    def test_admin_can_create_company_rock(self):
        self.client.force_login(self.admin)
        self.client.post('/rocks/new/', self._rock_post_data(is_company_rock='on'))
        rock = Rock.objects.get(title='A Rock')
        self.assertTrue(rock.is_company_rock)

    def test_member_cannot_set_company_rock_via_post(self):
        """The field is absent from a non-admin's form, so posting it anyway is ignored."""
        self.client.force_login(self.member)
        self.client.post('/rocks/new/', self._rock_post_data(is_company_rock='on'))
        rock = Rock.objects.get(title='A Rock')
        self.assertFalse(rock.is_company_rock)

    def test_admin_can_promote_existing_rock(self):
        self.client.force_login(self.admin)
        self.client.post(
            f'/rocks/{self.rock.pk}/edit/',
            self._rock_post_data(title=self.rock.title, is_company_rock='on'),
        )
        self.rock.refresh_from_db()
        self.assertTrue(self.rock.is_company_rock)

    def test_member_cannot_promote_existing_rock_via_post(self):
        self.client.force_login(self.member)
        self.client.post(
            f'/rocks/{self.rock.pk}/edit/',
            self._rock_post_data(title=self.rock.title, is_company_rock='on'),
        )
        self.rock.refresh_from_db()
        self.assertFalse(self.rock.is_company_rock)
