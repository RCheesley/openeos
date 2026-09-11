from django import forms
from django.contrib.auth.models import User
from django.db.models import Q

from apps.accounts.models import Team
from .models import Scorecard, ScorecardMetric, ScorecardEntry


class ScorecardForm(forms.ModelForm):
    class Meta:
        model = Scorecard
        fields = ['name', 'description', 'team', 'is_active']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization:
            self.fields['team'].queryset = Team.objects.filter(organization=organization).order_by('name')


class ScorecardMetricForm(forms.ModelForm):
    class Meta:
        model = ScorecardMetric
        fields = ['name', 'owner', 'metric_type', 'goal_value', 'goal_direction', 'frequency', 'order', 'is_active']
        widgets = {
            'goal_value': forms.NumberInput(attrs={'step': 'any'}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization:
            self.fields['owner'].queryset = (
                User.objects
                .filter(Q(profile__organization=organization) | Q(is_superuser=True))
                .distinct()
                .order_by('first_name', 'last_name', 'username')
            )
        self.fields['order'].initial = 0
        self.fields['is_active'].initial = True


class ScorecardEntryForm(forms.ModelForm):
    class Meta:
        model = ScorecardEntry
        fields = ['value', 'notes']
        widgets = {
            'value': forms.NumberInput(attrs={'step': 'any', 'class': 'form-control form-control-sm'}),
            'notes': forms.TextInput(attrs={'class': 'form-control form-control-sm',
                                           'placeholder': 'Optional note'}),
        }
