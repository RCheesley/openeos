from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Membership, Organization
from apps.accounts.strety_import import StretyFormatError, StretyImporter


class Command(BaseCommand):
    help = (
        'Load a Strety export folder (teams, goals, issues, to-dos, metrics, vto.md and the '
        'accountability chart) into an organisation. Runs in one transaction; --dry-run '
        'prints the summary and saves nothing. Re-running skips rows that already exist.'
    )

    def add_arguments(self, parser):
        parser.add_argument('folder', help='Path to the unpacked Strety export.')
        target = parser.add_mutually_exclusive_group(required=True)
        target.add_argument(
            '--organization', metavar='SLUG', help='Slug of an existing organisation.',
        )
        target.add_argument(
            '--create-organization', metavar='NAME',
            help='Create an organisation with this name and import into it.',
        )
        parser.add_argument(
            '--user', metavar='USERNAME',
            help='Who is importing: stands in for unmatched people where a user is '
                 'required and is recorded as the editor. Defaults to the first admin of '
                 'the organisation, then the first superuser.',
        )
        parser.add_argument(
            '--create-users', action='store_true',
            help='Create a member (with no usable password) for each name that does not '
                 'match an existing member.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Do the whole import, print the summary, then roll everything back.',
        )
        parser.add_argument(
            '--include-archived', action='store_true',
            help='Import goals that Strety marked as archived (skipped by default).',
        )

    def handle(self, *args, **options):
        try:
            summary, organization = self._run(options)
        except StretyFormatError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(summary.as_text())
        if options['dry_run']:
            self.stdout.write(self.style.WARNING('Dry run: nothing was saved.'))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'Imported into "{organization.name}" ({summary.total_created()} records).'
            ))

    def _run(self, options):
        """Resolve the organisation and user, then import. Everything is one transaction."""
        with transaction.atomic():
            organization, created_org = self._organization(options)
            user = self._importing_user(options['user'], organization)
            if created_org:
                Membership.objects.get_or_create(
                    user=user, organization=organization,
                    defaults={'role': Membership.ROLE_ADMIN},
                )
            importer = StretyImporter(
                options['folder'], organization, user,
                create_users=options['create_users'], dry_run=options['dry_run'],
                include_archived=options['include_archived'],
            )
            summary = importer.run()
            if options['dry_run']:
                transaction.set_rollback(True)
        return summary, organization

    @staticmethod
    def _organization(options):
        if options['create_organization']:
            name = options['create_organization'].strip()
            if not name:
                raise CommandError('--create-organization needs a name.')
            if Organization.objects.filter(name=name).exists():
                raise CommandError(
                    f'An organisation called "{name}" already exists; use --organization.'
                )
            return Organization.objects.create(name=name), True
        slug = options['organization']
        organization = Organization.objects.filter(slug=slug).first()
        if organization is None:
            raise CommandError(f'No organisation with slug "{slug}".')
        return organization, False

    @staticmethod
    def _importing_user(username, organization):
        if username:
            user = User.objects.filter(username=username).first()
            if user is None:
                raise CommandError(f'No user with username "{username}".')
            return user
        admin = (
            Membership.objects.filter(organization=organization, role=Membership.ROLE_ADMIN)
            .select_related('user').order_by('pk').first()
        )
        if admin is not None:
            return admin.user
        superuser = User.objects.filter(is_superuser=True).order_by('pk').first()
        if superuser is not None:
            return superuser
        raise CommandError(
            'No admin member or superuser found to act as the importing user; pass --user.'
        )
