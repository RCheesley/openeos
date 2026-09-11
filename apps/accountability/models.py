from django.db import models
from django.contrib.auth.models import User
from django.urls import reverse

from apps.accounts.models import Organization


class AccountabilityNode(models.Model):
    TYPE_SEAT = 'seat'
    TYPE_DEPARTMENT = 'department'
    TYPE_CHOICES = [
        (TYPE_SEAT, 'Seat'),
        (TYPE_DEPARTMENT, 'Department'),
    ]

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='chart_nodes'
    )
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE,
        null=True, blank=True, related_name='children'
    )
    name = models.CharField(max_length=100)
    node_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_SEAT)
    owner = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='chart_seats'
    )
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return f'{self.name} ({self.organization.name})'

    def get_absolute_url(self):
        return reverse('accountability:chart')

    @property
    def is_vacant(self):
        return self.owner is None


class AccountabilityRole(models.Model):
    node = models.ForeignKey(
        AccountabilityNode, on_delete=models.CASCADE, related_name='roles'
    )
    description = models.CharField(max_length=200)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order', 'description']

    def __str__(self):
        return self.description
