from io import StringIO

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.accounts.models import Membership, Organization, OrganizationDomain, Team


def run(**overrides):
    """Call create_organization with sensible defaults and return the captured stdout."""
    options = {
        'name': 'Acme Ltd',
        'domain': 'acme.example.test',
        'admin_username': 'acme-admin',
        'admin_email': 'admin@acme.example.test',
    }
    options.update(overrides)
    out = StringIO()
    call_command('create_organization', stdout=out, **options)
    return out.getvalue()


class CreateOrganizationCommandTest(TestCase):
    def test_creates_org_domain_admin_membership_and_team(self):
        output = run()

        org = Organization.objects.get(slug='acme-ltd')
        self.assertEqual(org.name, 'Acme Ltd')

        domain = OrganizationDomain.objects.get(hostname='acme.example.test')
        self.assertEqual(domain.organization, org)
        self.assertTrue(domain.is_primary)

        user = User.objects.get(username='acme-admin')
        self.assertEqual(user.email, 'admin@acme.example.test')
        membership = Membership.objects.get(user=user, organization=org)
        self.assertEqual(membership.role, Membership.ROLE_ADMIN)

        team = Team.objects.get(organization=org, name='Leadership')
        self.assertIn(team, user.profile.teams.all())

        self.assertIn('Organisation "Acme Ltd" is ready (created)', output)
        self.assertIn('acme.example.test (primary)', output)
        self.assertIn('Leadership', output)

    def test_rerun_is_idempotent_and_keeps_password(self):
        run()
        password_hash = User.objects.get(username='acme-admin').password
        counts = (
            Organization.objects.count(),
            OrganizationDomain.objects.count(),
            User.objects.count(),
            Membership.objects.count(),
            Team.objects.count(),
        )

        output = run()

        self.assertEqual(counts, (
            Organization.objects.count(),
            OrganizationDomain.objects.count(),
            User.objects.count(),
            Membership.objects.count(),
            Team.objects.count(),
        ))
        self.assertEqual(User.objects.get(username='acme-admin').password, password_hash)
        self.assertIn('already existed', output)
        self.assertNotIn('Generated password', output)

    def test_domain_owned_by_another_organisation_is_rejected(self):
        other = Organization.objects.create(name='Other Org')
        OrganizationDomain.objects.create(organization=other, hostname='acme.example.test')

        with self.assertRaisesMessage(CommandError, 'already belongs to organisation "Other Org"'):
            run()

        self.assertFalse(Organization.objects.filter(slug='acme-ltd').exists())
        self.assertFalse(User.objects.filter(username='acme-admin').exists())
        self.assertEqual(OrganizationDomain.objects.get(hostname='acme.example.test').organization, other)

    def test_generated_password_is_printed_once_and_works(self):
        output = run()

        lines = [line for line in output.splitlines() if 'Generated password' in line]
        self.assertEqual(len(lines), 1)
        password = lines[0].rsplit(': ', 1)[1].strip()
        self.assertEqual(len(password), 20)
        self.assertIsNotNone(authenticate(username='acme-admin', password=password))

    def test_explicit_password_is_used_and_not_printed(self):
        output = run(admin_password='correct horse battery staple')

        self.assertNotIn('correct horse battery staple', output)
        self.assertNotIn('Generated password', output)
        self.assertIsNotNone(authenticate(username='acme-admin', password='correct horse battery staple'))

    def test_explicit_password_on_rerun_resets_existing_user(self):
        run()
        run(admin_password='new-password-123')
        self.assertIsNotNone(authenticate(username='acme-admin', password='new-password-123'))

    def test_invalid_primary_colour_rolls_everything_back(self):
        with self.assertRaisesMessage(CommandError, 'Use a hex colour like #0d6efd.'):
            run(primary_color='teal')

        self.assertEqual(Organization.objects.count(), 0)
        self.assertEqual(OrganizationDomain.objects.count(), 0)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Membership.objects.count(), 0)
        self.assertEqual(Team.objects.count(), 0)

    def test_branding_applied_on_create_and_on_explicit_rerun(self):
        run(display_name='Acme', primary_color='#112233')
        org = Organization.objects.get(slug='acme-ltd')
        self.assertEqual(org.display_name, 'Acme')
        self.assertEqual(org.primary_color, '#112233')

        # A re-run without branding options leaves the existing values alone.
        run()
        org.refresh_from_db()
        self.assertEqual(org.display_name, 'Acme')
        self.assertEqual(org.primary_color, '#112233')

        run(display_name='Acme Corp', primary_color='#445566')
        org.refresh_from_db()
        self.assertEqual(org.display_name, 'Acme Corp')
        self.assertEqual(org.primary_color, '#445566')

    def test_second_domain_for_same_org_is_not_primary(self):
        run()
        output = run(domain='www.acme.example.test')

        first = OrganizationDomain.objects.get(hostname='acme.example.test')
        second = OrganizationDomain.objects.get(hostname='www.acme.example.test')
        self.assertEqual(first.organization, second.organization)
        self.assertTrue(first.is_primary)
        self.assertFalse(second.is_primary)
        self.assertIn('www.acme.example.test\n', output)
        self.assertNotIn('www.acme.example.test (primary)', output)

    def test_slug_override_and_hostname_normalisation(self):
        run(slug='acme', domain='  ACME.Example.TEST. ')
        org = Organization.objects.get(slug='acme')
        self.assertEqual(org.name, 'Acme Ltd')
        self.assertTrue(OrganizationDomain.objects.filter(organization=org, hostname='acme.example.test').exists())

    def test_hostname_with_scheme_is_rejected(self):
        with self.assertRaises(CommandError):
            run(domain='https://acme.example.test')
        self.assertEqual(Organization.objects.count(), 0)
