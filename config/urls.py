import re

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('accounts.urls')),
    path('api/', include('organization.urls')),
    path('api/', include('competitions.urls')),
    path('api/', include('registrations.urls')),
    path('api/', include('community.urls')),
]


def public_media(request, path):
    """Serve carousel images and post media.

    Deliberately not `django.conf.urls.static.static()`: that helper returns an
    empty list whenever DEBUG is off, so on the live site every image 404s while
    everything looks correct locally.

    Only PUBLIC_MEDIA_ROOT is reachable here. Registration documents live under
    MEDIA_ROOT and still leave only through their authenticated view.

    Uploaded names are content hashes, so a file at a given URL never changes
    and the browser can keep it for a year.
    """
    response = serve(request, path, document_root=settings.PUBLIC_MEDIA_ROOT)
    response['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response


urlpatterns += [
    re_path(
        r'^%s(?P<path>.*)$' % re.escape(settings.PUBLIC_MEDIA_URL.lstrip('/')),
        public_media,
    ),
]
