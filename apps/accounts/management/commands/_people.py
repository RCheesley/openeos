"""Find the account a personal-data command was asked about."""
from django.contrib.auth import get_user_model
from django.core.management.base import CommandError


def find_user(identifier):
    """The account with this username, or else the only one with this email."""
    users = get_user_model()._default_manager
    user = users.filter(username=identifier).first()
    if user is not None:
        return user
    by_email = list(users.filter(email__iexact=identifier)[:2]) if identifier else []
    if len(by_email) == 1:
        return by_email[0]
    if len(by_email) > 1:
        raise CommandError(
            f'More than one account has the email "{identifier}". Give the username instead.'
        )
    raise CommandError(f'No account has the username or email "{identifier}".')
