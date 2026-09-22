"""Public-facing content: the landing-page carousel and the community feed.

Two things live here. GalleryPhoto backs the carousel the admin curates. Post
and its companions back the feed where the club — or any club owner — publishes
news and events that visitors read, like and comment on **without an account**.

No account means no user id to attach anything to, so every anonymous action is
identified by the caller's IP (kept, as the club asked, for moderation) plus a
fingerprint derived from it. That fingerprint is what stops one visitor liking
the same post twice.
"""

import hashlib
import os
import re
import unicodedata
import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.deconstruct import deconstructible

from .ranking import rank_score

@deconstructible
class PublicMediaStorage(FileSystemStorage):
    """Where community media lives — world-readable by design, and deliberately
    outside MEDIA_ROOT, which holds the private registration documents.

    The location is read from settings on every access rather than captured in
    __init__. Two things depend on that: makemigrations serializes this class
    by name instead of baking one machine's absolute path into the migration,
    and a test can point PUBLIC_MEDIA_ROOT at a temporary directory without the
    uploads still landing in the real tree. (Django resolves a *callable*
    storage once when the field is built, so that alternative would not.)
    """

    @property
    def base_location(self):
        return settings.PUBLIC_MEDIA_ROOT

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    @property
    def base_url(self):
        url = settings.PUBLIC_MEDIA_URL
        return url if url.endswith('/') else url + '/'


public_storage = PublicMediaStorage()

IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp', 'gif']
VIDEO_EXTENSIONS = ['mp4', 'webm', 'mov']


def _public_path(folder: str, filename: str) -> str:
    """A collision-proof path. Visitors never see the original filename, and
    two admins uploading `photo.jpg` at once must not fight over one name."""
    suffix = Path(filename).suffix.lower()
    stamp = timezone.now().strftime('%Y/%m')
    return f'{folder}/{stamp}/{uuid.uuid4().hex}{suffix}'


# Named rather than closures: makemigrations has to serialize upload_to by
# import path, and a nested function has none.
def gallery_upload_to(instance, filename):
    return _public_path('gallery', filename)


def post_upload_to(instance, filename):
    return _public_path('posts', filename)


def poster_upload_to(instance, filename):
    return _public_path('posters', filename)


def slugify_title(value: str) -> str:
    """A URL-safe slug that survives Arabic and Vietnamese titles.

    Django's slugify strips non-ASCII entirely, so an Arabic-only title would
    slugify to the empty string and every such post would collide.
    """
    text = unicodedata.normalize('NFKC', value or '').strip().lower()
    text = re.sub(r'[\s_]+', '-', text)
    # Keep letters and digits of any script; drop punctuation.
    text = ''.join(ch for ch in text if ch.isalnum() or ch == '-')
    text = re.sub(r'-{2,}', '-', text).strip('-')
    return text[:60]


def fingerprint(ip: str, user_agent: str = '') -> str:
    """Identifies an anonymous visitor well enough to stop double-liking.

    Hashed rather than stored raw so the like table can't be read back as a
    browsing history; the comment table keeps the real IP, which is what the
    club actually needs for moderation.
    """
    raw = f'{ip}|{user_agent[:200]}'.encode('utf-8', 'ignore')
    return hashlib.sha256(raw).hexdigest()[:40]


class GalleryPhoto(models.Model):
    """One slide of the landing-page carousel."""

    club = models.ForeignKey(
        'organization.Club', null=True, blank=True, related_name='gallery_photos',
        on_delete=models.CASCADE, help_text='Blank means it belongs to the whole platform',
    )
    image = models.ImageField(
        upload_to=gallery_upload_to, storage=public_storage,
        validators=[FileExtensionValidator(IMAGE_EXTENSIONS)],
    )
    caption_ar = models.CharField(max_length=160, blank=True)
    caption_en = models.CharField(max_length=160, blank=True)
    caption_vi = models.CharField(max_length=160, blank=True)
    order = models.PositiveSmallIntegerField(default=0)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Ties broken by id so the carousel order never shuffles between reads.
        ordering = ['order', 'id']

    def __str__(self):
        return self.caption_en or f'Photo #{self.pk}'


