from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.crypto import get_random_string
from django.utils.text import slugify

from apps.accounts.models import Membership, Organization, OrganizationDomain, Team


class Command(BaseCommand):
    help = (
        "Create an organisation with a domain, an admin user and a first team in one "
        "non-interactive step, for scripted onboarding. Safe to re-run: existing "
        "records are reused and only the options you pass explicitly are updated. "
        "Prefer leaving --admin-password out so a random password is generated and "
        "printed once; a password passed on the command line is visible in process "
        "listings and shell history."
    )

    def add_arguments(self, parser):
        parser.add_argument('--name', required=True, help='Organisation name, e.g. "Acme Ltd".')
        parser.add_argument(
            '--domain', required=True,
            help='Hostname the organisation answers on, e.g. acme.example.com (no scheme, port or path).',
        )
        parser.add_argument('--admin-username', required=True, help='Username of the first admin.')
        parser.add_argument('--admin-email', required=True, help='Email address of the first admin.')
        parser.add_argument(
            '--admin-password',
            help=(
                'Password for the admin user. Visible in process listings, so prefer '
                'omitting it: a random password is then generated and printed once '
                'when the user is created.'
            ),
        )
        parser.add_argument('--display-name', help='Branding display name shown in the navbar and emails.')
        parser.add_argument('--primary-color', help='Branding primary colour as a hex value like #0d6efd.')
        parser.add_argument('--team', default='Leadership', help='Name of the first team (default: Leadership).')
        parser.add_argument('--slug', help='Override the slug derived from the organisation name.')

    def handle(self, *args, **options):
        name = options['name'].strip()
        slug = (options['slug'] or '').strip() or slugify(name)
        if not slug:
            raise CommandError('Could not derive a slug from the organisation name; pass --slug.')
        hostname = OrganizationDomain.normalize(options['domain'])
        username = options['admin_username'].strip()
        email = options['admin_email'].strip()
        team_name = options['team'].strip()

        with transaction.atomic():
            org, org_created = self._ensure_organization(name, slug, options)
            domain = self._ensure_domain(org, hostname)
            user, user_created, generated_password = self._ensure_admin_user(
                username, email, options['admin_password']
            )
            Membership.objects.update_or_create(
                user=user, organization=org, defaults={'role': Membership.ROLE_ADMIN}
            )
            team, _ = Team.objects.get_or_create(organization=org, name=team_name)
            user.profile.teams.add(team)

        self.stdout.write(self.style.SUCCESS(
            f'Organisation "{org.name}" is ready ({"created" if org_created else "already existed"}).\n'
            f'  Slug:   {org.slug}\n'
            f'  Domain: {domain.hostname}{" (primary)" if domain.is_primary else ""}\n'
            f'  Admin:  {user.username} <{user.email}> ({"created" if user_created else "already existed"})\n'
            f'  Team:   {team.name}'
        ))
        if generated_password:
            self.stdout.write(self.style.WARNING(
                f'Generated password for {user.username} (shown once, store it now): {generated_password}'
            ))

    def _ensure_organization(self, name, slug, options):
        branding = {}
        if options['display_name'] is not None:
            branding['display_name'] = options['display_name']
        if options['primary_color'] is not None:
            branding['primary_color'] = options['primary_color']

        org, created = Organization.objects.get_or_create(
            slug=slug, defaults={'name': name, **branding}
        )
        if not created:
            for field, value in branding.items():
                setattr(org, field, value)
        try:
            org.full_clean()
        except ValidationError as exc:
            raise CommandError('; '.join(exc.messages))
        if not created and branding:
            org.save(update_fields=list(branding))
        return org, created

    def _ensure_domain(self, org, hostname):
        probe = OrganizationDomain(organization=org, hostname=hostname)
        try:
            probe.clean()
        except ValidationError as exc:
            raise CommandError('; '.join(exc.messages))

        domain, created = OrganizationDomain.objects.get_or_create(
            hostname=hostname,
            defaults={
                'organization': org,
                'is_primary': not org.domains.filter(is_primary=True).exists(),
            },
        )
        if domain.organization_id != org.pk:
            raise CommandError(
                f'Domain {hostname} already belongs to organisation "{domain.organization.name}".'
            )
        return domain

    def _ensure_admin_user(self, username, email, password):
        user, created = User.objects.get_or_create(username=username, defaults={'email': email})
        generated_password = None
        if created and not password:
            password = generated_password = get_random_string(20)
        if created or password:
            user.set_password(password)
            user.save(update_fields=['password'])
        return user, created, generated_password
