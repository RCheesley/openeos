from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import PermissionDenied

from .throttle import SignInAttempt


class ThrottledModelBackend(ModelBackend):
    """Django's username-and-password check with a limit on wrong guesses.

    Sitting in the backend means every sign-in form is covered, the Django
    admin's included. While locked out the password is not checked at all, so a
    correct one is refused like any other.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(get_user_model().USERNAME_FIELD)
        if username is None or password is None:
            return None
        attempt = SignInAttempt(request, username)
        wait = attempt.seconds_to_wait()
        if wait:
            self._tell_the_form(request, wait)
            # Stops the remaining backends and fires user_login_failed.
            raise PermissionDenied('Too many failed sign-in attempts.')
        user = super().authenticate(request, username=username, password=password, **kwargs)
        if user is None:
            self._tell_the_form(request, attempt.failed())
        else:
            attempt.succeeded()
        return user

    @staticmethod
    def _tell_the_form(request, wait):
        if request is not None and wait:
            request.sign_in_wait_seconds = wait
