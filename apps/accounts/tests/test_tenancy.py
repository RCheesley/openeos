from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.accounts.models import Membership, OrganizationDomain
from apps.accounts.scoping import SESSION_ORG_KEY

from .test_isolation import build_org, pk_urls

HOSTS = ['testserver', 'mercury.example.test', 'silavapi.example.test']
MERCURY = 'mercury.example.test'
SILAVAPI = 'silavapi.example.test'

TEAL = '#1f6f8b'
PLUM = '#7b2d8e'


@override_settings(ALLOWED_HOSTS=HOSTS)
class TwoHostsIsolationTest(TestCase):
    """Two organisations on their own hostnames: each shows only its own brand,
    words and records, whichever organisation the session has pinned."""

    def setUp(self):
        self.mercury = build_org('Mercury')
        self.silavapi = build_org('Silavapi')
        self.brand(self.mercury, MERCURY, 'Mercury Consortium', TEAL, 'Priority', 'Priorities')
        self.brand(self.silavapi, SILAVAPI, 'Silavapi Collective', PLUM, 'Boulder', 'Boulders')
        # An admin of both, so the admin-only URLs are refused by scoping, not by role.
        self.user = User.objects.create_user(username='bothuser', password='pw')
        for fixture in (self.mercury, self.silavapi):
            Membership.objects.create(
                user=self.user, organization=fixture['org'], role=Membership.ROLE_ADMIN
            )
            self.user.profile.teams.add(fixture['team'])
        self.client.force_login(self.user)

    @staticmethod
    def brand(fixture, hostname, display_name, color, rock, rocks):
        org = fixture['org']
        org.display_name = display_name
        org.primary_color = color
        org.terminology = {'rock': rock, 'rocks': rocks}
        org.save()
        OrganizationDomain.objects.create(organization=org, hostname=hostname)

    def pin_session_to(self, fixture):
        session = self.client.session
        session[SESSION_ORG_KEY] = fixture['org'].pk
        session.save()

    def assert_host_shows_only_its_org(self, host, mine, theirs):
        resp = self.client.get('/', HTTP_HOST=host)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, mine['org'].display_name)
        self.assertContains(resp, f'--bs-primary: {mine["org"].primary_color};')
        self.assertContains(resp, mine['org'].terminology['rocks'])
        self.assertNotContains(resp, theirs['org'].display_name)
        self.assertNotContains(resp, theirs['org'].primary_color)
        self.assertNotContains(resp, theirs['org'].terminology['rocks'])
        self.assertNotContains(resp, theirs['org'].terminology['rock'])
        self.assertNotContains(resp, theirs['team'].name)

    def assert_other_org_records_are_not_found(self, host, theirs):
        gets, _ = pk_urls(theirs)
        for url in gets:
            with self.subTest(host=host, url=url):
                self.assertEqual(self.client.get(url, HTTP_HOST=host).status_code, 404)

    def test_each_host_is_isolated_whatever_the_session_pins(self):
        for host, mine, theirs in [
            (MERCURY, self.mercury, self.silavapi),
            (SILAVAPI, self.silavapi, self.mercury),
        ]:
            for pinned in (mine, theirs):
                with self.subTest(host=host, pinned=pinned['org'].name):
                    self.pin_session_to(pinned)
                    self.assert_host_shows_only_its_org(host, mine, theirs)
                    self.assert_other_org_records_are_not_found(host, theirs)

    def test_own_records_are_reachable_on_the_own_host(self):
        for host, mine in [(MERCURY, self.mercury), (SILAVAPI, self.silavapi)]:
            gets, _ = pk_urls(mine)
            for url in gets:
                with self.subTest(host=host, url=url):
                    self.assertIn(self.client.get(url, HTTP_HOST=host).status_code, (200, 302))
