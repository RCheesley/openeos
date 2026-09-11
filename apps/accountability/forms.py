from django import forms
from django.contrib.auth.models import User
from django.db.models import Q

from .models import AccountabilityNode, AccountabilityRole


class NodeForm(forms.ModelForm):
    class Meta:
        model = AccountabilityNode
        fields = ['name', 'node_type', 'owner', 'order']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Visionary, Marketing Lead, Operations Manager',
            }),
            'node_type': forms.Select(attrs={'class': 'form-select'}),
            'owner': forms.Select(attrs={'class': 'form-select'}),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
        }

    def __init__(self, *args, org=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['owner'].required = False
        self.fields['owner'].empty_label = '— Vacant —'
        if org:
            self.fields['owner'].queryset = (
                User.objects
                .filter(Q(profile__organization=org) | Q(is_superuser=True))
                .distinct()
                .order_by('first_name', 'last_name', 'username')
            )


class RoleForm(forms.ModelForm):
    class Meta:
        model = AccountabilityRole
        fields = ['description', 'order']
        widgets = {
            'description': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Own the P&L, Drive revenue, Hire and fire the team',
            }),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
        }
