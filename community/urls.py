from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('admin/gallery', views.GalleryPhotoViewSet, basename='gallery')
router.register('admin/posts', views.PostAdminViewSet, basename='admin-post')
router.register('admin/comments', views.CommentAdminViewSet, basename='admin-comment')

urlpatterns = [
    # Public — no token required; this is the point of the community feature.
    # <str:> not <slug:>: the slug converter is ASCII-only and would 404 on
    # an Arabic or Vietnamese title.
    path('gallery/', views.public_gallery),
    path('community/posts/', views.public_feed),
    path('community/posts/<str:slug>/', views.public_post),
    path('community/posts/<str:slug>/like/', views.toggle_like),
    path('community/posts/<str:slug>/comments/', views.post_comments),
    path('', include(router.urls)),
]
