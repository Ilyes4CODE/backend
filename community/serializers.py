"""Serializers for the carousel and the community feed.

Two audiences, deliberately separated. The `Public*` classes are what an
anonymous visitor can read and write, and they expose nothing a visitor has no
business seeing — no draft, no IP address, no author account. The `Admin*`
classes are the editing surface behind the dashboard login.
"""

from django.conf import settings
from rest_framework import serializers

from .models import (
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    GalleryPhoto,
    Post,
    PostComment,
    PostLike,
    PostMedia,
)


def _absolute(request, file_field) -> str:
    """A URL the browser can actually fetch.

    Community media is served from its own root, so the relative path a
    FileField hands back is not enough for a frontend on another origin.
    """
    if not file_field:
        return ''
    url = file_field.url
    return request.build_absolute_uri(url) if request else url


def validate_media_size(uploaded, kind: str):
    limit = (
        settings.COMMUNITY_VIDEO_MAX_BYTES if kind == PostMedia.VIDEO
        else settings.COMMUNITY_IMAGE_MAX_BYTES
    )
    if uploaded.size > limit:
        raise serializers.ValidationError(
            f'That file is {uploaded.size // (1024 * 1024)} MB; the limit is '
            f'{limit // (1024 * 1024)} MB.'
        )


class OptionalBooleanField(serializers.BooleanField):
    """A boolean that means "unchanged" when it is simply absent.

    DRF assumes a missing boolean in HTML/multipart input is an *unchecked
    checkbox* and substitutes False. A photo uploaded as multipart without an
    explicit `active` therefore arrives inactive and never reaches the
    carousel. Treating absent as "not supplied" restores the model default.
    """

    def get_value(self, dictionary):
        if self.field_name not in dictionary:
            return serializers.empty
        return super().get_value(dictionary)


def kind_from_name(filename: str) -> str:
    suffix = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return PostMedia.VIDEO if suffix in VIDEO_EXTENSIONS else PostMedia.IMAGE


# ── Gallery ──────────────────────────────────────────────────────────────────

class GalleryPhotoSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    club_name = serializers.CharField(source='club.name_en', read_only=True, default='')
    active = OptionalBooleanField(required=False, default=True)

    class Meta:
        model = GalleryPhoto
        fields = [
            'id', 'club', 'club_name', 'image', 'image_url',
            'caption_ar', 'caption_en', 'caption_vi', 'order', 'active', 'created_at',
        ]
        extra_kwargs = {'image': {'write_only': True}}

    def get_image_url(self, obj) -> str:
        return _absolute(self.context.get('request'), obj.image)

    def validate_image(self, value):
        validate_media_size(value, PostMedia.IMAGE)
        return value


class PublicGalleryPhotoSerializer(serializers.ModelSerializer):
    """What the carousel needs and nothing more."""

    image_url = serializers.SerializerMethodField()

    class Meta:
        model = GalleryPhoto
        fields = ['id', 'image_url', 'caption_ar', 'caption_en', 'caption_vi']

    def get_image_url(self, obj) -> str:
        return _absolute(self.context.get('request'), obj.image)


# ── Post media ───────────────────────────────────────────────────────────────

class PostMediaSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    poster_url = serializers.SerializerMethodField()

    class Meta:
        model = PostMedia
        fields = ['id', 'kind', 'url', 'poster_url', 'alt_text', 'order']

    def get_url(self, obj) -> str:
        return _absolute(self.context.get('request'), obj.file)

    def get_poster_url(self, obj) -> str:
        return _absolute(self.context.get('request'), obj.poster)


class PostMediaUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostMedia
        fields = ['id', 'file', 'poster', 'alt_text', 'order']

    def validate(self, attrs):
        uploaded = attrs.get('file')
        if uploaded is not None:
            kind = kind_from_name(uploaded.name)
            validate_media_size(uploaded, kind)
            attrs['kind'] = kind
        poster = attrs.get('poster')
        if poster is not None:
            validate_media_size(poster, PostMedia.IMAGE)
        return attrs


# ── Comments ─────────────────────────────────────────────────────────────────

