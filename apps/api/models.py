"""What the API stores beside the OAuth library's own tables.

``OrganizationApiAccess`` is the per-organisation switch. ``Connection`` records
that a user let one application act in one organisation, and
``ConnectionCredential`` ties each authorisation code, access token and refresh
token to its connection, which is how a token knows its organisation.

None of this is part of an organisation export (``apps.api`` is not a portable
app), so tokens never leave the instance.
"""
from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from oauth2_provider.settings import oauth2_settings

from apps.accounts.models import Organization


class OrganizationApiAccess(models.Model):
    """Whether the API may be used for one organisation. Off until an admin turns it on."""

    organization = models.OneToOneField(
        Organization, on_delete=models.CASCADE, related_name='api_access'
    )
    enabled = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Organization API access'
        verbose_name_plural = 'Organization API access'

    def __str__(self):
        return f'{self.organization} — API {"on" if self.enabled else "off"}'

    @classmethod
    def is_enabled(cls, organization):
        if organization is None:
            return False
        return cls.objects.filter(organization=organization, enabled=True).exists()

    @classmethod
    def enabled_organizations(cls, queryset):
        """Narrow an Organization queryset to those with the API switched on."""
        return queryset.filter(api_access__enabled=True)


class Connection(models.Model):
    """A user's approval for one application to act in one organisation."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='api_connections'
    )
    application = models.ForeignKey(
        oauth2_settings.APPLICATION_MODEL, on_delete=models.CASCADE, related_name='api_connections'
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='api_connections'
    )
    scope = models.TextField(blank=True, help_text='Space-separated scopes of the latest approval.')
    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(default=timezone.now)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-approved_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'application', 'organization'],
                name='one_api_connection_per_user_application_organization',
            ),
        ]

    def __str__(self):
        return f'{self.application} for {self.user} in {self.organization}'

    @property
    def is_active(self):
        return self.revoked_at is None

    @property
    def scopes(self):
        return self.scope.split()

    @transaction.atomic
    def revoke(self):
        """End the connection: every code and token issued under it stops working."""
        from oauth2_provider.models import get_access_token_model, get_grant_model, get_refresh_token_model

        mine = {'api_credential__connection': self}
        for refresh_token in get_refresh_token_model().objects.filter(**mine):
            refresh_token.revoke()  # also removes the access token it was issued with
        get_access_token_model().objects.filter(**mine).delete()
        get_grant_model().objects.filter(**mine).delete()
        self.revoked_at = timezone.now()
        self.save(update_fields=['revoked_at'])


class ConnectionCredential(models.Model):
    """Ties one authorisation code, access token or refresh token to its connection."""

    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name='credentials')
    grant = models.OneToOneField(
        oauth2_settings.GRANT_MODEL, on_delete=models.CASCADE, null=True, blank=True,
        related_name='api_credential',
    )
    access_token = models.OneToOneField(
        oauth2_settings.ACCESS_TOKEN_MODEL, on_delete=models.CASCADE, null=True, blank=True,
        related_name='api_credential',
    )
    refresh_token = models.OneToOneField(
        oauth2_settings.REFRESH_TOKEN_MODEL, on_delete=models.CASCADE, null=True, blank=True,
        related_name='api_credential',
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(grant__isnull=False, access_token__isnull=True, refresh_token__isnull=True)
                    | models.Q(grant__isnull=True, access_token__isnull=False, refresh_token__isnull=True)
                    | models.Q(grant__isnull=True, access_token__isnull=True, refresh_token__isnull=False)
                ),
                name='api_credential_points_at_exactly_one_token',
            ),
        ]

    def __str__(self):
        return f'Credential #{self.pk} of connection #{self.connection_id}'
