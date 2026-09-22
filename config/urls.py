from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('accounts.urls')),
    path('api/', include('organization.urls')),
    path('api/', include('competitions.urls')),
    path('api/', include('registrations.urls')),
    path('api/', include('community.urls')),
]

# Carousel and post media are public by design, so they are served directly.
# Only PUBLIC_MEDIA_ROOT is exposed — registration documents live under
# MEDIA_ROOT and still leave only through their authenticated view.
urlpatterns += static(settings.PUBLIC_MEDIA_URL, document_root=settings.PUBLIC_MEDIA_ROOT)
