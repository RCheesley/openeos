"""An organisation can require two-factor authentication for everyone in it."""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django_otp import DEVICE_ID_SESSION_KEY

from apps.accounts.models import Membership, Organization, OrganizationDomain
from apps.audit.models import AuditEvent

from .test_domains import HOSTS, MERCURY, SILAVAPI
from .test_isolation import build_org, pk_urls
from .test_memberships import TwoOrgMixin
from .test_portability_import import ImportTestBase
from .test_portability import export_to_bytes
from .test_two_factor import (
    DISABLE_URL, PASSWORD, SETUP_URL, VERIFY_URL, confirmed_totp_device, totp_code,
)

SETTINGS_URL = '/org/settings/'
REQUIRED = 'organization.two_factor_required'
NOT_REQUIRED = 'organization.two_factor_not_required'


def setup_redirect(next_path):
    return f'{SETUP_URL}?next={next_path}'


class VerifiedSessionMixin:
    def enrol_and_verify(self, user):
        """Give ``user`` a confirmed authenticator and mark this session as verified with it."""
        device = confirmed_totp_device(user)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()
        return device


class RequirementSettingTest(VerifiedSessionMixin, TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Harbour Lights')
        self.admin = User.objects.create_user(username='orgadmin', password=PASSWORD)
        Membership.objects.create(user=self.admin, organization=self.org, role=Membership.ROLE_ADMIN)
        self.member = User.objects.create_user(username='plainmember', password=PASSWORD)
        Membership.objects.create(user=self.member, organization=self.org)

    def post_settings(self, **extra):
        data = {'name': self.org.name, 'navbar_style': self.org.navbar_style, 'primary_color': '#0d6efd'}
        data.update(extra)
        return self.client.post(SETTINGS_URL, data)

    def test_new_organisations_do_not_require_it(self):
        self.assertFalse(self.org.require_two_factor)

    def test_admin_sees_the_setting_with_a_label_and_the_count_still_to_set_up(self):
        self.client.force_login(self.admin)
        resp = self.client.get(SETTINGS_URL)
        self.assertContains(resp, 'Require two-step sign-in for everyone in this organisation')
        self.assertContains(resp, 'for="id_require_two_factor"')
        self.assertContains(resp, 'type="checkbox"')
        self.assertEqual(resp.context['members_without_two_factor'], 2)
        self.assertEqual(resp.context['member_count'], 2)

    def test_member_cannot_open_or_change_the_setting(self):
        self.client.force_login(self.member)
        self.enrol_and_verify(self.member)
        self.assertEqual(self.client.get(SETTINGS_URL).status_code, 403)
        self.assertEqual(self.post_settings(require_two_factor='on').status_code, 403)
        self.org.refresh_from_db()
        self.assertFalse(self.org.require_two_factor)
        self.assertFalse(AuditEvent.objects.filter(action=REQUIRED).exists())

    def test_admin_without_two_factor_cannot_switch_it_on(self):
        self.client.force_login(self.admin)
        resp = self.post_settings(require_two_factor='on')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Set up two-factor authentication on your own account first')
        self.org.refresh_from_db()
        self.assertFalse(self.org.require_two_factor)
        self.assertFalse(AuditEvent.objects.filter(action=REQUIRED).exists())

    def test_admin_with_two_factor_switches_it_on_and_it_is_audited(self):
        self.client.force_login(self.admin)
        self.enrol_and_verify(self.admin)
        resp = self.post_settings(require_two_factor='on')
        self.assertRedirects(resp, '/org/', fetch_redirect_response=False)
        self.org.refresh_from_db()
        self.assertTrue(self.org.require_two_factor)
        event = AuditEvent.objects.get(action=REQUIRED)
        self.assertEqual(event.actor, self.admin)
        self.assertEqual(event.organization, self.org)
        self.assertEqual(event.target_id, str(self.org.pk))

    def test_switching_it_off_is_audited(self):
        Organization.objects.filter(pk=self.org.pk).update(require_two_factor=True)
        self.client.force_login(self.admin)
        self.enrol_and_verify(self.admin)
        resp = self.post_settings()
        self.assertRedirects(resp, '/org/', fetch_redirect_response=False)
        self.org.refresh_from_db()
        self.assertFalse(self.org.require_two_factor)
        event = AuditEvent.objects.get(action=NOT_REQUIRED)
        self.assertEqual(event.actor, self.admin)
        self.assertEqual(event.organization, self.org)

    def test_saving_other_settings_leaves_no_requirement_event(self):
        self.client.force_login(self.admin)
        self.post_settings(tagline='Onwards')
        Organization.objects.filter(pk=self.org.pk).update(require_two_factor=True)
        self.enrol_and_verify(self.admin)
        self.post_settings(tagline='Further', require_two_factor='on')
        self.assertFalse(AuditEvent.objects.filter(action__in=[REQUIRED, NOT_REQUIRED]).exists())

    def test_django_admin_change_is_audited_too(self):
        root = User.objects.create_superuser(username='root', password=PASSWORD)
        self.client.force_login(root)
        resp = self.client.post(f'/admin/accounts/organization/{self.org.pk}/change/', {
            'name': self.org.name, 'slug': self.org.slug, 'navbar_style': 'dark',
            'require_two_factor': 'on',
            'domains-TOTAL_FORMS': 0, 'domains-INITIAL_FORMS': 0,
            'memberships-TOTAL_FORMS': 0, 'memberships-INITIAL_FORMS': 0,
        })
        self.assertEqual(resp.status_code, 302)
        self.org.refresh_from_db()
        self.assertTrue(self.org.require_two_factor)
        self.assertEqual(AuditEvent.objects.get(action=REQUIRED).actor, root)


class EnforcementTest(VerifiedSessionMixin, TestCase):
    def setUp(self):
        self.f = build_org('Mine')
        self.org = self.f['org']
        self.org.require_two_factor = True
        self.org.save()
        self.user = self.f['user']
        self.user.set_password(PASSWORD)
        self.user.save()
        self.client.force_login(self.user)

    def test_member_without_two_factor_is_sent_to_set_up(self):
        for path in ('/', '/rocks/', '/org/', '/users/', SETTINGS_URL, '/notifications/preferences/'):
            with self.subTest(path=path):
                resp = self.client.get(path)
                self.assertRedirects(resp, setup_redirect(path), fetch_redirect_response=False)

    def test_every_record_page_is_held_back(self):
        gets, posts = pk_urls(self.f)
        for url in gets:
            with self.subTest(method='GET', url=url):
                self.assertTrue(self.client.get(url)['Location'].startswith(SETUP_URL))
        for url, data in posts:
            with self.subTest(method='POST', url=url):
                self.assertTrue(self.client.post(url, data)['Location'].startswith(SETUP_URL))

    def test_posts_are_held_back_without_changing_anything(self):
        resp = self.client.post(f'/todos/{self.f["todo"].pk}/complete/')
        self.assertTrue(resp['Location'].startswith(SETUP_URL))
        self.f['todo'].refresh_from_db()
        self.assertFalse(self.f['todo'].is_complete)

    def test_profile_set_up_and_sign_out_stay_reachable(self):
        self.assertEqual(self.client.get('/profile/').status_code, 200)
        self.assertEqual(self.client.get('/profile/edit/').status_code, 200)
        self.assertEqual(self.client.get(SETUP_URL).status_code, 200)
        self.assertEqual(self.client.get('/healthz/').status_code, 200)
        resp = self.client.post('/accounts/logout/')
        self.assertNotIn(SETUP_URL, resp.get('Location', ''))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_set_up_page_names_the_organisation(self):
        resp = self.client.get(setup_redirect('/rocks/'))
        self.assertContains(resp, 'Mine Org</strong> requires two-step sign-in')

    def test_profile_says_the_organisation_requires_it(self):
        resp = self.client.get('/profile/')
        self.assertContains(resp, 'Not enabled')
        self.assertContains(resp, 'it before you can work there')

    def test_finishing_set_up_lets_the_member_in_and_offers_the_page_they_wanted(self):
        self.client.get(SETUP_URL)
        device = self.user.totpdevice_set.get()
        resp = self.client.post(setup_redirect('/rocks/'), {'token': totp_code(device)})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'href="/rocks/"')
        self.assertEqual(self.client.get('/rocks/').status_code, 200)

    def test_off_site_next_is_not_offered_after_set_up(self):
        self.client.get(SETUP_URL)
        device = self.user.totpdevice_set.get()
        resp = self.client.post(
            f'{SETUP_URL}?next=https://evil.example/phish', {'token': totp_code(device)}
        )
        self.assertNotContains(resp, 'evil.example')
        self.assertContains(resp, 'href="/profile/"')

    def test_member_with_two_factor_verifies_as_before(self):
        confirmed_totp_device(self.user)
        resp = self.client.get('/rocks/')
        self.assertRedirects(resp, f'{VERIFY_URL}?next=/rocks/', fetch_redirect_response=False)

    def test_verified_member_is_not_held_back(self):
        self.enrol_and_verify(self.user)
        self.assertEqual(self.client.get('/rocks/').status_code, 200)

    def test_nobody_is_held_back_when_it_is_not_required(self):
        Organization.objects.filter(pk=self.org.pk).update(require_two_factor=False)
        self.assertEqual(self.client.get('/rocks/').status_code, 200)

    def test_anonymous_visitor_goes_to_sign_in(self):
        self.client.logout()
        resp = self.client.get('/rocks/')
        self.assertRedirects(resp, '/accounts/login/?next=/rocks/', fetch_redirect_response=False)

    def test_user_without_an_organisation_is_not_held_back(self):
        orphan = User.objects.create_user(username='orphan', password=PASSWORD)
        self.client.force_login(orphan)
        resp = self.client.get('/')
        self.assertNotIn(SETUP_URL, resp.get('Location', ''))

    def test_superuser_working_in_the_organisation_is_held_back_like_anyone_else(self):
        root = User.objects.create_superuser(username='root', password=PASSWORD)
        Membership.objects.create(user=root, organization=self.org, role=Membership.ROLE_ADMIN)
        self.client.force_login(root)
        self.assertRedirects(
            self.client.get('/rocks/'), setup_redirect('/rocks/'), fetch_redirect_response=False
        )
        self.assertRedirects(
            self.client.get('/admin/'), setup_redirect('/admin/'), fetch_redirect_response=False
        )

    def test_superuser_with_no_organisation_keeps_the_django_admin(self):
        root = User.objects.create_superuser(username='root', password=PASSWORD)
        self.client.force_login(root)
        self.assertEqual(self.client.get('/admin/').status_code, 200)


