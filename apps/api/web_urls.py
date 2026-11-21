from django.urls import path

from . import web_views

app_name = 'api_web'

urlpatterns = [
    path('org/settings/api/', web_views.ApiAccessView.as_view(), name='access'),
    path('profile/connections/', web_views.ConnectionListView.as_view(), name='connections'),
    path('profile/connections/<int:pk>/revoke/', web_views.ConnectionRevokeView.as_view(), name='revoke'),
]
