"""Each club sets its own letterhead: logos and header lines.

Checked here: who may change it, what is accepted, that replaced and removed
logos leave the disk, and that every printed document actually uses them.
"""

import io
import os
import shutil
import tempfile
from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from reportlab.pdfgen import canvas
from rest_framework.test import APIClient

from registrations import letterhead
from registrations.categorization import categorize
from registrations.models import Registration

from .models import Club, UserProfile, Wilaya

User = get_user_model()


def png(name='logo.png', size=(64, 64), colour=(200, 20, 20)):
    buffer = io.BytesIO()
    Image.new('RGB', size, colour).save(buffer, 'PNG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')


def staff(email, role, club=None):
    user = User.objects.create_user(email, email, 'pw-for-tests')
    UserProfile.objects.create(user=user, role=role, club=club)
    return user


class LetterheadTestBase(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(PUBLIC_MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)

        wilaya = Wilaya.objects.create(code=30, name_ar='ورقلة', name_en='Ouargla')
        self.club = Club.objects.create(wilaya=wilaya, name_ar='نادي النجمة', name_en='Najma')
        self.other = Club.objects.create(wilaya=wilaya, name_ar='نادي آخر', name_en='Other')
        self.national = staff('n@x.dz', UserProfile.SUPER_ADMIN)
        self.president = staff('p@x.dz', UserProfile.CLUB_OWNER, club=self.club)
        self.client = APIClient()

    def patch(self, user, club, data, fmt='multipart'):
        self.client.force_authenticate(user)
        return self.client.patch(f'/api/admin/clubs/{club.pk}/letterhead/', data, format=fmt)


class WhoMayChangeIt(LetterheadTestBase):
    def test_a_president_changes_their_own_clubs(self):
        response = self.patch(self.president, self.club, {'letterhead_lines': 'سطر أول\nسطر ثان'})
        self.assertEqual(response.status_code, 200, response.content)
        self.club.refresh_from_db()
        self.assertEqual(self.club.letterhead_lines, 'سطر أول\nسطر ثان')

    def test_a_president_cannot_touch_another_clubs(self):
        response = self.patch(self.president, self.other, {'letterhead_lines': 'x'})
        self.assertEqual(response.status_code, 404)

    def test_a_branch_manager_cannot_change_it(self):
        manager = staff('m@x.dz', UserProfile.BRANCH_MANAGER, club=self.club)
        response = self.patch(manager, self.club, {'letterhead_lines': 'x'})
        self.assertEqual(response.status_code, 403)

    def test_the_national_admin_changes_any_clubs(self):
        response = self.patch(self.national, self.other, {'letterhead_lines': 'x'})
        self.assertEqual(response.status_code, 200)

    def test_a_president_still_cannot_edit_the_club_itself(self):
        self.client.force_authenticate(self.president)
        response = self.client.patch(f'/api/admin/clubs/{self.club.pk}/',
                                     {'name_en': 'Renamed'}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_reading_it_offers_the_official_wording_to_start_from(self):
        self.client.force_authenticate(self.president)
        body = self.client.get(f'/api/admin/clubs/{self.club.pk}/letterhead/').json()
        self.assertEqual(body['default_lines'][0], letterhead.REPUBLIC)
        self.assertIn('لولاية ورقلة', body['default_lines'][2])
        self.assertIsNone(body['logo_url'])


class WhatIsAccepted(LetterheadTestBase):
    def test_blank_lines_and_stray_spaces_are_tidied(self):
        self.patch(self.president, self.club, {'letterhead_lines': '  أ  \n\n\n ب \n'})
        self.club.refresh_from_db()
        self.assertEqual(self.club.letterhead_lines, 'أ\nب')

    def test_more_than_six_lines_is_refused(self):
        response = self.patch(self.president, self.club,
                              {'letterhead_lines': '\n'.join(str(i) for i in range(7))})
        self.assertEqual(response.status_code, 400)

    def test_a_line_over_120_characters_is_refused(self):
        response = self.patch(self.president, self.club, {'letterhead_lines': 'ا' * 121})
        self.assertEqual(response.status_code, 400)

    def test_a_png_logo_is_accepted_and_served_absolutely(self):
        response = self.patch(self.president, self.club, {'logo': png()})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()['logo_url'].startswith('http'))

    def test_something_that_is_not_an_image_is_refused(self):
        fake = SimpleUploadedFile('logo.png', b'not an image at all', content_type='image/png')
        response = self.patch(self.president, self.club, {'logo': fake})
        self.assertEqual(response.status_code, 400)

    def test_an_svg_is_refused(self):
        svg = SimpleUploadedFile('logo.svg', b'<svg xmlns="http://www.w3.org/2000/svg"/>',
                                 content_type='image/svg+xml')
        self.assertEqual(self.patch(self.president, self.club, {'logo': svg}).status_code, 400)

    def test_a_logo_over_2_mb_is_refused(self):
        # Random pixels do not compress, so this PNG really is over the limit.
        noise = Image.frombytes('RGB', (1000, 1000), os.urandom(1000 * 1000 * 3))
        buffer = io.BytesIO()
        noise.save(buffer, 'PNG')
        self.assertGreater(len(buffer.getvalue()), 2 * 1024 * 1024)
        big = SimpleUploadedFile('big.png', buffer.getvalue(), content_type='image/png')
        self.assertEqual(self.patch(self.president, self.club, {'logo': big}).status_code, 400)


class LogosOnDisk(LetterheadTestBase):
    def test_each_upload_gets_a_fresh_name(self):
        """Public media is cached for a year; a reused name would never update."""
        self.patch(self.president, self.club, {'logo': png()})
        first = Club.objects.get(pk=self.club.pk).logo.name
        self.patch(self.president, self.club, {'logo': png()})
        second = Club.objects.get(pk=self.club.pk).logo.name
        self.assertNotEqual(first, second)

    def test_a_replaced_logo_leaves_the_disk(self):
        self.patch(self.president, self.club, {'logo': png()})
        old = Club.objects.get(pk=self.club.pk).logo.path
        self.patch(self.president, self.club, {'logo': png(colour=(0, 0, 200))})
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(Club.objects.get(pk=self.club.pk).logo.path))

    def test_removing_a_logo_deletes_it(self):
        self.patch(self.president, self.club, {'logo': png()})
        path = Club.objects.get(pk=self.club.pk).logo.path
        response = self.patch(self.president, self.club, {'remove_logo': 'true'})
        self.assertIsNone(response.json()['logo_url'])
        self.assertFalse(os.path.exists(path))

    def test_editing_the_lines_leaves_the_logo_alone(self):
        self.patch(self.president, self.club, {'logo': png()})
        path = Club.objects.get(pk=self.club.pk).logo.path
        self.patch(self.president, self.club, {'letterhead_lines': 'سطر'})
        self.assertTrue(os.path.exists(path))

    def test_deleting_the_club_takes_its_logos(self):
        self.patch(self.national, self.club, {'logo': png(), 'logo_secondary': png()})
        club = Club.objects.get(pk=self.club.pk)
        paths = [club.logo.path, club.logo_secondary.path]
        club.delete()
        for path in paths:
            self.assertFalse(os.path.exists(path))


