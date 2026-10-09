"""Record authentication events. Connected from :class:`apps.audit.apps.AuditConfig`."""
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .services import record


@receiver(user_logged_in, dispatch_uid='audit.user_logged_in')
def on_user_logged_in(sender, request, user, **kwargs):
    record('user.login', request=request, actor=user)


@receiver(user_logged_out, dispatch_uid='audit.user_logged_out')
def on_user_logged_out(sender, request, user, **kwargs):
    if user is None or not user.is_authenticated:
        return
    record('user.logout', request=request, actor=user)


@receiver(user_login_failed, dispatch_uid='audit.user_login_failed')
def on_user_login_failed(sender, credentials, request=None, **kwargs):
    record(
        'user.login_failed', request=request,
        details={'username': credentials.get('username')},
    )
