from django.urls import path
from . import views

app_name = 'todos'

urlpatterns = [
    path('', views.ToDoListView.as_view(), name='list'),
    path('new/', views.ToDoCreateView.as_view(), name='create'),
    path('<int:pk>/edit/', views.ToDoUpdateView.as_view(), name='update'),
    path('<int:pk>/delete/', views.ToDoDeleteView.as_view(), name='delete'),
    path('<int:pk>/complete/', views.ToDoCompleteView.as_view(), name='complete'),
    path('<int:pk>/escalate/', views.ToDoEscalateView.as_view(), name='escalate'),
]
