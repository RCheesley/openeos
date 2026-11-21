"""Let a signed-in person download a copy of their own data."""
import tempfile

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import FileResponse
from django.utils import timezone
from django.views.generic import FormView

from apps.audit.services import record
from apps.audit.signals import organization_for

from .personal_data.export import (
    FORMAT_VERSION, ArchiveTooLarge, archive_filename, build_personal_archive,
)
from .views_export import ExportConfirmForm


class PersonalDataExportView(LoginRequiredMixin, FormView):
    """Explain what the archive holds, confirm the password, send the zip.

    Open to every signed-in person, for their own account only: there is no
    id in the address. Every download is written to the audit log with its
    size and record counts.
    """

    template_name = 'accounts/personal_data_export.html'
    form_class = ExportConfirmForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['memberships'] = self.request.user.memberships.select_related('organization')
        return ctx

    def form_valid(self, form):
        user = self.request.user
        now = timezone.now()
        archive = tempfile.TemporaryFile()
        try:
            manifest = build_personal_archive(
                user, fileobj=archive, via='web',
                max_bytes=settings.EXPORT_MAX_BYTES, exported_at=now,
            )
        except ArchiveTooLarge:
            archive.close()
            megabytes = settings.EXPORT_MAX_BYTES // (1024 * 1024)
            form.add_error(None, (
                f'Your data is larger than the {megabytes} MB limit for downloads from the '
                f'browser. Ask whoever runs this server to export it for you.'
            ))
            return self.form_invalid(form)

        size = archive.tell()
        archive.seek(0)
        record(
            'user.personal_data_exported', request=self.request,
            organization=organization_for(user, self.request), target=user, details={
                'format_version': FORMAT_VERSION, 'via': 'web', 'size_bytes': size,
                'record_counts': manifest['record_counts'],
            },
        )
        return FileResponse(
            archive, as_attachment=True, filename=archive_filename(user, now),
            content_type='application/zip',
        )