class Post(models.Model):
    """A news item or event announcement shown in the public feed."""

    DRAFT = 'DRAFT'
    PUBLISHED = 'PUBLISHED'
    ARCHIVED = 'ARCHIVED'
    STATUS_CHOICES = [
        (DRAFT, 'Draft'),
        (PUBLISHED, 'Published'),
        (ARCHIVED, 'Archived'),
    ]

    NEWS = 'NEWS'
    EVENT = 'EVENT'
    RESULT = 'RESULT'
    KIND_CHOICES = [(NEWS, 'News'), (EVENT, 'Event'), (RESULT, 'Result')]

    club = models.ForeignKey(
        'organization.Club', null=True, blank=True, related_name='posts',
        on_delete=models.CASCADE, help_text='Blank means it speaks for the whole platform',
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='posts',
    )
    slug = models.SlugField(max_length=80, unique=True, allow_unicode=True, editable=False)
    kind = models.CharField(max_length=8, choices=KIND_CHOICES, default=NEWS)

    title_ar = models.CharField(max_length=200, blank=True)
    title_en = models.CharField(max_length=200, blank=True)
    title_vi = models.CharField(max_length=200, blank=True)
    body_ar = models.TextField(blank=True)
    body_en = models.TextField(blank=True)
    body_vi = models.TextField(blank=True)

    status = models.CharField(max_length=9, choices=STATUS_CHOICES, default=DRAFT)
    pinned = models.BooleanField(default=False)
    # Set when it first goes live. A future value schedules it.
    published_at = models.DateTimeField(null=True, blank=True)

    event_starts_at = models.DateTimeField(null=True, blank=True)
    location = models.CharField(max_length=160, blank=True)

    # Denormalised so the feed never has to COUNT across two big tables.
    like_count = models.PositiveIntegerField(default=0)
    comment_count = models.PositiveIntegerField(default=0)
    # Cached ranking, refreshed whenever engagement or publication changes.
    rank_score = models.FloatField(default=0, db_index=True)

    comments_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # id breaks ties: two posts sharing a score must still come back in a
        # fixed order, or paging the feed would repeat or skip rows.
        ordering = ['-pinned', '-rank_score', '-id']
        indexes = [models.Index(fields=['status', 'published_at'])]

    def __str__(self):
        return self.display_title or self.slug

    @property
    def display_title(self) -> str:
        return self.title_ar or self.title_en or self.title_vi or ''

    @property
    def is_live(self) -> bool:
        """Published *and* actually due — a future published_at is a schedule."""
        return (
            self.status == self.PUBLISHED
            and self.published_at is not None
            and self.published_at <= timezone.now()
        )

    def assign_slug(self):
        """A stable, unique slug. Called only while the slug is still empty, so
        a published post's URL never changes underneath a shared link."""
        base = (
            slugify_title(self.title_en)
            or slugify_title(self.title_ar)
            or slugify_title(self.title_vi)
            or 'post'
        )
        candidate = base
        suffix = 2
        while Post.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
            candidate = f'{base}-{suffix}'
            suffix += 1
        self.slug = candidate

    def refresh_rank(self, save: bool = True):
        self.rank_score = rank_score(
            self.published_at or self.created_at or timezone.now(),
            self.like_count,
            self.comment_count,
        )
        if save:
            Post.objects.filter(pk=self.pk).update(rank_score=self.rank_score)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.assign_slug()
        # Publishing stamps the time once. Re-saving a live post must not move
        # it back to the top of the feed.
        if self.status == self.PUBLISHED and self.published_at is None:
            self.published_at = timezone.now()
        self.rank_score = rank_score(
            self.published_at or timezone.now(), self.like_count, self.comment_count,
        )
        super().save(*args, **kwargs)


