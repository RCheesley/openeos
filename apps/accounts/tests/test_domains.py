from unittest import mock

from django.contrib.auth.models import AnonymousUser, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase, override_settings

from apps.accounts.middleware import OrganizationDomainMiddleware
from apps.accounts.models import Membership, Organization, OrganizationDomain
from apps.accounts.scoping import SESSION_ORG_KEY

from .test_isolation import build_org, pk_urls
from .test_memberships import TwoOrgMixin

HOSTS = ['testserver', 'mercury.example.test', 'silavapi.example.test']
MERCURY = 'mercury.example.test'
SILAVAPI = 'silavapi.example.test'


class OrganizationDomainModelTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Domain Org')

    def test_hostname_is_normalised_on_save(self):
        domain = OrganizationDomain.objects.create(organization=self.org, hostname='  Acme.Example.COM. ')
        self.assertEqual(domain.hostname, 'acme.example.com')
        self.assertEqual(str(domain), 'acme.example.com')

    def test_clean_rejects_scheme_port_path_and_whitespace(self):
        for bad in ['https://acme.example.com', 'acme.example.com:8000', 'acme.example.com/x', 'ac me.com', '']:
            with self.subTest(hostname=bad):
                with self.assertRaises(ValidationError):
                    OrganizationDomain(organization=self.org, hostname=bad).clean()

    def test_hostname_is_unique_across_organisations(self):
        OrganizationDomain.objects.create(organization=self.org, hostname='shared.example.com')
        other = Organization.objects.create(name='Other Org')
        with self.assertRaises(IntegrityError):
            OrganizationDomain.objects.create(organization=other, hostname='SHARED.example.com')

    def test_only_one_primary_domain_per_organisation(self):
        OrganizationDomain.objects.create(organization=self.org, hostname='a.example.com', is_primary=True)
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                OrganizationDomain.objects.create(
                    organization=self.org, hostname='b.example.com', is_primary=True
                )
        OrganizationDomain.objects.create(organization=self.org, hostname='c.example.com')
        self.assertEqual(self.org.domains.count(), 2)

    def test_primary_domain_prefers_the_primary_flag(self):
        OrganizationDomain.objects.create(organization=self.org, hostname='alias.example.com')
        primary = OrganizationDomain.objects.create(
            organization=self.org, hostname='main.example.com', is_primary=True
        )
        self.assertEqual(self.org.primary_domain, primary)

    def test_primary_domain_falls_back_to_first_by_hostname(self):
        OrganizationDomain.objects.create(organization=self.org, hostname='b.example.com')
        first = OrganizationDomain.objects.create(organization=self.org, hostname='a.example.com')
        self.assertEqual(self.org.primary_domain, first)

    @override_settings(SITE_URL='http://localhost:8000')
    def test_site_url_uses_scheme_from_site_url_setting(self):
        self.assertEqual(self.org.site_url, '')
        OrganizationDomain.objects.create(organization=self.org, hostname='acme.example.com')
        self.assertEqual(self.org.site_url, 'http://acme.example.com')

    @override_settings(SITE_URL='acme.example.com')
    def test_site_url_defaults_to_https_when_site_url_has_no_scheme(self):
        OrganizationDomain.objects.create(organization=self.org, hostname='acme.example.com')
        self.assertEqual(self.org.site_url, 'https://acme.example.com')


class OrganizationDomainMiddlewareTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Middleware Org')
        OrganizationDomain.objects.create(organization=self.org, hostname=MERCURY)
        self.factory = RequestFactory()
        self.middleware = OrganizationDomainMiddleware(lambda request: 'response')

    def _request(self, path='/', host=MERCURY, user=None):
        request = self.factory.get(path, HTTP_HOST=host)
        request.user = user or AnonymousUser()
        return request

    @override_settings(ALLOWED_HOSTS=HOSTS)
    def test_resolves_hostname_ignoring_case_and_port(self):
        request = self._request(host='Mercury.Example.TEST:8000')
        self.middleware(request)
        self.assertEqual(request.host_org, self.org)
        self.assertEqual(request.org_domain.hostname, MERCURY)

    @override_settings(ALLOWED_HOSTS=HOSTS)
    def test_unmapped_host_leaves_both_attributes_none(self):
        request = self._request(host='testserver')
        self.middleware(request)
        self.assertIsNone(request.host_org)
        self.assertIsNone(request.org_domain)

    @override_settings(ALLOWED_HOSTS=['testserver'])
    def test_disallowed_host_resolves_to_none_instead_of_raising(self):
        request = self._request(host='evil.example.test')
        self.assertEqual(self.middleware(request), 'response')
        self.assertIsNone(request.host_org)

    @override_settings(ALLOWED_HOSTS=HOSTS)
    def test_non_member_is_denied(self):
        outsider = User.objects.create_user(username='outsider', password='pw')
        with self.assertRaises(PermissionDenied):
            self.middleware(self._request(user=outsider))

    @override_settings(ALLOWED_HOSTS=HOSTS)
    def test_open_paths_anonymous_members_and_superusers_pass(self):
        outsider = User.objects.create_user(username='outsider', password='pw')
        member = User.objects.create_user(username='member', password='pw')
        Membership.objects.create(user=member, organization=self.org)
        root = User.objects.create_superuser(username='root', password='pw')
        for path, user in [
            ('/accounts/login/', outsider), ('/admin/', outsider), ('/healthz/', outsider),
            ('/', AnonymousUser()), ('/', member), ('/', root),
        ]:
            with self.subTest(path=path, user=user):
                self.assertEqual(self.middleware(self._request(path=path, user=user)), 'response')


