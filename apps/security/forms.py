from django import forms
from django.contrib.auth.forms import AuthenticationForm

from apps.accounts.two_factor.forms import too_many_attempts_message


class SignInForm(AuthenticationForm):
    """The standard sign-in form, plus a message when attempts are being limited."""

    throttled = False

    def clean(self):
        try:
            return super().clean()
        except forms.ValidationError:
            wait = getattr(self.request, 'sign_in_wait_seconds', 0)
            if not wait:
                raise
            self.throttled = True
            raise forms.ValidationError(too_many_attempts_message(wait), code='throttled')
