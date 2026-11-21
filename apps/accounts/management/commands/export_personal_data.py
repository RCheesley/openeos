from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.personal_data.export import (
    FORMAT_VERSION, archive_filename, build_personal_archive,
)
from apps.accounts.personal_data.relations import UnhandledRelation
from apps.audit.services import record

from ._people import find_user


class Command(BaseCommand):
    help = (
        'Write one person\'s personal data to a zip archive, the same one they can download '
        'from their profile. For a person who cannot sign in, or whose data is too large '
        'for a browser download. The export is recorded in the audit log.'
    )

    def add_arguments(self, parser):
        parser.add_argument('user', help='Username of the person, or their email address.')
        parser.add_argument(
            '--out', default='.', metavar='DIR',
            help='Directory to write the archive into (default: the current directory).',
        )

    def handle(self, *args, **options):
        user = find_user(options['user'])
        out_dir = Path(options['out'])
        out_dir.mkdir(parents=True, exist_ok=True)
        now = timezone.now()
        path = out_dir / archive_filename(user, now)
        try:
            with open(path, 'wb') as fh:
                manifest = build_personal_archive(user, fileobj=fh, via='command', exported_at=now)
        except UnhandledRelation as exc:
            path.unlink(missing_ok=True)
            raise CommandError(str(exc))
        except Exception:
            path.unlink(missing_ok=True)
            raise
        record(
            'user.personal_data_exported', target=user, details={
                'format_version': FORMAT_VERSION, 'via': 'command',
                'size_bytes': path.stat().st_size,
                'record_counts': manifest['record_counts'],
            },
        )
        self.stdout.write(str(path))
