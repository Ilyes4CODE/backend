"""Keep shared caches out of the API."""

from django.utils.cache import add_never_cache_headers, patch_cache_control

# Everything below these prefixes is meant to be cached hard: static assets and
# uploaded media are content-addressed, so a given URL never changes.
CACHEABLE_PREFIXES = ('/static/', '/public-media/')


class NoStoreDynamicResponses:
    """Mark every dynamic response private and uncacheable.

    Django sends no Cache-Control at all on an ordinary DRF response, and the
    cache the host runs in front of the application then falls back to its own
    heuristics. It stored an authenticated GET of /api/admin/settings/ and
    served that copy to callers with no token at all — a 200 with the admin's
    payload where the view itself would have answered 401.

    The same store broke the dashboard: closing registration saved correctly,
    but the refetch straight afterwards was answered from the cache with the
    old value, so the switch appeared to snap back and nothing seemed to
    happen.

    Vary alone cannot fix this. The responses carried `Vary: Accept, origin`,
    which says nothing about Authorization, so one entry was shared by
    everybody.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if request.path.startswith(CACHEABLE_PREFIXES):
            return response

        # no-store is the part that matters: no-cache alone still permits a
        # shared cache to keep the body and revalidate, and this host does not
        # revalidate with the original Authorization header.
        add_never_cache_headers(response)
        patch_cache_control(response, no_store=True, private=True)
        return response
