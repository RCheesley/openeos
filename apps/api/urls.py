from django.urls import path, re_path
from drf_spectacular.views import SpectacularJSONAPIView

from . import views
from .docs import DocsSignInReturnView, DocsView

app_name = 'api'

urlpatterns = [
    path('openapi.json', SpectacularJSONAPIView.as_view(), name='schema'),
    path('docs', DocsView.as_view(url_name='api:schema'), name='docs'),
    # Swagger UI sends sign-in back to ./oauth2-redirect.html, beside the docs page.
    path('oauth2-redirect.html', DocsSignInReturnView.as_view(), name='docs-sign-in-return'),

    path('organisation', views.OrganisationView.as_view(), name='organisation'),
    path('me', views.MeView.as_view(), name='me'),
    path('teams', views.TeamListView.as_view(), name='team-list'),
    path('teams/<int:pk>', views.TeamDetailView.as_view(), name='team-detail'),
    path('priorities', views.PriorityListView.as_view(), name='priority-list'),
    path('priorities/<int:pk>', views.PriorityDetailView.as_view(), name='priority-detail'),
    path('priorities/<int:pk>/steps', views.StepListView.as_view(), name='priority-steps'),
    path('priorities/<int:pk>/check-ins', views.CheckInListView.as_view(), name='priority-check-ins'),
    path('actions', views.ActionListView.as_view(), name='action-list'),
    path('actions/<int:pk>', views.ActionDetailView.as_view(), name='action-detail'),
    path('blockers', views.BlockerListView.as_view(), name='blocker-list'),
    path('blockers/<int:pk>', views.BlockerDetailView.as_view(), name='blocker-detail'),
    path('metrics-boards', views.MetricsBoardListView.as_view(), name='metrics-board-list'),
    path('metrics-boards/<int:pk>', views.MetricsBoardDetailView.as_view(), name='metrics-board-detail'),
    path('metrics-boards/<int:pk>/metrics', views.MetricListView.as_view(), name='metrics-board-metrics'),
    path(
        'metrics-boards/<int:pk>/metrics/<int:metric_id>/entries',
        views.EntryListView.as_view(), name='metric-entries',
    ),
    path('meetings', views.MeetingListView.as_view(), name='meeting-list'),
    path('meetings/<int:pk>', views.MeetingDetailView.as_view(), name='meeting-detail'),
    path('vision-board', views.VisionBoardView.as_view(), name='vision-board'),
    path('org-chart', views.OrgChartView.as_view(), name='org-chart'),

    re_path(r'^.*$', views.NotFoundView.as_view()),
]
