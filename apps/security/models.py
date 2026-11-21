from datetime import timedelta

from django.db import models
from django.utils import timezone
from django_otp.models import ThrottlingMixin


class Throttle(ThrottlingMixin, models.Model):
    """Failure or request counter for one account identifier, email or client address.

    Built on the same django-otp mixin that throttles two-factor codes, so the
    counter fields, ``throttle_increment`` / ``throttle_reset`` and the shape of
    ``verify_is_allowed`` are the ones already used for authenticator devices.
    The difference is that a number of attempts are free before the first
    lock-out, and the lock-out has an upper bound, so that nobody can keep a
    colleague out for days by typing their username.

    ``key`` is a keyed hash, never the username, email or address itself. Rows
    live in the database because the app runs several Gunicorn workers and has
    no shared cache; a row exists only while there is something to count.
    """

    SCOPE_SIGN_IN_ACCOUNT = 'sign_in_account'
    SCOPE_SIGN_IN_ADDRESS = 'sign_in_address'
    SCOPE_RESET_ADDRESS = 'reset_address'
    SCOPE_RESET_EMAIL = 'reset_email'
    SCOPE_CHOICES = [
        (SCOPE_SIGN_IN_ACCOUNT, 'Sign-in failures for one account identifier'),
        (SCOPE_SIGN_IN_ADDRESS, 'Sign-in failures from one address'),
        (SCOPE_RESET_ADDRESS, 'Password reset requests from one address'),
        (SCOPE_RESET_EMAIL, 'Password reset emails to one address'),
    ]

    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES)
    key = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['scope', 'key'], name='security_throttle_scope_key'),
        ]
        indexes = [
            models.Index(
                fields=['throttling_failure_timestamp'], name='security_throttle_time_idx',
            ),
        ]
        verbose_name = 'Throttle counter'
        verbose_name_plural = 'Throttle counters'

    def __str__(self):
        return f'{self.get_scope_display()} ({self.throttling_failure_count})'

    # ── Lock-out after repeated failures (sign-in) ───────────────────────────

    def lockout_seconds(self, limit, base, maximum):
        """How long the current failure count locks for: base, 2x base, 4x base ... up to maximum."""
        over = self.throttling_failure_count - limit
        if limit <= 0 or base <= 0 or over < 0:
            return 0
        return min(base * 2 ** min(over, 32), max(base, maximum))

    def locked_until(self, limit, base, maximum):
        seconds = self.lockout_seconds(limit, base, maximum)
        if not seconds or self.throttling_failure_timestamp is None:
            return None
        return self.throttling_failure_timestamp + timedelta(seconds=seconds)

    def verify_is_allowed(self, limit, base, maximum, now=None):
        """``(True, None)`` or ``(False, {'failure_count': n, 'locked_until': datetime})``."""
        until = self.locked_until(limit, base, maximum)
        if until is not None and (now or timezone.now()) < until:
            return False, {
                'failure_count': self.throttling_failure_count,
                'locked_until': until,
            }
        return True, None

    def is_forgotten(self, limit, base, maximum, window, now=None):
        """True once ``window`` seconds have passed since the last failure or lock-out."""
        if self.throttling_failure_timestamp is None:
            return True
        end = self.locked_until(limit, base, maximum) or self.throttling_failure_timestamp
        return (now or timezone.now()) >= end + timedelta(seconds=window)

    def get_throttle_factor(self):
        # The mixin's own back-off is replaced by lockout_seconds() above.
        return 0
