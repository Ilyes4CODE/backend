"""Deployment settings that are only ever exercised on the live site.

Everything checked here was broken in production while every local page looked
perfect, because `runserver` papers over all of it.
"""

from django.conf import settings
from django.test import TestCase, override_settings


class StaticFilesAreServableWithDebugOff(TestCase):
    """The Django admin loaded as unstyled HTML on the live site.

    Django serves /static/ only while DEBUG is on, and a cPanel Python app
    routes every URL to Passenger, so nothing else was going to answer for it.
    WhiteNoise does, from STATIC_ROOT.
    """

    def test_whitenoise_is_installed(self):
        self.assertIn('whitenoise.middleware.WhiteNoiseMiddleware', settings.MIDDLEWARE)

    def test_whitenoise_sits_directly_after_the_security_middleware(self):
        """Its documented position. Above it, responses skip it entirely;
        below the others, every static file is dragged through session lookups
        and CORS handling it has no use for."""
        middleware = list(settings.MIDDLEWARE)
        security = middleware.index('django.middleware.security.SecurityMiddleware')
        whitenoise = middleware.index('whitenoise.middleware.WhiteNoiseMiddleware')
        self.assertEqual(whitenoise, security + 1)

    def test_collectstatic_has_somewhere_to_put_things(self):
        self.assertTrue(settings.STATIC_ROOT)

    def test_static_storage_does_not_hard_fail_on_a_missing_reference(self):
        """Not the Manifest backend: it refuses to serve anything at all if one
        stylesheet points at a file that was never shipped."""
        backend = settings.STORAGES['staticfiles']['BACKEND']
        self.assertNotIn('Manifest', backend)


class DynamicResponsesAreNotCacheable(TestCase):
    """A cache in front of the app served an admin payload to anonymous callers.

    /api/admin/settings/ answered 200 with the settings to a request carrying
    no token at all, because the host's cache had stored an authenticated GET
    of that URL and matched the next caller on the URL alone. The view was
    never reached; with a cache-busting query string the same request got the
    401 it should have.

    The same store is why closing registration looked broken in the dashboard:
    the PATCH saved, and the refetch immediately after was answered from the
    cache with the old value.
    """

    def test_an_api_response_forbids_storage(self):
        response = self.client.get('/api/settings/')
        self.assertEqual(response.status_code, 200)
        directives = response['Cache-Control']
        # no-cache alone is not enough: a shared cache may still keep the body
        # and revalidate, and it does not revalidate with the caller's token.
        self.assertIn('no-store', directives)
        self.assertIn('private', directives)

    def test_a_rejected_request_is_not_cacheable_either(self):
        """Otherwise the 401 itself gets stored and handed to the real admin."""
        response = self.client.get('/api/admin/settings/')
        self.assertEqual(response.status_code, 401)
        self.assertIn('no-store', response['Cache-Control'])

    def test_static_files_keep_their_long_cache(self):
        """Hashed assets must stay cacheable; the middleware skips them."""
        from config.middleware import CACHEABLE_PREFIXES

        self.assertIn('/static/', CACHEABLE_PREFIXES)
        self.assertIn('/public-media/', CACHEABLE_PREFIXES)

    def test_public_media_is_still_immutable(self):
        with override_settings(PUBLIC_MEDIA_ROOT=self.media_root):
            response = self.client.get('/public-media/gallery/photo.gif')
        self.assertEqual(response.status_code, 200)
        self.assertIn('max-age=31536000', response['Cache-Control'])
        self.assertNotIn('no-store', response['Cache-Control'])

    def setUp(self):
        import base64
        import os
        import shutil
        import tempfile

        self.media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        os.makedirs(os.path.join(self.media_root, 'gallery'))
        with open(os.path.join(self.media_root, 'gallery', 'photo.gif'), 'wb') as handle:
            handle.write(base64.b64decode(
                'R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'))
