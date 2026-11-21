"""Limits on sign-in failures and password reset requests.

Every limit reads its settings when called, so a deployment (or a test) can
tune or switch off each one. A limit of 0 disables it.
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.crypto import salted_hmac

from apps.audit.services import record

from .addresses import address_bucket
from .models import Throttle

MINIMUM_RETENTION_SECONDS = 24 * 60 * 60


def hashed(value):
    """Keyed hash of an identifier, so the table holds no usernames, emails or addresses."""
    return salted_hmac('apps.security.throttle', value, algorithm='sha256').hexdigest()


def _seconds_left(until, now):
    return max(1, int((until - now).total_seconds()) + 1)


def _prune(now):
    """Drop counters nothing can still depend on. Runs only when a counter is written."""
    keep = max(
        MINIMUM_RETENTION_SECONDS,
        settings.SIGN_IN_LOCKOUT_MAX_SECONDS + settings.SIGN_IN_FAILURE_WINDOW_SECONDS,
        settings.PASSWORD_RESET_WINDOW_SECONDS,
    )
    Throttle.objects.filter(
        throttling_failure_timestamp__lt=now - timedelta(seconds=keep),
    ).delete()


class SignInAttempt:
    """One username-and-password attempt, counted per account identifier and per address.

    The account identifier is whatever was typed, so the behaviour is the same
    whether or not such an account exists.
    """

    def __init__(self, request, username):
        self.request = request
        self.username = username or ''
        self.lock = (
            settings.SIGN_IN_LOCKOUT_SECONDS,
            settings.SIGN_IN_LOCKOUT_MAX_SECONDS,
        )
        self.targets = {}
        identifier = self.username.strip().lower()
        if identifier and settings.SIGN_IN_FAILURE_LIMIT > 0:
            self.targets[Throttle.SCOPE_SIGN_IN_ACCOUNT] = (
                hashed(identifier), settings.SIGN_IN_FAILURE_LIMIT,
            )
        bucket = address_bucket(request)
        if bucket and settings.SIGN_IN_ADDRESS_FAILURE_LIMIT > 0:
            self.targets[Throttle.SCOPE_SIGN_IN_ADDRESS] = (
                hashed(bucket), settings.SIGN_IN_ADDRESS_FAILURE_LIMIT,
            )
        if settings.SIGN_IN_LOCKOUT_SECONDS <= 0:
            self.targets = {}
        self._found = None

    def _records(self):
        """Existing counters for this attempt, in one query. Usually there are none."""
        if self._found is None:
            self._found = {}
            if self.targets:
                lookup = Q()
                for scope, (key, _limit) in self.targets.items():
                    lookup |= Q(scope=scope, key=key)
                self._found = {t.scope: t for t in Throttle.objects.filter(lookup)}
        return self._found

    def seconds_to_wait(self):
        """Seconds until another attempt is accepted; 0 when not locked out."""
        now = timezone.now()
        wait = 0
        for scope, throttle in self._records().items():
            allowed, data = throttle.verify_is_allowed(self.targets[scope][1], *self.lock, now=now)
            if not allowed:
                wait = max(wait, _seconds_left(data['locked_until'], now))
        return wait

    def failed(self):
        """Count a wrong password. Returns the seconds locked out, 0 if still free to retry."""
        now = timezone.now()
        window = settings.SIGN_IN_FAILURE_WINDOW_SECONDS
        wait = 0
        for scope, (key, limit) in self.targets.items():
            with transaction.atomic():
                throttle, _created = Throttle.objects.select_for_update().get_or_create(
                    scope=scope, key=key,
                )
                if throttle.is_forgotten(limit, *self.lock, window, now=now):
                    throttle.throttling_failure_count = 0
                throttle.throttle_increment()
            seconds = throttle.lockout_seconds(limit, *self.lock)
            if seconds:
                wait = max(wait, seconds)
                self._record_lockout(scope, throttle, seconds)
        if self.targets:
            _prune(now)
        return wait

    def succeeded(self):
        """Forget the failures for this account. The address keeps its count:
        signing in to one account must not clear guesses made against others."""
        throttle = self._records().get(Throttle.SCOPE_SIGN_IN_ACCOUNT)
        if throttle is not None:
            throttle.delete()

    def _record_lockout(self, scope, throttle, seconds):
        from apps.audit.signals import organization_for

        user = get_user_model()._default_manager.filter(username=self.username).first()
        record(
            'user.sign_in_locked', request=self.request,
            organization=organization_for(user, self.request),
            details={
                'username': self.username,
                'limit': 'account' if scope == Throttle.SCOPE_SIGN_IN_ACCOUNT else 'address',
                'failures': throttle.throttling_failure_count,
                'seconds': seconds,
            },
        )


def _count_request(scope, value, limit, window):
    """Count one request against a fixed window. Returns seconds to wait, 0 when allowed."""
    if limit <= 0 or window <= 0 or not value:
        return 0
    now = timezone.now()
    with transaction.atomic():
        throttle, _created = Throttle.objects.select_for_update().get_or_create(
            scope=scope, key=hashed(value),
        )
        started = throttle.throttling_failure_timestamp
        if started is None or now >= started + timedelta(seconds=window):
            throttle.throttling_failure_timestamp = started = now
            throttle.throttling_failure_count = 0
        if throttle.throttling_failure_count >= limit:
            return _seconds_left(started + timedelta(seconds=window), now)
        throttle.throttling_failure_count += 1
        throttle.save()
    _prune(now)
    return 0


def password_reset_wait(request):
    """Count a reset request from this address. Returns seconds to wait, 0 when allowed."""
    return _count_request(
        Throttle.SCOPE_RESET_ADDRESS, address_bucket(request),
        settings.PASSWORD_RESET_ADDRESS_LIMIT, settings.PASSWORD_RESET_WINDOW_SECONDS,
    )


def password_reset_email_allowed(email):
    """Count a reset email to this address; False once the window's allowance is used."""
    return not _count_request(
        Throttle.SCOPE_RESET_EMAIL, (email or '').strip().lower(),
        settings.PASSWORD_RESET_EMAIL_LIMIT, settings.PASSWORD_RESET_WINDOW_SECONDS,
    )
