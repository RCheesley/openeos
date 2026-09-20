from django import forms
from .models import NotificationPreference


class NotificationPreferenceForm(forms.ModelForm):
    class Meta:
        model = NotificationPreference
        fields = ['overdue_todo_digest', 'meeting_reminders', 'rock_off_track_alerts']
        widgets = {
            'overdue_todo_digest': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'meeting_reminders': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'rock_off_track_alerts': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
