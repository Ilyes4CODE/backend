"""Endpoints for the carousel and the community feed.

The public half answers to anyone — no token, no account. That is the whole
point of the feature, and it is also the reason everything here is written
defensively: counters move through F() expressions so two simultaneous likes
can't overwrite each other, likes are unique per visitor at the database level,
and comments are rate-limited per IP because there is no login to slow anyone
down.
"""

from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from organization.models import profile_for
from organization.permissions import IsClubLevel, scope_queryset_to_club

from .models import (
    GalleryPhoto,
    Post,
    PostComment,
    PostLike,
    PostMedia,
    fingerprint,
)
from .ranking import order_feed
from .serializers import (
    AdminCommentSerializer,
    AdminPostSerializer,
    CommentCreateSerializer,
    GalleryPhotoSerializer,
    PostMediaUploadSerializer,
    PublicCommentSerializer,
    PublicGalleryPhotoSerializer,
    PublicPostSerializer,
)


def client_ip(request) -> str:
    """The visitor's address, honouring one proxy hop.

    X-Forwarded-For is a client-controlled header, so the *first* entry is only
    trustworthy behind a proxy that rewrites it. It is what the club needs for
    moderation, not an authorisation input, so taking the leading entry and
    falling back to REMOTE_ADDR is the right trade here.
    """
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        first = forwarded.split(',')[0].strip()
        if first:
            return first
    return request.META.get('REMOTE_ADDR') or ''


def visitor_key(request) -> str:
    return fingerprint(client_ip(request), request.META.get('HTTP_USER_AGENT', ''))


def live_posts():
    """Posts a visitor is allowed to see: published and past their release
    time. A future published_at is a schedule, not a live post."""
    return (
        Post.objects
        .filter(status=Post.PUBLISHED, published_at__lte=timezone.now())
        .select_related('club', 'author', 'author__profile')
        .prefetch_related(Prefetch('media', queryset=PostMedia.objects.order_by('order', 'id')))
    )


# ── Public: carousel ─────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def public_gallery(request):
    photos = GalleryPhoto.objects.filter(active=True).select_related('club')
    if club := request.query_params.get('club'):
        photos = photos.filter(club_id=club)
    return Response(
        PublicGalleryPhotoSerializer(photos, many=True, context={'request': request}).data
    )


# ── Public: feed ─────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def public_feed(request):
    """The ranked feed. Pinned first, then the score, then id — see ranking.py
    for why the id matters."""
    posts = live_posts()
    if club := request.query_params.get('club'):
        posts = posts.filter(club_id=club)
    if kind := request.query_params.get('kind'):
        posts = posts.filter(kind=kind)
    posts = order_feed(posts)

    try:
        page = max(1, int(request.query_params.get('page', 1)))
    except ValueError:
        page = 1
    size = min(50, max(1, int(request.query_params.get('page_size', 10) or 10)))
    start = (page - 1) * size

    total = posts.count()
    window = list(posts[start:start + size])

    # One query for the whole page rather than one per card.
    visitor = visitor_key(request)
    liked_ids = set(
        PostLike.objects
        .filter(visitor=visitor, post__in=window)
        .values_list('post_id', flat=True)
    )

    data = PublicPostSerializer(
        window, many=True,
        context={'request': request, 'visitor': visitor, 'liked_ids': liked_ids},
    ).data
    return Response({
        'count': total,
        'page': page,
        'page_size': size,
        'has_next': start + size < total,
        'results': data,
    })


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def public_post(request, slug):
    post = get_object_or_404(live_posts(), slug=slug)
    visitor = visitor_key(request)
    return Response(PublicPostSerializer(
        post, context={'request': request, 'visitor': visitor},
    ).data)


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def toggle_like(request, slug):
    """Like or unlike, with no account. Idempotent per visitor: pressing it
    twice returns to the starting state rather than counting twice."""
    post = get_object_or_404(live_posts(), slug=slug)
    visitor = visitor_key(request)

    # The insert gets its own savepoint: a unique-constraint violation marks the
    # surrounding transaction unusable, and the unlike path still has work to do.
    try:
        with transaction.atomic():
            PostLike.objects.create(
                post=post, visitor=visitor, ip_address=client_ip(request) or None)
        first_time = True
    except IntegrityError:
        first_time = False  # they had already liked it

    if first_time:
        # F() rather than post.like_count + 1: two visitors liking at the same
        # moment would otherwise each write the same value.
        Post.objects.filter(pk=post.pk).update(like_count=F('like_count') + 1)
        liked = True
    else:
        deleted, _ = PostLike.objects.filter(post=post, visitor=visitor).delete()
        if deleted:
            Post.objects.filter(pk=post.pk, like_count__gt=0).update(
                like_count=F('like_count') - 1)
        liked = False

    post.refresh_from_db(fields=['like_count', 'comment_count'])
    post.refresh_rank()
    return Response({'liked': liked, 'like_count': post.like_count})


