from django.urls import path
from . import views

app_name = 'accountability'

urlpatterns = [
    path('', views.ChartView.as_view(), name='chart'),
    path('nodes/add/', views.NodeCreateView.as_view(), name='node_add'),
    path('nodes/<int:pk>/edit/', views.NodeUpdateView.as_view(), name='node_edit'),
    path('nodes/<int:pk>/delete/', views.NodeDeleteView.as_view(), name='node_delete'),
    path('nodes/<int:pk>/move/', views.NodeMoveView.as_view(), name='node_move'),
    path('nodes/<int:pk>/roles/add/', views.RoleCreateView.as_view(), name='role_add'),
    path('roles/<int:pk>/edit/', views.RoleUpdateView.as_view(), name='role_edit'),
    path('roles/<int:pk>/delete/', views.RoleDeleteView.as_view(), name='role_delete'),
]