class TheLetterheadItself(LetterheadTestBase):
    def test_without_custom_lines_the_official_wording_is_used(self):
        texts = [t for t, _, _ in letterhead.official_lines(self.club)]
        self.assertEqual(texts, letterhead.default_lines(self.club))

    def test_custom_lines_replace_it_first_and_last_heavier(self):
        self.club.letterhead_lines = 'الأول\nالأوسط\nالأخير'
        lines = letterhead.official_lines(self.club)
        self.assertEqual([t for t, _, _ in lines], ['الأول', 'الأوسط', 'الأخير'])
        self.assertEqual([bold for _, _, bold in lines], [True, False, True])

    def test_a_club_without_logos_prints_the_platforms(self):
        start, end = letterhead.logo_files(self.club)
        self.assertEqual(start, str(letterhead.DEFAULT_LOGO))
        self.assertEqual(end, start)

    def test_one_logo_goes_on_both_sides(self):
        self.patch(self.president, self.club, {'logo': png()})
        club = Club.objects.get(pk=self.club.pk)
        start, end = letterhead.logo_files(club)
        self.assertEqual(start, club.logo.path)
        self.assertEqual(end, club.logo.path)

    def test_a_second_logo_takes_the_other_side(self):
        self.patch(self.president, self.club, {'logo': png(), 'logo_secondary': png()})
        club = Club.objects.get(pk=self.club.pk)
        self.assertEqual(letterhead.logo_files(club), (club.logo.path, club.logo_secondary.path))

    def test_six_lines_push_the_list_down_rather_than_overlap(self):
        from registrations.rosters import header_first
        short = header_first(self.club)
        self.club.letterhead_lines = '\n'.join(f'سطر {i}' for i in range(6))
        self.assertGreater(header_first(self.club), short)

    def test_an_unreadable_stored_logo_falls_back_instead_of_failing(self):
        c = canvas.Canvas(io.BytesIO())
        with mock.patch.object(canvas.Canvas, 'drawImage', autospec=True,
                               side_effect=[OSError('broken'), None]) as draw:
            letterhead.draw_logo(c, '/nowhere/broken.png', 0, 0, 10)
        self.assertEqual(draw.call_count, 2)
        self.assertEqual(draw.call_args_list[1].args[1], str(letterhead.DEFAULT_LOGO))


