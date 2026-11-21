"""Django's own password views, with the change written to the audit log.

Django sends no signal when a password changes, so these thin subclasses are
the one place both routes pass through. Only the fact is recorded, never the
password or the reset token.
"""
from django.contrib.auth import views as auth_views

from apps.audit.services import record_for_user


class PasswordChangeView(auth_views.PasswordChangeView):
    def form_valid(self, form):
        response = super().form_valid(form)
        record_for_user('user.password_changed', form.user, request=self.request)
        return response


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    """Also the page an invited user sets their first password on."""

    def form_valid(self, form):
        response = super().form_valid(form)
        record_for_user('user.password_reset', form.user, request=self.request)
        return response