@api_view(['GET', 'POST'])
@permission_classes([permissions.AllowAny])
def post_comments(request, slug):
    post = get_object_or_404(live_posts(), slug=slug)

    if request.method == 'GET':
        rows = post.comments.filter(status=PostComment.PUBLISHED)
        return Response(PublicCommentSerializer(rows, many=True).data)

    if not post.comments_enabled:
        return Response(
            {'detail': 'Comments are closed on this post.', 'code': 'COMMENTS_CLOSED'},
            status=status.HTTP_403_FORBIDDEN,
        )

    ip = client_ip(request)
    since = timezone.now() - timedelta(seconds=settings.COMMUNITY_COMMENT_WINDOW_SECONDS)
    recent = PostComment.objects.filter(ip_address=ip, created_at__gte=since).count()
    if ip and recent >= settings.COMMUNITY_COMMENT_MAX_PER_WINDOW:
        return Response(
            {'detail': 'Too many comments just now — please wait a moment.',
             'code': 'RATE_LIMITED'},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    serializer = CommentCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    comment = serializer.save(
        post=post,
        ip_address=ip or None,
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:300],
        visitor=visitor_key(request),
    )
    Post.objects.filter(pk=post.pk).update(comment_count=F('comment_count') + 1)
    post.refresh_from_db(fields=['like_count', 'comment_count'])
    post.refresh_rank()

    return Response(
        {'comment': PublicCommentSerializer(comment).data, 'comment_count': post.comment_count},
        status=status.HTTP_201_CREATED,
    )


# ── Admin: gallery ───────────────────────────────────────────────────────────

class GalleryPhotoViewSet(viewsets.ModelViewSet):
    """Carousel photos. A club owner curates their own club's slides."""

    # Club-wide publishing: the national admin and presidents, not branch managers.
    permission_classes = [IsClubLevel]
    serializer_class = GalleryPhotoSerializer
    pagination_class = None

    def get_queryset(self):
        qs = GalleryPhoto.objects.select_related('club')
        profile = profile_for(self.request.user)
        if profile and not profile.is_super_admin:
            # Their own slides plus the platform-wide ones, which they can see
            # but not edit (guarded in perform_update/destroy).
            return qs.filter(club_id=profile.club_id)
        return qs

    def perform_create(self, serializer):
        profile = profile_for(self.request.user)
        if profile and not profile.is_super_admin:
            serializer.save(club_id=profile.club_id)
        else:
            serializer.save()


# ── Admin: posts ─────────────────────────────────────────────────────────────

