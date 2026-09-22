"""Deployment settings that are only ever exercised on the live site.

Everything checked here was broken in production while every local page looked
perfect, because `runserver` papers over all of it.
"""

from django.conf import settings
from django.test import TestCase


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
