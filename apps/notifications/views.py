from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import UpdateView

from .forms import NotificationPreferenceForm
from .models import NotificationPreference


class NotificationPreferenceUpdateView(LoginRequiredMixin, UpdateView):
    form_class = NotificationPreferenceForm
    template_name = 'notifications/preferences.html'
    success_url = reverse_lazy('notifications:preferences')

    def get_object(self, queryset=None):
        return NotificationPreference.for_user(self.request.user)

    def form_valid(self, form):
        messages.success(self.request, 'Notification preferences updated.')
        return super().form_valid(form)
