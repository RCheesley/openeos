from django import forms
from django.contrib.auth.models import User

from .members import (
    ALL_KINDS, KIND_METRICS, KIND_ROCKS, KIND_SEATS, KIND_TODOS, REQUIRED_KINDS,
    is_last_admin, open_issues_raised, owned_records, teams_missing,
)
from .models import Membership
from .terminology import terms_for


def display_name(user):
    return user.get_full_name() or user.username


class MemberChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, user):
        return display_name(user)


class MemberRoleForm(forms.Form):
    role = forms.ChoiceField(
        choices=Membership.ROLE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def __init__(self, *args, membership, **kwargs):
        super().__init__(*args, **kwargs)
        self.membership = membership
        self.fields['role'].initial = membership.role

    def clean_role(self):
        role = self.cleaned_data['role']
        if role != Membership.ROLE_ADMIN and is_last_admin(self.membership):
            raise forms.ValidationError(
                f'{display_name(self.membership.user)} is the only admin of '
                f'{self.membership.organization.name}. Make someone else an admin first.'
            )
        return role


class HandOverForm(forms.Form):
    """Choose who takes over a member's live records.

    With ``removing`` every record that must have an owner moves, and seats
    either move too or are left vacant. Without it the admin picks which kinds
    of record to move.
    """

    new_owner = MemberChoiceField(
        queryset=User.objects.none(), required=False, empty_label='Choose a member',
        label='New owner', widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def __init__(self, *args, membership, removing, **kwargs):
        super().__init__(*args, **kwargs)
        self.membership = membership
        self.removing = removing
        user, org = membership.user, membership.organization
        terms = terms_for(org)
        labels = {
            KIND_ROCKS: f'Open {terms.rocks}',
            KIND_TODOS: f'Open {terms.todos}',
            KIND_METRICS: 'Active metrics',
            KIND_SEATS: f'{terms.seats} on the {terms.accountability_chart}',
        }
        records = owned_records(user, org)
        self.counts = {kind: records[kind].count() for kind in ALL_KINDS}
        # (kind, label, count) for the kinds the member owns something of.
        self.owned = [
            (kind, labels[kind], self.counts[kind]) for kind in ALL_KINDS if self.counts[kind]
        ]
        self.issues_raised = open_issues_raised(user, org).count()
        self.fields['new_owner'].queryset = (
            User.objects
            .filter(memberships__organization=org)
            .exclude(pk=user.pk)
            .order_by('first_name', 'last_name', 'username')
        )
        if removing:
            if self.counts[KIND_SEATS]:
                self.fields['vacate_seats'] = forms.BooleanField(
                    required=False,
                    label=f'Leave their {terms.seats} on the {terms.accountability_chart} vacant',
                    widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
                )
        else:
            self.fields['kinds'] = forms.MultipleChoiceField(
                choices=[(kind, f'{label} ({count})') for kind, label, count in self.owned],
                initial=[kind for kind, _, _ in self.owned],
                label='Records to hand over',
                widget=forms.CheckboxSelectMultiple(),
                error_messages={'required': 'Choose at least one kind of record to hand over.'},
            )

    @property
    def needs_owner(self):
        """Whether the page has to offer the new owner field at all."""
        return bool(self.owned)

    def selected_kinds(self):
        """The kinds that move to the new owner, from the cleaned data."""
        if not self.removing:
            return list(self.cleaned_data.get('kinds', []))
        kinds = [kind for kind in REQUIRED_KINDS if self.counts[kind]]
        if self.counts[KIND_SEATS] and not self.cleaned_data.get('vacate_seats'):
            kinds.append(KIND_SEATS)
        return kinds

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        kinds = self.selected_kinds()
        new_owner = cleaned.get('new_owner')
        if kinds and new_owner is None:
            self.add_error('new_owner', 'Choose who takes over these records.')
            return cleaned
        if new_owner is not None:
            user, org = self.membership.user, self.membership.organization
            missing = [team.name for team in teams_missing(new_owner, user, org, kinds)]
            if missing:
                self.add_error(
                    'new_owner',
                    f'{display_name(new_owner)} is not in {", ".join(missing)}. '
                    f'Add them to the team first, or choose someone who is in it.',
                )
        return cleaned
