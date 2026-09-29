"""What the printed documents say.

Arabic reaches the PDF reshaped into presentation forms, so reading the text
back out of the file is unreliable. These tests capture the strings as the
generators hand them to the drawing calls instead — which is also exactly the
text a reader sees.
"""

import io
from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from rest_framework.test import APIClient

from organization.models import Center, Club, UserProfile, Wilaya

from . import letterhead
from . import pdf as registration_pdf
from . import rosters
from .categorization import categorize
from .letterhead import MINISTRY, NATIONAL_NAME, REPUBLIC, club_heading, official_lines
from .models import Registration


def make_registration(club, **kwargs):
    fields = dict(
        club=club, first_name='الياس', last_name='بن', latin_full_name='Ilyes Ben',
        gender='MALE', birth_date=date(2000, 1, 1), birth_place='Ouargla',
        address='Rue 1', phone='0555000000', season='2026/2027',
    )
    fields.update(kwargs)
    category, is_minor, age = categorize(fields['birth_date'])
    return Registration.objects.create(
        category=category, is_minor=is_minor, age_at_registration=age, **fields)


class DocumentTestBase(TestCase):
    def setUp(self):
        self.wilaya = Wilaya.objects.create(code=16, name_ar='الجزائر', name_en='Alger')
        self.club = Club.objects.create(
            wilaya=self.wilaya, name_ar='النادي الرياضي للهواة النجمة', name_en='Najma')
        self.branch = Center.objects.create(club=self.club, name_ar='باب الواد', name_en='Bab El Oued')


class TheLetterhead(DocumentTestBase):
    def test_it_opens_with_the_republic_and_the_ministry(self):
        lines = [text for text, _, _ in official_lines(self.club)]
        self.assertEqual(lines[:2], [REPUBLIC, MINISTRY])

    def test_the_directorate_follows_the_clubs_wilaya(self):
        lines = [text for text, _, _ in official_lines(self.club)]
        self.assertIn('مديرية الشباب والرياضة لولاية الجزائر', lines)

    def test_the_discipline_is_named_once(self):
        self.assertEqual(club_heading(self.club), 'النادي الرياضي للهواة النجمة للبيندين زا')
        self.club.name_ar = 'نادي البيندين زا للنجمة'
        self.assertEqual(club_heading(self.club), 'نادي البيندين زا للنجمة')

    def test_a_national_list_names_no_wilaya(self):
        lines = [text for text, _, _ in official_lines(None)]
        self.assertEqual(lines, [REPUBLIC, MINISTRY, NATIONAL_NAME])


class TheRegistrationForm(DocumentTestBase):
    def drawn_text(self, registration):
        """Every string the form writes, before it is shaped for drawing."""
        seen = []
        builder = registration_pdf.FormBuilder
        originals = {name: getattr(builder, name)
                     for name in ('centered', 'line_rtl', 'two_col_rtl', 'section_title')}

        def recorder(name):
            def record(self_, *args, **kwargs):
                seen.extend(a for a in args if isinstance(a, str))
                return originals[name](self_, *args, **kwargs)
            return record

        # The letterhead is drawn by the shared letterhead module, not by the
        # form's own builder, so listen there too.
        real_shape = letterhead.shape

        def record_shape(text):
            seen.append(str(text))
            return real_shape(text)

        with mock.patch.multiple(builder, **{n: recorder(n) for n in originals}), \
                mock.patch.object(letterhead, 'shape', side_effect=record_shape):
            out = registration_pdf.generate_registration_pdf(registration).getvalue()
        self.assertTrue(out.startswith(b'%PDF'))
        return ' | '.join(seen)

    def test_no_fees_are_printed(self):
        text = self.drawn_text(make_registration(self.club))
        self.assertNotIn('دج', text)
        self.assertNotIn('1000', text)
        self.assertNotIn('600', text)

    def test_it_carries_the_official_letterhead(self):
        text = self.drawn_text(make_registration(self.club))
        self.assertIn(REPUBLIC, text)
        self.assertIn(MINISTRY, text)
        self.assertIn('لولاية الجزائر', text)

    def test_a_parent_authorises_the_club_actually_being_joined(self):
        """It named one Ouargla club on every minor's form in the country."""
        minor = make_registration(
            self.club, birth_date=date(date.today().year - 12, 1, 1),
            parent_name='الأب', parent_id_type='CNI', parent_id_number='1')
        text = self.drawn_text(minor)
        self.assertNotIn('مدرسة الجنوب', text)
        self.assertIn('النادي الرياضي للهواة النجمة', text)


