from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('admin/wilayas', views.WilayaViewSet, basename='admin-wilayas')
router.register('admin/clubs', views.ClubViewSet, basename='admin-clubs')
router.register('admin/centers', views.CenterViewSet, basename='admin-centers')
router.register('admin/users', views.AdminUserViewSet, basename='admin-users')
router.register('admin/activity', views.ActivityLogViewSet, basename='activity')
router.register('admin/groups', views.TrainingGroupViewSet, basename='admin-groups')
router.register('admin/sessions', views.WeeklySessionViewSet, basename='admin-sessions')

urlpatterns = [
    path('admin/timetable/', views.weekly_timetable, name='admin-timetable'),
    path('directory/', views.public_directory, name='public-directory'),
    path('', include(router.urls)),
]