@override_settings(ALLOWED_HOSTS=HOSTS)
class PinnedHostTest(TestCase):
    """Requests on an organisation's hostname are scoped to it whatever the session says."""

    def setUp(self):
        self.mercury = build_org('Mercury')
        self.silavapi = build_org('Silavapi')
        OrganizationDomain.objects.create(organization=self.mercury['org'], hostname=MERCURY)
        OrganizationDomain.objects.create(organization=self.silavapi['org'], hostname=SILAVAPI)

    def _pin_session_to(self, org):
        session = self.client.session
        session[SESSION_ORG_KEY] = org.pk
        session.save()

    def test_member_gets_host_org_regardless_of_session(self):
        self.client.force_login(self.mercury['user'])
        self._pin_session_to(self.silavapi['org'])
        resp = self.client.get('/', HTTP_HOST=MERCURY)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['active_org'], self.mercury['org'])
        self.assertEqual(resp.context['user_orgs'], [self.mercury['org']])

    def test_user_in_both_orgs_follows_the_host_not_the_session(self):
        both = self.mercury['user']
        Membership.objects.create(user=both, organization=self.silavapi['org'])
        both.profile.teams.add(self.silavapi['team'])
        self.client.force_login(both)
        self._pin_session_to(self.silavapi['org'])

        q1 = {'quarter': 1, 'year': 2026}
        resp = self.client.get('/rocks/', q1, HTTP_HOST=MERCURY)
        self.assertEqual(resp.context['active_org'], self.mercury['org'])
        self.assertContains(resp, 'Mercury Rock')
        self.assertNotContains(resp, 'Silavapi Rock')
        self.assertNotContains(resp, 'Switch Organisation')

        resp = self.client.get('/rocks/', q1, HTTP_HOST=SILAVAPI)
        self.assertEqual(resp.context['active_org'], self.silavapi['org'])
        self.assertContains(resp, 'Silavapi Rock')

    def test_switching_to_another_org_on_a_pinned_host_is_not_found(self):
        both = self.mercury['user']
        Membership.objects.create(user=both, organization=self.silavapi['org'])
        self.client.force_login(both)
        url = f'/org/{self.silavapi["org"].pk}/switch/'
        self.assertEqual(self.client.post(url, HTTP_HOST=MERCURY).status_code, 404)
        url = f'/org/{self.mercury["org"].pk}/switch/'
        self.assertEqual(self.client.post(url, HTTP_HOST=MERCURY).status_code, 302)

    def test_other_orgs_records_are_not_found_on_this_host_even_for_a_member_of_both(self):
        both = self.mercury['user']
        Membership.objects.create(user=both, organization=self.silavapi['org'])
        both.profile.teams.add(self.silavapi['team'])
        self.client.force_login(both)
        gets, posts = pk_urls(self.silavapi)
        for url in gets:
            with self.subTest(method='GET', url=url):
                self.assertEqual(self.client.get(url, HTTP_HOST=MERCURY).status_code, 404)
        for url, data in posts:
            with self.subTest(method='POST', url=url):
                self.assertEqual(self.client.post(url, data, HTTP_HOST=MERCURY).status_code, 404)

    def test_non_member_is_forbidden_on_app_pages(self):
        self.client.force_login(self.silavapi['user'])
        for path in ['/', '/rocks/']:
            with self.subTest(path=path):
                resp = self.client.get(path, HTTP_HOST=MERCURY)
                self.assertEqual(resp.status_code, 403)
                self.assertContains(resp, "You don't have access to this organisation", status_code=403)
                self.assertContains(resp, '/accounts/logout/', status_code=403)

    def test_non_member_can_still_log_out(self):
        self.client.force_login(self.silavapi['user'])
        resp = self.client.post('/accounts/logout/', HTTP_HOST=MERCURY)
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_page_is_public_on_a_pinned_host(self):
        self.assertEqual(self.client.get('/accounts/login/', HTTP_HOST=MERCURY).status_code, 200)
        resp = self.client.get('/', HTTP_HOST=MERCURY)
        self.assertRedirects(resp, '/accounts/login/?next=/', fetch_redirect_response=False)

    def test_superuser_without_membership_sees_the_host_org(self):
        root = User.objects.create_superuser(username='root', password='pw')
        self.client.force_login(root)
        resp = self.client.get('/', HTTP_HOST=MERCURY)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['active_org'], self.mercury['org'])
        self.assertEqual(resp.context['user_orgs'], [self.mercury['org']])

    def test_org_setup_redirects_home_on_a_pinned_host(self):
        root = User.objects.create_superuser(username='root', password='pw')
        self.client.force_login(root)
        resp = self.client.get('/org/setup/', HTTP_HOST=MERCURY, follow=True)
        self.assertRedirects(resp, '/')
        self.assertContains(resp, 'This address belongs to Mercury Org')
        self.client.post('/org/setup/', {'name': 'Sneaky Org'}, HTTP_HOST=MERCURY)
        self.assertFalse(Organization.objects.filter(name='Sneaky Org').exists())

    def test_active_org_is_resolved_once_per_request(self):
        self.client.force_login(self.mercury['user'])
        with mock.patch(
            'apps.accounts.scoping._resolve_active_org', return_value=self.mercury['org']
        ) as resolve:
            self.client.get('/', HTTP_HOST=MERCURY)
        self.assertEqual(resolve.call_count, 1)


@override_settings(ALLOWED_HOSTS=HOSTS)
class UnpinnedHostTest(TwoOrgMixin, TestCase):
    """A host with no domain record keeps the session switcher, even when domains exist."""

    def setUp(self):
        super().setUp()
        OrganizationDomain.objects.create(organization=self.alpha['org'], hostname=MERCURY)

    def test_session_switcher_still_works_on_an_unmapped_host(self):
        resp = self.client.get('/', HTTP_HOST='testserver')
        self.assertEqual(resp.context['active_org'], self.alpha['org'])
        self.assertEqual(len(resp.context['user_orgs']), 2)
        self.assertContains(resp, 'Switch Organisation')

        self.assertEqual(self.switch_to(self.beta).status_code, 302)
        resp = self.client.get('/', HTTP_HOST='testserver')
        self.assertEqual(resp.context['active_org'], self.beta['org'])

    def test_pinned_host_overrides_a_session_switched_elsewhere(self):
        self.switch_to(self.beta)
        resp = self.client.get('/', HTTP_HOST=MERCURY)
        self.assertEqual(resp.context['active_org'], self.alpha['org'])
        self.assertEqual(self.client.session[SESSION_ORG_KEY], self.beta['org'].pk)