class EveryDocumentUsesIt(LetterheadTestBase):
    def setUp(self):
        super().setUp()
        self.patch(self.president, self.club, {'logo': png()})
        self.club.refresh_from_db()
        born = date(2000, 1, 1)
        category, is_minor, age = categorize(born)
        self.reg = Registration.objects.create(
            club=self.club, first_name='أ', last_name='ب', latin_full_name='A B',
            gender='MALE', birth_date=born, birth_place='x', address='x', phone='0',
            season='2026/2027', category=category, is_minor=is_minor, age_at_registration=age,
            status='APPROVED', payment_status='PAID')

    def images_drawn(self, build):
        drawn = []
        real = canvas.Canvas.drawImage

        def record(self_, image, *args, **kwargs):
            drawn.append(str(image))
            return real(self_, image, *args, **kwargs)

        with mock.patch.object(canvas.Canvas, 'drawImage', autospec=True, side_effect=record):
            build()
        return drawn

    def test_the_candidate_list(self):
        from registrations.rosters import generate_roster
        drawn = self.images_drawn(lambda: generate_roster(Registration.objects.all(), club=self.club))
        self.assertEqual(drawn.count(self.club.logo.path), 2)

    def test_the_registration_form(self):
        from registrations.pdf import generate_registration_pdf
        drawn = self.images_drawn(lambda: generate_registration_pdf(self.reg))
        self.assertEqual(drawn.count(self.club.logo.path), 2)

    def test_the_membership_card(self):
        from registrations.badges import generate_badge
        drawn = self.images_drawn(lambda: generate_badge(self.reg))
        self.assertIn(self.club.logo.path, drawn)

    def test_a_clubs_competition_certificates(self):
        from competitions.certificates import generate_certificate
        from competitions.models import Competition, Participant
        competition = Competition.objects.create(**self._competition_fields())
        participant = Participant.objects.create(**self._participant_fields(competition))
        drawn = self.images_drawn(lambda: generate_certificate(competition, participant))
        self.assertIn(self.club.logo.path, drawn)

    def test_the_preview_is_the_letterhead_as_it_prints(self):
        self.client.force_authenticate(self.president)
        response = self.client.get(f'/api/admin/clubs/{self.club.pk}/letterhead/preview/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))

    # Competition models have several required fields; built from the model so
    # this test does not need updating whenever one is added with a default.
    def _competition_fields(self):
        from competitions.models import Competition
        fields = {'club': self.club}
        for field in Competition._meta.concrete_fields:
            if field.name in ('id', 'club') or field.has_default() or field.null or field.blank:
                continue
            if field.choices:
                fields[field.name] = field.choices[0][0]
            elif field.get_internal_type() == 'DateField':
                fields[field.name] = date.today()
            elif field.get_internal_type() in ('CharField', 'TextField'):
                fields[field.name] = 'Test'
        return fields

    def _participant_fields(self, competition):
        from competitions.models import Participant
        fields = {'competition': competition}
        for field in Participant._meta.concrete_fields:
            if field.name in ('id', 'competition') or field.has_default() or field.null or field.blank:
                continue
            if field.is_relation:
                if field.related_model is Registration:
                    fields[field.name] = self.reg
                continue
            if field.choices:
                fields[field.name] = field.choices[0][0]
            elif field.get_internal_type() in ('CharField', 'TextField'):
                fields[field.name] = 'Test'
        return fields