class PostMedia(models.Model):
    """A photo or clip attached to a post."""

    IMAGE = 'IMAGE'
    VIDEO = 'VIDEO'
    KIND_CHOICES = [(IMAGE, 'Image'), (VIDEO, 'Video')]

    post = models.ForeignKey(Post, related_name='media', on_delete=models.CASCADE)
    kind = models.CharField(max_length=5, choices=KIND_CHOICES, default=IMAGE)
    file = models.FileField(
        upload_to=post_upload_to, storage=public_storage,
        validators=[FileExtensionValidator(IMAGE_EXTENSIONS + VIDEO_EXTENSIONS)],
    )
    # Shown while a video loads, and used as the feed thumbnail.
    poster = models.ImageField(
        upload_to=poster_upload_to, storage=public_storage,
        validators=[FileExtensionValidator(IMAGE_EXTENSIONS)], null=True, blank=True,
    )
    alt_text = models.CharField(max_length=200, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f'{self.get_kind_display()} on {self.post_id}'


class PostLike(models.Model):
    """An anonymous like. One per visitor per post, enforced by the database."""

    post = models.ForeignKey(Post, related_name='likes', on_delete=models.CASCADE)
    visitor = models.CharField(max_length=40, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # The real guard against double-counting: a race that slips past the
        # view still cannot write a second row.
        unique_together = ('post', 'visitor')

    def __str__(self):
        return f'like on {self.post_id}'


class PostComment(models.Model):
    """A visitor's comment. The club keeps the IP so it can moderate abuse."""

    PUBLISHED = 'PUBLISHED'
    HIDDEN = 'HIDDEN'
    STATUS_CHOICES = [(PUBLISHED, 'Published'), (HIDDEN, 'Hidden')]

    post = models.ForeignKey(Post, related_name='comments', on_delete=models.CASCADE)
    author_name = models.CharField(max_length=80)
    body = models.TextField(max_length=2000)
    status = models.CharField(max_length=9, choices=STATUS_CHOICES, default=PUBLISHED)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    visitor = models.CharField(max_length=40, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']
        indexes = [models.Index(fields=['post', 'status'])]

    def __str__(self):
        return f'{self.author_name} on {self.post_id}'


# ── Keeping the disk in step with the database ───────────────────────────────
#
# Django deliberately does not remove a file when its row is deleted — a
# rollback would otherwise leave the row referring to a file that no longer
# exists. Nothing else cleans up either, so without these receivers every
# deleted photo and every replaced video would sit on the server forever. A
# club posting 64 MB clips would notice.

def _discard(file_field):
    """Delete the stored file, tolerating one that has already gone."""
    if not file_field:
        return
    try:
        file_field.storage.delete(file_field.name)
    except (OSError, ValueError):
        # A missing or unreachable file must never break the delete itself.
        pass


@receiver(post_delete, sender=GalleryPhoto)
def _gallery_photo_deleted(sender, instance, **kwargs):
    _discard(instance.image)


@receiver(post_delete, sender=PostMedia)
def _post_media_deleted(sender, instance, **kwargs):
    # Fires for cascades too, so deleting a post cleans up its attachments.
    _discard(instance.file)
    _discard(instance.poster)


@receiver(pre_save, sender=GalleryPhoto)
def _gallery_photo_replaced(sender, instance, **kwargs):
    if not instance.pk:
        return
    previous = GalleryPhoto.objects.filter(pk=instance.pk).first()
    if previous and previous.image and previous.image.name != instance.image.name:
        _discard(previous.image)


@receiver(pre_save, sender=PostMedia)
def _post_media_replaced(sender, instance, **kwargs):
    if not instance.pk:
        return
    previous = PostMedia.objects.filter(pk=instance.pk).first()
    if not previous:
        return
    if previous.file and previous.file.name != instance.file.name:
        _discard(previous.file)
    if previous.poster and previous.poster.name != getattr(instance.poster, 'name', None):
        _discard(previous.poster)
