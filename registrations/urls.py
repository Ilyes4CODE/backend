from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('admin/required-documents', views.RequiredDocumentAdminViewSet, basename='admin-required-documents')
router.register('admin/registrations', views.RegistrationAdminViewSet, basename='admin-registrations')

urlpatterns = [
    path('settings/', views.public_settings, name='public-settings'),
    path('required-documents/', views.public_required_documents, name='public-required-documents'),
    path('registrations/', views.RegistrationCreateView.as_view(), name='registration-create'),
    path('registrations/<str:reference>/', views.RegistrationPublicDetailView.as_view(), name='registration-detail'),
    path('registrations/<str:reference>/pdf/', views.RegistrationPdfView.as_view(), name='registration-pdf'),
    path('admin/stats/', views.admin_stats, name='admin-stats'),
    path('admin/settings/', views.AdminSettingsView.as_view(), name='admin-settings'),
    path('admin/documents/<int:pk>/download/', views.DocumentDownloadView.as_view(), name='admin-document-download'),
    path('admin/registrations/<int:pk>/badge/', views.BadgeView.as_view(), name='admin-registration-badge'),
    path('admin/badges/', views.BadgeSheetView.as_view(), name='admin-badge-sheet'),
    path('admin/registrations-print/', views.RosterPrintView.as_view(), name='admin-roster-print'),
    path('', include(router.urls)),
]
