from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from apps.accounts.views import HealthzView, HomeView
from apps.accounts.views_password import PasswordChangeView, PasswordResetConfirmView

urlpatterns = [
    path('healthz/', HealthzView.as_view(), name='healthz'),
    path('admin/', admin.site.urls),
    # Ahead of Django's own routes of the same name, so password changes are audited.
    path('accounts/password_change/', PasswordChangeView.as_view(), name='password_change'),
    path(
        'accounts/reset/<uidb64>/<token>/', PasswordResetConfirmView.as_view(),
        name='password_reset_confirm',
    ),
    path('accounts/', include('django.contrib.auth.urls')),
    path('', include('apps.accounts.urls', namespace='accounts')),
    path('', include('apps.audit.urls')),
    path('rocks/', include('apps.rocks.urls', namespace='rocks')),
    path('issues/', include('apps.issues.urls', namespace='issues')),
    path('todos/', include('apps.todos.urls', namespace='todos')),
    path('scorecards/', include('apps.scorecards.urls', namespace='scorecards')),
    path('vision/', include('apps.vision.urls', namespace='vision')),
    path('accountability/', include('apps.accountability.urls', namespace='accountability')),
    path('meetings/', include('apps.meetings.urls', namespace='meetings')),
    path('notifications/', include('apps.notifications.urls', namespace='notifications')),
    path('', HomeView.as_view(), name='home'),
]

# Appended last so apps.accounts' permission-checked /media/avatars/ view wins
# over the development file server; only organisation logos are served openly.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