class TwoOrganisationTest(VerifiedSessionMixin, TwoOrgMixin, TestCase):
    """Alpha requires it, Beta does not; the user belongs to both."""

    def setUp(self):
        super().setUp()
        self.user.set_password(PASSWORD)
        self.user.save()
        self.client.force_login(self.user)
        Organization.objects.filter(pk=self.alpha['org'].pk).update(require_two_factor=True)

    def test_held_back_only_in_the_organisation_that_requires_it(self):
        # Alpha is first by name, so it is the active organisation to begin with.
        self.assertRedirects(
            self.client.get('/rocks/'), setup_redirect('/rocks/'), fetch_redirect_response=False
        )
        resp = self.switch_to(self.beta)
        self.assertRedirects(resp, '/', fetch_redirect_response=False)
        resp = self.client.get('/rocks/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['active_org'], self.beta['org'])
        self.assertEqual(self.client.get(f'/rocks/{self.beta["rock"].pk}/').status_code, 200)

    def test_switching_back_to_the_requiring_organisation_holds_them_again(self):
        self.switch_to(self.beta)
        self.switch_to(self.alpha)
        self.assertRedirects(
            self.client.get('/rocks/'), setup_redirect('/rocks/'), fetch_redirect_response=False
        )

    def test_cannot_switch_it_off_while_any_organisation_requires_it(self):
        self.enrol_and_verify(self.user)
        self.switch_to(self.beta)
        resp = self.client.post(DISABLE_URL, {'password': PASSWORD}, follow=True)
        self.assertContains(resp, 'Alpha Org requires it')
        self.assertTrue(self.user.totpdevice_set.filter(confirmed=True).exists())

    def test_profile_explains_instead_of_offering_the_disable_form(self):
        self.enrol_and_verify(self.user)
        resp = self.client.get('/profile/')
        self.assertContains(resp, 'You cannot switch this off because')
        self.assertContains(resp, '<strong>Alpha Org</strong>')
        self.assertNotContains(resp, f'action="{DISABLE_URL}"')

    def test_can_switch_it_off_once_no_organisation_requires_it(self):
        self.enrol_and_verify(self.user)
        Organization.objects.filter(pk=self.alpha['org'].pk).update(require_two_factor=False)
        self.assertContains(self.client.get('/profile/'), f'action="{DISABLE_URL}"')
        self.client.post(DISABLE_URL, {'password': PASSWORD})
        self.assertFalse(self.user.totpdevice_set.exists())

    def test_can_switch_it_off_after_leaving_the_organisation(self):
        self.enrol_and_verify(self.user)
        Membership.objects.filter(user=self.user, organization=self.alpha['org']).delete()
        self.client.post(DISABLE_URL, {'password': PASSWORD})
        self.assertFalse(self.user.totpdevice_set.exists())


@override_settings(ALLOWED_HOSTS=HOSTS)
class HostPinnedTest(TwoOrgMixin, TestCase):
    """Alpha (requires it) and Beta (does not) each have their own hostname."""

    def setUp(self):
        super().setUp()
        Organization.objects.filter(pk=self.alpha['org'].pk).update(require_two_factor=True)
        OrganizationDomain.objects.create(organization=self.alpha['org'], hostname=MERCURY)
        OrganizationDomain.objects.create(organization=self.beta['org'], hostname=SILAVAPI)

    def test_held_back_on_the_requiring_organisations_host_whatever_the_session_says(self):
        self.switch_to(self.beta)
        resp = self.client.get('/rocks/', HTTP_HOST=MERCURY)
        self.assertRedirects(resp, setup_redirect('/rocks/'), fetch_redirect_response=False)

    def test_not_held_back_on_the_other_organisations_host(self):
        resp = self.client.get('/rocks/', HTTP_HOST=SILAVAPI)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['active_org'], self.beta['org'])

    def test_set_up_and_profile_are_reachable_on_the_pinned_host(self):
        resp = self.client.get(SETUP_URL, HTTP_HOST=MERCURY)
        self.assertContains(resp, 'Alpha Org</strong> requires two-step sign-in')
        self.assertEqual(self.client.get('/profile/', HTTP_HOST=MERCURY).status_code, 200)

    def test_superuser_who_is_not_a_member_is_held_back_on_the_pinned_host(self):
        root = User.objects.create_superuser(username='root', password=PASSWORD)
        self.client.force_login(root)
        resp = self.client.get('/rocks/', HTTP_HOST=MERCURY)
        self.assertRedirects(resp, setup_redirect('/rocks/'), fetch_redirect_response=False)
        self.assertEqual(self.client.get('/rocks/', HTTP_HOST=SILAVAPI).status_code, 200)


class UserListColumnTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Harbour Lights')
        self.admin = User.objects.create_user(username='orgadmin', password=PASSWORD)
        Membership.objects.create(user=self.admin, organization=self.org, role=Membership.ROLE_ADMIN)
        self.member = User.objects.create_user(username='plainmember', password=PASSWORD)
        Membership.objects.create(user=self.member, organization=self.org)
        self.client.force_login(self.admin)

    def statuses(self, resp):
        return {m.user.username: m.has_two_factor for m in resp.context['memberships']}

    def test_column_says_in_words_who_has_it_on(self):
        confirmed_totp_device(self.member)
        resp = self.client.get('/users/')
        self.assertEqual(self.statuses(resp), {'orgadmin': False, 'plainmember': True})
        self.assertContains(resp, '<th>Two-factor authentication</th>', html=True)
        self.assertContains(resp, 'Not set up', count=1)
        self.assertContains(resp, '</i>On</span>', count=1)

    def test_an_unconfirmed_authenticator_does_not_count(self):
        self.member.totpdevice_set.create(name='Authenticator app', confirmed=False)
        resp = self.client.get('/users/')
        self.assertEqual(self.statuses(resp), {'orgadmin': False, 'plainmember': False})

    def test_page_says_when_it_is_required(self):
        self.assertNotContains(self.client.get('/users/'), 'Two-step sign-in is required')
        Organization.objects.filter(pk=self.org.pk).update(require_two_factor=True)
        device = confirmed_totp_device(self.admin)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()
        self.assertContains(self.client.get('/users/'), 'Two-step sign-in is required')

    def test_members_cannot_see_the_list(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get('/users/').status_code, 403)


class RequirementPortabilityTest(ImportTestBase):
    def test_export_and_import_carry_the_setting(self):
        org = self.a['org']
        org.require_two_factor = True
        org.save()
        blob, _ = export_to_bytes(org, exported_by=self.a['admin'])
        self.archive.write_bytes(blob)
        self.run_import()
        self.assertTrue(Organization.objects.get(slug='alpha-copy').require_two_factor)

    def test_an_organisation_without_the_requirement_imports_without_it(self):
        self.run_import()
        self.assertFalse(Organization.objects.get(slug='alpha-copy').require_two_factor)
