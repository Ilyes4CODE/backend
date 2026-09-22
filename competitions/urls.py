from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('admin/competitions', views.CompetitionViewSet, basename='admin-competitions')
router.register('admin/participants', views.ParticipantViewSet, basename='admin-participants')
router.register('admin/matches', views.MatchViewSet, basename='admin-matches')
router.register('admin/performances', views.PerformanceViewSet, basename='admin-performances')
router.register('admin/judge-scores', views.JudgeScoreViewSet, basename='admin-judge-scores')

urlpatterns = [
    path('competitions/reference/', views.reference_data, name='competition-reference'),
    path('competitions/<int:pk>/display/', views.display_state, name='competition-display'),
    path('', include(router.urls)),
]