class PostAdminViewSet(viewsets.ModelViewSet):
    # Club-wide publishing: the national admin and presidents, not branch managers.
    permission_classes = [IsClubLevel]
    serializer_class = AdminPostSerializer

    def get_queryset(self):
        qs = (
            Post.objects
            .select_related('club', 'author', 'author__profile')
            .prefetch_related('media')
        )
        if status_filter := self.request.query_params.get('status'):
            qs = qs.filter(status=status_filter)
        if kind := self.request.query_params.get('kind'):
            qs = qs.filter(kind=kind)
        if search := self.request.query_params.get('search'):
            qs = qs.filter(title_ar__icontains=search) | qs.filter(title_en__icontains=search)
        profile = profile_for(self.request.user)
        if profile and not profile.is_super_admin:
            qs = scope_queryset_to_club(qs, self.request.user)
        return qs.order_by('-pinned', '-created_at', '-id')

    def perform_create(self, serializer):
        profile = profile_for(self.request.user)
        if profile and not profile.is_super_admin:
            # A club owner always posts as their own club, whatever they sent.
            serializer.save(club_id=profile.club_id, author=self.request.user)
        else:
            serializer.save(author=self.request.user)

    @action(detail=True, methods=['post'], url_path='media')
    def add_media(self, request, pk=None):
        post = self.get_object()
        serializer = PostMediaUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(post=post)
        return Response(
            AdminPostSerializer(post, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['delete'], url_path=r'media/(?P<media_id>\d+)')
    def remove_media(self, request, pk=None, media_id=None):
        post = self.get_object()
        deleted, _ = PostMedia.objects.filter(post=post, pk=media_id).delete()
        if not deleted:
            return Response({'detail': 'No such attachment.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(AdminPostSerializer(post, context={'request': request}).data)

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        """Take it live. Idempotent — republishing an already-live post leaves
        published_at alone so it doesn't jump back to the top of the feed."""
        post = self.get_object()
        post.status = Post.PUBLISHED
        if post.published_at is None:
            post.published_at = timezone.now()
        post.save()
        return Response(AdminPostSerializer(post, context={'request': request}).data)

    @action(detail=True, methods=['post'])
    def unpublish(self, request, pk=None):
        post = self.get_object()
        post.status = Post.DRAFT
        post.save()
        return Response(AdminPostSerializer(post, context={'request': request}).data)


class CommentAdminViewSet(viewsets.ReadOnlyModelViewSet):
    """Moderation. Read, hide, show, delete — never edit what someone wrote."""

    # Club-wide publishing: the national admin and presidents, not branch managers.
    permission_classes = [IsClubLevel]
    serializer_class = AdminCommentSerializer

    def get_queryset(self):
        qs = PostComment.objects.select_related('post', 'post__club')
        if post_id := self.request.query_params.get('post'):
            qs = qs.filter(post_id=post_id)
        if state := self.request.query_params.get('status'):
            qs = qs.filter(status=state)
        profile = profile_for(self.request.user)
        if profile and not profile.is_super_admin:
            qs = scope_queryset_to_club(qs, self.request.user, field='post__club')
        return qs.order_by('-created_at', '-id')

    @action(detail=True, methods=['post'])
    def hide(self, request, pk=None):
        return self._set_status(self.get_object(), PostComment.HIDDEN)

    @action(detail=True, methods=['post'])
    def show(self, request, pk=None):
        return self._set_status(self.get_object(), PostComment.PUBLISHED)

    def _set_status(self, comment, new_status):
        if comment.status != new_status:
            comment.status = new_status
            comment.save(update_fields=['status'])
            _recount_comments(comment.post)
        return Response(AdminCommentSerializer(comment).data)

    def destroy(self, request, *args, **kwargs):
        comment = self.get_object()
        post = comment.post
        comment.delete()
        _recount_comments(post)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['delete'], url_path=r'(?P<pk>\d+)/remove')
    def remove(self, request, pk=None):
        return self.destroy(request)


def _recount_comments(post):
    """Recount from the table rather than nudging the counter.

    Hiding, showing and deleting all move the visible total in different
    directions; counting once is simpler than getting three deltas right, and
    it self-heals a counter that has already drifted.
    """
    total = post.comments.filter(status=PostComment.PUBLISHED).count()
    Post.objects.filter(pk=post.pk).update(comment_count=total)
    post.comment_count = total
    post.refresh_rank()
