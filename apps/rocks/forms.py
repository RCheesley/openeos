from django import forms
from django.contrib.auth.models import User

from .models import Rock, RockDependency
from apps.accounts.models import Team


class RockForm(forms.ModelForm):
    class Meta:
        model = Rock
        # team is excluded: always set to the user's active team in the view
        fields = ['title', 'description', 'owner', 'quarter', 'year', 'due_date', 'parent_rock']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'What is this Rock? Keep it concise.',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'What does "done" look like? Be specific and measurable.',
            }),
            'owner': forms.Select(attrs={'class': 'form-select'}),
            'quarter': forms.Select(attrs={'class': 'form-select'}),
            'year': forms.NumberInput(attrs={'class': 'form-control', 'min': 2020, 'max': 2099}),
            'due_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'parent_rock': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        if team:
            self.fields['owner'].queryset = User.objects.filter(
                profile__teams=team
            ).distinct().order_by('first_name', 'username')
            self.fields['parent_rock'].queryset = Rock.objects.filter(
                team=team
            ).order_by('-year', '-quarter', 'title')
        else:
            self.fields['owner'].queryset = User.objects.none()
            self.fields['parent_rock'].queryset = Rock.objects.none()
        self.fields['parent_rock'].required = False
        self.fields['parent_rock'].empty_label = '— None (top-level Rock) —'
        self.fields['description'].required = False

        if not self.instance.pk:
            self.fields['quarter'].initial = Rock.current_quarter()
            self.fields['year'].initial = Rock.current_year()
            q = Rock.current_quarter()
            y = Rock.current_year()
            self.fields['due_date'].initial = Rock.quarter_end_date(q, y)


class RockStatusForm(forms.Form):
    """Simple form to set a Rock's status from the dashboard or detail page."""
    status = forms.ChoiceField(choices=Rock.STATUS_CHOICES)
    next = forms.CharField(required=False, widget=forms.HiddenInput())


class RockDependencyForm(forms.ModelForm):
    class Meta:
        model = RockDependency
        fields = ['depends_on_rock', 'description']
        widgets = {
            'depends_on_rock': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Why does this Rock depend on the other? (optional)',
            }),
        }

    def __init__(self, *args, rock=None, **kwargs):
        super().__init__(*args, **kwargs)
        if rock:
            # Show only rocks from the same org, different team, same quarter/year
            self.fields['depends_on_rock'].queryset = (
                Rock.objects
                .filter(team__organization=rock.team.organization, quarter=rock.quarter, year=rock.year)
                .exclude(pk=rock.pk)
                .exclude(dependencies__rock=rock)   # exclude already-linked
                .select_related('team', 'owner')
                .order_by('team__name', 'title')
            )
            self.fields['depends_on_rock'].label_from_instance = (
                lambda r: f'{r.title} ({r.team.name} — {r.owner.get_full_name() or r.owner.username})'
            )
        self.fields['description'].required = False
