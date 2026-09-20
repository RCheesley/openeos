from django.urls import path
from . import views

app_name = 'notifications'

urlpatterns = [
    path('preferences/', views.NotificationPreferenceUpdateView.as_view(), name='preferences'),
]
