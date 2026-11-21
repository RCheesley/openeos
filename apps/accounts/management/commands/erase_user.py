from django.core.management.base import BaseCommand, CommandError

from apps.accounts.personal_data.erasure import (
    LAST_ADMIN, PLACEHOLDER_LABEL, SUPERUSER, ErasureRefused, PlaceholderConflict, erase, plan,
)
from apps.accounts.personal_data.relations import UnhandledRelation

from ._people import find_user

FLAGS = {LAST_ADMIN: '--allow-last-admin', SUPERUSER: '--allow-superuser'}


class Command(BaseCommand):
    help = (
        'Erase one person: clear their name, email, avatar, two-factor devices, sessions, '
        'memberships and rights, switch the account off, and show the records that named '
        f'them as "{PLACEHOLDER_LABEL}". What they wrote stays as the organisation\'s record. '
        'This cannot be undone. Run with --dry-run first to see exactly what would change. '
        'Safe to run again on an account that is already erased.'
    )

    def add_arguments(self, parser):
        parser.add_argument('user', help='Username of the person, or their email address.')
        parser.add_argument(
            '--dry-run', action='store_true',
            help='List what would change and stop. Nothing is written.',
        )
        parser.add_argument(
            '--yes', action='store_true',
            help='Do not ask for confirmation (for scripts).',
        )
        parser.add_argument(
            '--allow-last-admin', action='store_true',
            help='Erase the person even if an organisation is left without an admin.',
        )
        parser.add_argument(
            '--allow-superuser', action='store_true',
            help='Erase the person even though the account is a superuser.',
        )

    def handle(self, *args, **options):
        user = find_user(options['user'])
        username = user.get_username()
        try:
            planned = plan(user)
        except UnhandledRelation as exc:
            raise CommandError(str(exc))

        self.stdout.write(f'Erasing "{username}" (account id {user.pk}):')
        for step in planned.steps:
            self.stdout.write(f'  {step.count:>6}  {step.what}')
        allowed = {
            LAST_ADMIN: options['allow_last_admin'], SUPERUSER: options['allow_superuser'],
        }
        blocking = [
            (code, message) for code, message in planned.refusals if not allowed.get(code)
        ]
        for code, message in blocking:
            hint = f' Add {FLAGS[code]} to go ahead anyway.' if code in FLAGS else ''
            self.stdout.write(self.style.WARNING(f'  Refused: {message}{hint}'))

        if options['dry_run']:
            self.stdout.write('Dry run: nothing was changed.')
            return
        if blocking:
            raise CommandError('Not erased. ' + ' '.join(message for _, message in blocking))
        if not planned.has_changes:
            self.stdout.write(self.style.SUCCESS('Already erased: nothing to change.'))
            return

        if not options['yes']:
            answer = input(
                f'This cannot be undone. Type the username "{username}" to erase this person: '
            )
            if answer.strip() != username:
                raise CommandError('Not erased: the username did not match.')

        try:
            erase(
                user, allow_last_admin=options['allow_last_admin'],
                allow_superuser=options['allow_superuser'],
            )
        except (ErasureRefused, PlaceholderConflict) as exc:
            raise CommandError(f'Not erased. {exc}')
        self.stdout.write(self.style.SUCCESS(
            f'Erased. Account {user.pk} is switched off and now reads "{PLACEHOLDER_LABEL}".'
        ))