class TheCandidateList(DocumentTestBase):
    def render(self, rows, **kwargs):
        shaped, images = [], []
        real_shape = rosters.shape

        def record_shape(text):
            shaped.append(str(text))
            return real_shape(text)

        with mock.patch.object(rosters, 'shape', side_effect=record_shape), \
                mock.patch.object(letterhead, 'shape', side_effect=record_shape), \
                mock.patch.object(canvas.Canvas, 'drawImage',
                                  side_effect=lambda *a, **k: images.append(a)):
            out = rosters.generate_roster(rows, **kwargs).getvalue()
        return out, shaped, images

    def test_it_is_titled_as_a_members_list(self):
        _, shaped, _ = self.render(Registration.objects.none(), club=self.club)
        self.assertIn('قائمة المنخرطين', shaped)

    def test_the_letterhead_is_on_it(self):
        _, shaped, _ = self.render(Registration.objects.none(), club=self.club)
        for line in (REPUBLIC, MINISTRY, 'مديرية الشباب والرياضة لولاية الجزائر',
                     club_heading(self.club)):
            self.assertIn(line, shaped)

    def test_the_logo_is_on_both_sides(self):
        _, _, images = self.render(Registration.objects.none(), club=self.club)
        self.assertEqual(len(images), 2)
        # An unbound mock: (image path, x, y, ...), no self.
        left_x, right_x = sorted(call[1] for call in images)
        page_w = rosters.PAGE_SIZES[rosters.PORTRAIT][0]
        self.assertLess(left_x, page_w / 4)
        self.assertGreater(right_x, page_w * 3 / 4)

    def test_the_branch_is_named_under_the_title(self):
        _, shaped, _ = self.render(Registration.objects.none(), club=self.club, center=self.branch)
        self.assertTrue(any('باب الواد' in text for text in shaped))

    def test_only_the_first_page_carries_the_full_letterhead(self):
        rows = [make_registration(self.club) for _ in range(60)]
        out, shaped, images = self.render(rows, club=self.club)
        self.assertGreater(len(PdfReader(io.BytesIO(out)).pages), 1)
        self.assertEqual(shaped.count(REPUBLIC), 1)
        self.assertEqual(len(images), 2)

    def test_page_count_in_the_footer_matches_the_pages_printed(self):
        for count in (0, 1, 25, 26, 60, 140):
            with self.subTest(rows=count):
                rows = [make_registration(self.club) for _ in range(count)]
                out, shaped, _ = self.render(rows, club=self.club)
                printed = len(PdfReader(io.BytesIO(out)).pages)
                self.assertIn(f'الصفحة {printed} من {printed}', shaped)
                Registration.objects.all().delete()


class TheListFromTheDashboard(DocumentTestBase):
    def test_a_branch_manager_gets_their_branch_on_the_letterhead(self):
        user = get_user_model().objects.create_user('m@x.dz', 'm@x.dz', 'pw')
        UserProfile.objects.create(user=user, role=UserProfile.BRANCH_MANAGER,
                                   club=self.club, center=self.branch)
        client = APIClient()
        client.force_authenticate(user)
        with mock.patch.object(rosters, 'generate_roster', wraps=rosters.generate_roster) as spy:
            response = client.get('/api/admin/registrations-print/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(spy.call_args.kwargs['club'], self.club)
        self.assertEqual(spy.call_args.kwargs['center'], self.branch)

    def test_a_president_cannot_put_another_clubs_branch_on_it(self):
        other = Club.objects.create(wilaya=self.wilaya, name_ar='آخر', name_en='Other')
        foreign = Center.objects.create(club=other, name_ar='غريب', name_en='Foreign')
        user = get_user_model().objects.create_user('p@x.dz', 'p@x.dz', 'pw')
        UserProfile.objects.create(user=user, role=UserProfile.CLUB_OWNER, club=self.club)
        client = APIClient()
        client.force_authenticate(user)
        with mock.patch.object(rosters, 'generate_roster', wraps=rosters.generate_roster) as spy:
            client.get('/api/admin/registrations-print/', {'center': foreign.pk})
        self.assertIsNone(spy.call_args.kwargs['center'])


class OtherDocuments(TestCase):
    def test_the_badge_says_branch_not_centre(self):
        from .badges import TEXT
        self.assertEqual(TEXT['ar']['center'], 'الفرع')

    def test_a_national_competition_is_not_issued_by_an_ouargla_club(self):
        from competitions.certificates import DEFAULT_CLUB_NAME
        self.assertEqual(DEFAULT_CLUB_NAME['ar'], NATIONAL_NAME)
        for name in DEFAULT_CLUB_NAME.values():
            self.assertNotIn('Sud', name)