class PublicCommentSerializer(serializers.ModelSerializer):
    """Read side. The IP is recorded but never published."""

    class Meta:
        model = PostComment
        fields = ['id', 'author_name', 'body', 'created_at']


class CommentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostComment
        fields = ['author_name', 'body']

    def validate_author_name(self, value):
        name = ' '.join(value.split())
        if len(name) < 2:
            raise serializers.ValidationError('Please give a name of at least 2 characters.')
        return name

    def validate_body(self, value):
        body = value.strip()
        if len(body) < 2:
            raise serializers.ValidationError('The comment is empty.')
        return body


class AdminCommentSerializer(serializers.ModelSerializer):
    """Moderation view — this is the one that shows the IP."""

    post_title = serializers.CharField(source='post.display_title', read_only=True)
    post_slug = serializers.CharField(source='post.slug', read_only=True)

    class Meta:
        model = PostComment
        fields = [
            'id', 'post', 'post_title', 'post_slug', 'author_name', 'body',
            'status', 'ip_address', 'user_agent', 'created_at',
        ]
        read_only_fields = [
            'post', 'author_name', 'body', 'ip_address', 'user_agent', 'created_at',
        ]


# ── Posts ────────────────────────────────────────────────────────────────────

class PublicPostSerializer(serializers.ModelSerializer):
    media = PostMediaSerializer(many=True, read_only=True)
    club_name = serializers.CharField(source='club.name_en', read_only=True, default='')
    club_name_ar = serializers.CharField(source='club.name_ar', read_only=True, default='')
    author_name = serializers.SerializerMethodField()
    liked = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            'id', 'slug', 'kind', 'club', 'club_name', 'club_name_ar', 'author_name',
            'title_ar', 'title_en', 'title_vi', 'body_ar', 'body_en', 'body_vi',
            'media', 'pinned', 'published_at', 'event_starts_at', 'location',
            'like_count', 'comment_count', 'comments_enabled', 'liked',
        ]

    def get_author_name(self, obj) -> str:
        profile = getattr(obj.author, 'profile', None)
        return getattr(profile, 'full_name', '') or (obj.club.name_en if obj.club else '')

    def get_liked(self, obj) -> bool:
        """Whether *this* visitor already liked it, so the heart renders filled
        on a page they've interacted with before."""
        visitor = self.context.get('visitor')
        if not visitor:
            return False
        liked = self.context.get('liked_ids')
        if liked is not None:
            return obj.pk in liked
        return PostLike.objects.filter(post=obj, visitor=visitor).exists()


class AdminPostSerializer(serializers.ModelSerializer):
    media = PostMediaSerializer(many=True, read_only=True)
    club_name = serializers.CharField(source='club.name_en', read_only=True, default='')
    author_name = serializers.SerializerMethodField()
    is_live = serializers.BooleanField(read_only=True)

    class Meta:
        model = Post
        fields = [
            'id', 'slug', 'kind', 'club', 'club_name', 'author', 'author_name',
            'title_ar', 'title_en', 'title_vi', 'body_ar', 'body_en', 'body_vi',
            'status', 'pinned', 'published_at', 'event_starts_at', 'location',
            'comments_enabled', 'like_count', 'comment_count', 'rank_score',
            'is_live', 'media', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'slug', 'author', 'like_count', 'comment_count', 'rank_score', 'is_live',
        ]

    def get_author_name(self, obj) -> str:
        profile = getattr(obj.author, 'profile', None)
        return getattr(profile, 'full_name', '') or ''

    def validate(self, attrs):
        # A post with no title in any language would show as a blank card and
        # could not be slugged.
        merged = {**getattr(self.instance, '__dict__', {}), **attrs}
        if not any(merged.get(f) for f in ('title_ar', 'title_en', 'title_vi')):
            raise serializers.ValidationError(
                {'title_ar': 'Give the post a title in at least one language.'}
            )
        starts = merged.get('event_starts_at')
        if merged.get('kind') == Post.EVENT and not starts:
            raise serializers.ValidationError(
                {'event_starts_at': 'An event needs a start date.'}
            )
        return attrs
