from django.contrib.auth.views import LoginView, PasswordResetView
from django.http import HttpResponseRedirect

from . import throttle
from .forms import SignInForm


def wait_phrase(seconds):
    minutes = -(-seconds // 60)
    return '1 minute' if minutes == 1 else f'{minutes} minutes'


class SignInView(LoginView):
    form_class = SignInForm


class ThrottledPasswordResetView(PasswordResetView):
    """Password reset with a limit per client address and per target email.

    Neither limit depends on whether the email belongs to an account. Past the
    email limit the visitor still sees the usual "check your inbox" page; no
    further message is sent.
    """

    def form_valid(self, form):
        wait = throttle.password_reset_wait(self.request)
        if wait:
            form.add_error(None, (
                'Too many password reset requests. '
                f'Please wait {wait_phrase(wait)} before trying again.'
            ))
            return self.form_invalid(form)
        if not throttle.password_reset_email_allowed(form.cleaned_data['email']):
            return HttpResponseRedirect(self.get_success_url())
        return super().form_valid(form)
