"""Tests for the community feed.

The feed is the first thing on this platform that anyone can write to without
an account, so most of what is checked here is what happens when that is
abused: double likes, comment floods, drafts leaking, one club's posts landing
in another club's dashboard.
"""

import base64
import os
import shutil
import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model
from organization.models import Club, UserProfile, Wilaya

from .models import GalleryPhoto, Post, PostComment, PostLike, PostMedia, slugify_title
from .ranking import DECAY_SECONDS, engagement, rank_score

User = get_user_model()

#: The smallest thing Pillow will accept as an image, so gallery tests don't
#: need a fixture on disk. Base64 rather than a bytes literal, which is easy
#: to corrupt when this file is edited by a script.
_GIF_BYTES = base64.b64decode(
    'R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7')


def _one_pixel_gif():
    return SimpleUploadedFile('probe.gif', _GIF_BYTES, content_type='image/gif')


def make_post(**kwargs):
    defaults = dict(
        title_en='A post', status=Post.PUBLISHED, published_at=timezone.now(),
    )
    return Post.objects.create(**{**defaults, **kwargs})


class SlugTests(TestCase):
    def test_arabic_title_produces_a_usable_slug(self):
        # django.utils.text.slugify would return '' here and every Arabic post
        # would then collide on the unique constraint.
        slug = slugify_title('بطولة ورقلة الكبرى')
        self.assertTrue(slug)
        self.assertNotIn(' ', slug)

    def test_slugs_stay_unique(self):
        first = make_post(title_en='Open day')
        second = make_post(title_en='Open day')
        self.assertNotEqual(first.slug, second.slug)

    def test_slug_is_stable_across_edits(self):
        # A shared link must not rot because someone fixed a typo.
        post = make_post(title_en='Open day')
        original = post.slug
        post.title_en = 'Open day 2026'
        post.save()
        self.assertEqual(post.slug, original)

    def test_untitled_post_still_slugs(self):
        post = make_post(title_en='', title_ar='!!!')
        self.assertTrue(post.slug)


class RankingTests(TestCase):
    def test_newer_post_outranks_older_at_equal_engagement(self):
        now = timezone.now()
        older = rank_score(now - timedelta(days=2), likes=5, comments=1)
        newer = rank_score(now, likes=5, comments=1)
        self.assertGreater(newer, older)

    def test_engagement_outranks_a_slightly_newer_post(self):
        now = timezone.now()
        popular = rank_score(now - timedelta(hours=6), likes=200, comments=40)
        quiet = rank_score(now, likes=0, comments=0)
        self.assertGreater(popular, quiet)

    def test_a_single_hit_cannot_own_the_feed_forever(self):
        # The log is what guarantees this: a week of age beats any realistic
        # like count, so the feed keeps moving.
        now = timezone.now()
        ancient_hit = rank_score(now - timedelta(days=7), likes=5000, comments=900)
        fresh = rank_score(now, likes=0, comments=0)
        self.assertGreater(fresh, ancient_hit)

    def test_comments_weigh_more_than_likes(self):
        self.assertGreater(engagement(0, 1), engagement(1, 0))

    def test_zero_engagement_never_produces_a_negative_weight(self):
        now = timezone.now()
        self.assertAlmostEqual(
            rank_score(now, 0, 0), rank_score(now, 0, 0), places=6)
        self.assertGreaterEqual(rank_score(now, 0, 0), 0)

    def test_corrupt_counters_do_not_explode(self):
        # A negative counter should not raise out of a log10.
        self.assertGreaterEqual(rank_score(timezone.now(), -10, -10), 0)

    def test_score_is_deterministic(self):
        stamp = timezone.now()
        self.assertEqual(rank_score(stamp, 3, 2), rank_score(stamp, 3, 2))

    def test_decay_constant_is_the_documented_scale(self):
        now = timezone.now()
        one_point_older = now - timedelta(seconds=DECAY_SECONDS)
        self.assertAlmostEqual(
            rank_score(now, 0, 0) - rank_score(one_point_older, 0, 0), 1.0, places=4)


class FeedVisibilityTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_only_live_posts_are_public(self):
        make_post(title_en='Live one')
        make_post(title_en='A draft', status=Post.DRAFT, published_at=None)
        make_post(title_en='Scheduled', published_at=timezone.now() + timedelta(days=1))

        body = self.client.get('/api/community/posts/').json()
        titles = [row['title_en'] for row in body['results']]
        self.assertEqual(titles, ['Live one'])

    def test_scheduled_post_appears_once_due(self):
        post = make_post(title_en='Scheduled', published_at=timezone.now() + timedelta(hours=1))
        self.assertEqual(self.client.get('/api/community/posts/').json()['count'], 0)

        Post.objects.filter(pk=post.pk).update(published_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.client.get('/api/community/posts/').json()['count'], 1)

    def test_draft_detail_is_404_not_a_preview(self):
        post = make_post(title_en='Secret', status=Post.DRAFT, published_at=None)
        self.assertEqual(self.client.get(f'/api/community/posts/{post.slug}/').status_code, 404)

    def test_pinned_post_leads_regardless_of_score(self):
        make_post(title_en='Hot', published_at=timezone.now())
        pinned = make_post(
            title_en='Pinned', pinned=True, published_at=timezone.now() - timedelta(days=30))
        body = self.client.get('/api/community/posts/').json()
        self.assertEqual(body['results'][0]['slug'], pinned.slug)

    def test_paging_never_repeats_or_drops_a_post(self):
        # Same score for all five: without the id tiebreak the window can slide.
        stamp = timezone.now()
        for i in range(5):
            make_post(title_en=f'Post {i}', published_at=stamp)

        first = self.client.get('/api/community/posts/?page=1&page_size=2').json()
        second = self.client.get('/api/community/posts/?page=2&page_size=2').json()
        third = self.client.get('/api/community/posts/?page=3&page_size=2').json()

        seen = [r['slug'] for r in first['results'] + second['results'] + third['results']]
        self.assertEqual(len(seen), 5)
        self.assertEqual(len(set(seen)), 5)
        self.assertTrue(first['has_next'])
        self.assertFalse(third['has_next'])

    def test_bad_page_parameters_do_not_error(self):
        make_post()
        self.assertEqual(self.client.get('/api/community/posts/?page=abc').status_code, 200)
        self.assertEqual(self.client.get('/api/community/posts/?page=-4').status_code, 200)


class LikeTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.post = make_post()

    def url(self):
        return f'/api/community/posts/{self.post.slug}/like/'

    def test_anonymous_visitor_can_like(self):
        response = self.client.post(self.url(), REMOTE_ADDR='10.0.0.1')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['liked'])
        self.assertEqual(response.json()['like_count'], 1)

    def test_same_visitor_liking_twice_toggles_off(self):
        self.client.post(self.url(), REMOTE_ADDR='10.0.0.1', HTTP_USER_AGENT='UA')
        second = self.client.post(self.url(), REMOTE_ADDR='10.0.0.1', HTTP_USER_AGENT='UA')
        self.assertFalse(second.json()['liked'])
        self.assertEqual(second.json()['like_count'], 0)
        self.assertEqual(PostLike.objects.filter(post=self.post).count(), 0)

    def test_two_visitors_each_count(self):
        self.client.post(self.url(), REMOTE_ADDR='10.0.0.1', HTTP_USER_AGENT='A')
        self.client.post(self.url(), REMOTE_ADDR='10.0.0.2', HTTP_USER_AGENT='B')
        self.post.refresh_from_db()
        self.assertEqual(self.post.like_count, 2)

    def test_like_count_never_goes_negative(self):
        # Unliking something never liked must not underflow the counter.
        self.client.post(self.url(), REMOTE_ADDR='10.0.0.9')
        self.client.post(self.url(), REMOTE_ADDR='10.0.0.9')
        self.client.post(self.url(), REMOTE_ADDR='10.0.0.9')
        self.post.refresh_from_db()
        self.assertGreaterEqual(self.post.like_count, 0)

    def test_liking_lifts_the_rank(self):
        before = Post.objects.get(pk=self.post.pk).rank_score
        self.client.post(self.url(), REMOTE_ADDR='10.0.0.1')
        self.assertGreater(Post.objects.get(pk=self.post.pk).rank_score, before)

    def test_feed_reports_whether_this_visitor_liked_it(self):
        self.client.post(self.url(), REMOTE_ADDR='10.0.0.5', HTTP_USER_AGENT='UA')
        mine = self.client.get(
            '/api/community/posts/', REMOTE_ADDR='10.0.0.5', HTTP_USER_AGENT='UA').json()
        other = self.client.get(
            '/api/community/posts/', REMOTE_ADDR='10.0.0.6', HTTP_USER_AGENT='UA').json()
        self.assertTrue(mine['results'][0]['liked'])
        self.assertFalse(other['results'][0]['liked'])


class CommentTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.post = make_post()

    def url(self):
        return f'/api/community/posts/{self.post.slug}/comments/'

    def test_visitor_can_comment_without_an_account(self):
        response = self.client.post(
            self.url(), {'author_name': 'Amina', 'body': 'Bravo!'},
            REMOTE_ADDR='41.100.1.2',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['comment_count'], 1)

    def test_the_ip_is_kept_but_never_published(self):
        self.client.post(
            self.url(), {'author_name': 'Amina', 'body': 'Bravo!'}, REMOTE_ADDR='41.100.1.2')
        stored = PostComment.objects.get()
        self.assertEqual(stored.ip_address, '41.100.1.2')

        public = self.client.get(self.url()).json()
        self.assertNotIn('ip_address', public[0])

    def test_forwarded_header_is_preferred_behind_a_proxy(self):
        self.client.post(
            self.url(), {'author_name': 'Amina', 'body': 'Bravo!'},
            REMOTE_ADDR='10.0.0.1', HTTP_X_FORWARDED_FOR='41.100.9.9, 10.0.0.1',
        )
        self.assertEqual(PostComment.objects.get().ip_address, '41.100.9.9')

    def test_empty_comment_is_rejected(self):
        response = self.client.post(
            self.url(), {'author_name': 'Amina', 'body': '   '}, REMOTE_ADDR='41.100.1.3')
        self.assertEqual(response.status_code, 400)

    def test_flood_from_one_ip_is_throttled(self):
        for i in range(3):
            ok = self.client.post(
                self.url(), {'author_name': 'Spam', 'body': f'buy {i}'}, REMOTE_ADDR='41.1.1.1')
            self.assertEqual(ok.status_code, 201)
        blocked = self.client.post(
            self.url(), {'author_name': 'Spam', 'body': 'buy more'}, REMOTE_ADDR='41.1.1.1')
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.json()['code'], 'RATE_LIMITED')

    def test_another_ip_is_not_caught_by_someone_elses_flood(self):
        for i in range(3):
            self.client.post(
                self.url(), {'author_name': 'Spam', 'body': f'buy {i}'}, REMOTE_ADDR='41.1.1.1')
        fine = self.client.post(
            self.url(), {'author_name': 'Real', 'body': 'Nice work'}, REMOTE_ADDR='41.2.2.2')
        self.assertEqual(fine.status_code, 201)

    def test_comments_can_be_closed_on_a_post(self):
        self.post.comments_enabled = False
        self.post.save()
        response = self.client.post(
            self.url(), {'author_name': 'Amina', 'body': 'Hi'}, REMOTE_ADDR='41.3.3.3')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['code'], 'COMMENTS_CLOSED')

    def test_hidden_comments_disappear_from_the_public_thread(self):
        self.client.post(
            self.url(), {'author_name': 'Amina', 'body': 'Bravo'}, REMOTE_ADDR='41.4.4.4')
        PostComment.objects.update(status=PostComment.HIDDEN)
        self.assertEqual(self.client.get(self.url()).json(), [])


class AdminScopingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        wilaya = Wilaya.objects.create(code=30, name_ar='ورقلة', name_en='Ouargla')
        self.club_a = Club.objects.create(wilaya=wilaya, name_ar='أ', name_en='Club A')
        self.club_b = Club.objects.create(wilaya=wilaya, name_ar='ب', name_en='Club B')

        self.owner = User.objects.create_user('a@club.dz', password='pw')
        UserProfile.objects.create(
            user=self.owner, role=UserProfile.CLUB_OWNER, club=self.club_a, full_name='Owner A')
        self.boss = User.objects.create_user('boss@club.dz', password='pw')
        UserProfile.objects.create(
            user=self.boss, role=UserProfile.SUPER_ADMIN, full_name='Boss')

    def test_owner_sees_only_their_own_posts(self):
        make_post(title_en='Mine', club=self.club_a)
        make_post(title_en='Theirs', club=self.club_b)

        self.client.force_authenticate(self.owner)
        rows = self.client.get('/api/admin/posts/').json()['results']
        self.assertEqual([r['title_en'] for r in rows], ['Mine'])

    def test_owner_posting_for_another_club_is_filed_under_their_own(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            '/api/admin/posts/', {'title_en': 'Try', 'club': self.club_b.id}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['club'], self.club_a.id)

    def test_super_admin_sees_every_club(self):
        make_post(title_en='Mine', club=self.club_a)
        make_post(title_en='Theirs', club=self.club_b)

        self.client.force_authenticate(self.boss)
        rows = self.client.get('/api/admin/posts/').json()['results']
        self.assertEqual(sorted(r['title_en'] for r in rows), ['Mine', 'Theirs'])

    def test_a_post_needs_a_title_in_some_language(self):
        self.client.force_authenticate(self.boss)
        response = self.client.post('/api/admin/posts/', {'kind': 'NEWS'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_an_event_needs_a_start_date(self):
        self.client.force_authenticate(self.boss)
        response = self.client.post(
            '/api/admin/posts/', {'title_en': 'Gala', 'kind': 'EVENT'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_republishing_does_not_move_the_post_back_to_the_top(self):
        post = make_post(title_en='Old news', published_at=timezone.now() - timedelta(days=3))
        self.client.force_authenticate(self.boss)
        self.client.post(f'/api/admin/posts/{post.pk}/publish/')
        post.refresh_from_db()
        self.assertLess(post.published_at, timezone.now() - timedelta(days=2))

    def test_owner_cannot_moderate_another_clubs_comments(self):
        theirs = make_post(title_en='Theirs', club=self.club_b)
        PostComment.objects.create(post=theirs, author_name='X', body='hi')

        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.get('/api/admin/comments/').json()['results'], [])

    def test_hiding_a_comment_corrects_the_public_counter(self):
        post = make_post(title_en='Mine', club=self.club_a)
        self.client.post(
            f'/api/community/posts/{post.slug}/comments/',
            {'author_name': 'Amina', 'body': 'Bravo'}, REMOTE_ADDR='41.5.5.5')
        post.refresh_from_db()
        self.assertEqual(post.comment_count, 1)

        comment = PostComment.objects.get()
        self.client.force_authenticate(self.owner)
        self.client.post(f'/api/admin/comments/{comment.pk}/hide/')

        post.refresh_from_db()
        self.assertEqual(post.comment_count, 0)


class GalleryTests(TestCase):
    """Uploads go to a throwaway directory — a test run must never leave files
    in the real storage tree, and public_storage reads the setting per call so
    the override actually takes effect."""

    @classmethod
    def setUpClass(cls):
        cls._media = tempfile.mkdtemp(prefix='bdg-test-media-')
        cls._override = override_settings(PUBLIC_MEDIA_ROOT=cls._media)
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)

    def setUp(self):
        self.client = APIClient()
        self.boss = User.objects.create_user('boss2@club.dz', password='pw')
        UserProfile.objects.create(
            user=self.boss, role=UserProfile.SUPER_ADMIN, full_name='Boss')

    def test_gallery_is_public(self):
        self.assertEqual(self.client.get('/api/gallery/').status_code, 200)

    def test_managing_the_gallery_needs_a_login(self):
        self.assertEqual(self.client.get('/api/admin/gallery/').status_code, 401)

    def test_a_multipart_upload_is_visible_by_default(self):
        # DRF reads a *missing* boolean in multipart as an unchecked checkbox,
        # i.e. False. Without OptionalBooleanField every uploaded photo would
        # be saved hidden and the carousel would stay empty.
        self.client.force_authenticate(self.boss)
        response = self.client.post(
            '/api/admin/gallery/',
            {'image': _one_pixel_gif(), 'caption_en': 'Training'},
            format='multipart',
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data['active'])
        self.assertEqual(len(self.client.get('/api/gallery/').json()), 1)

    def test_deleting_a_photo_removes_the_file_too(self):
        # Django leaves the file behind on its own; without the post_delete
        # receiver the disk fills up with orphans nothing references.
        self.client.force_authenticate(self.boss)
        created = self.client.post(
            '/api/admin/gallery/',
            {'image': _one_pixel_gif(), 'caption_en': 'Training'},
            format='multipart',
        ).data
        photo = GalleryPhoto.objects.get(pk=created['id'])
        path = photo.image.path
        self.assertTrue(os.path.exists(path))

        self.client.delete(f'/api/admin/gallery/{created["id"]}/')
        self.assertFalse(os.path.exists(path))

    def test_deleting_a_post_removes_its_attachments(self):
        self.client.force_authenticate(self.boss)
        post = make_post(title_en='With media')
        self.client.post(
            f'/api/admin/posts/{post.pk}/media/',
            {'file': _one_pixel_gif()}, format='multipart',
        )
        media = PostMedia.objects.get(post=post)
        path = media.file.path
        self.assertTrue(os.path.exists(path))

        post.delete()
        self.assertFalse(os.path.exists(path))

    def test_hiding_a_photo_takes_it_out_of_the_carousel(self):
        self.client.force_authenticate(self.boss)
        created = self.client.post(
            '/api/admin/gallery/',
            {'image': _one_pixel_gif(), 'caption_en': 'Training'},
            format='multipart',
        ).data
        self.client.patch(
            f'/api/admin/gallery/{created["id"]}/', {'active': False}, format='json')
        self.assertEqual(self.client.get('/api/gallery/').json(), [])


class PublicMediaIsServedInProduction(TestCase):
    """The carousel and post attachments must load with DEBUG off.

    Django's test runner already forces DEBUG=False, which is the whole point:
    this was originally wired with `django.conf.urls.static.static()`, which
    quietly returns no routes unless DEBUG is on. Everything worked locally and
    every image 404'd on the live site.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        os.makedirs(os.path.join(self.root, 'gallery'))
        with open(os.path.join(self.root, 'gallery', 'photo.gif'), 'wb') as handle:
            handle.write(_GIF_BYTES)

    def test_a_public_file_is_downloadable(self):
        with override_settings(PUBLIC_MEDIA_ROOT=self.root):
            response = self.client.get('/public-media/gallery/photo.gif')
        self.assertEqual(response.status_code, 200)
        self.assertIn('max-age=', response['Cache-Control'])

    def test_registration_documents_are_not_reachable_through_it(self):
        """MEDIA_ROOT sits outside PUBLIC_MEDIA_ROOT and must stay there."""
        with override_settings(PUBLIC_MEDIA_ROOT=self.root):
            response = self.client.get('/public-media/../uploads/anything.pdf')
        self.assertNotEqual(response.status_code, 200)
