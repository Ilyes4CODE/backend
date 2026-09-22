from datetime import date

from django.test import TestCase

from organization.models import Center, Club, Wilaya
from .categorization import categorize
from .models import Registration
from .rosters import (
    COLUMN_SETS, LANDSCAPE, PORTRAIT, columns_mm, generate_roster, usable_mm,
)


class RosterLayoutTests(TestCase):
    """The roster draws at fixed millimetre offsets. Nothing errors when the
    columns are wider than the page — the last one just runs off the edge and
    prints clipped — so the fit has to be asserted."""

    def test_roster_fits_the_page(self):
        for orientation in (PORTRAIT, LANDSCAPE):
            with self.subTest(orientation=orientation):
                needed, available = columns_mm(orientation), usable_mm(orientation)
                self.assertLessEqual(
                    needed, available,
                    f'{orientation} columns need {needed} mm but only {available} mm '
                    'print; the rightmost column would be clipped',
                )

    def test_signature_column_is_last_and_empty(self):
        for orientation in (PORTRAIT, LANDSCAPE):
            with self.subTest(orientation=orientation):
                heading, _, reader = COLUMN_SETS[orientation][-1]
                self.assertEqual(heading, 'Signature')
                self.assertEqual(reader(None), '')

    def test_portrait_is_the_default(self):
        # The club prints a register, not a diploma.
        from reportlab.lib.pagesizes import A4
        from .rosters import PAGE_SIZES
        width, height = PAGE_SIZES[PORTRAIT]
        self.assertLess(width, height)
        self.assertAlmostEqual(width, A4[0], places=3)


class RosterContentTests(TestCase):
    def setUp(self):
        wilaya = Wilaya.objects.create(code=30, name_ar='ورقلة', name_en='Ouargla')
        self.club = Club.objects.create(wilaya=wilaya, name_ar='نادي', name_en='Club')
        self.center = Center.objects.create(club=self.club, name_ar='مركز', name_en='Lassilis')

    def _make(self, **kwargs):
        defaults = dict(
            club=self.club, first_name='الياس', last_name='بن', latin_full_name='Ilyes Ben',
            gender='MALE', birth_date=date(2000, 1, 1), birth_place='Ouargla',
            address='Rue 1', phone='0555000000',
        )
        fields = {**defaults, **kwargs}
        # The view derives these on submit; the model doesn't compute them.
        category, is_minor, age = categorize(fields['birth_date'])
        return Registration.objects.create(
            category=category, is_minor=is_minor, age_at_registration=age, **fields)

    def test_pdf_is_produced_for_mixed_rows(self):
        # An Arabic name, a centre, a female row and a row predating the sex
        # field all have to render without blowing up.
        self._make()
        self._make(gender='FEMALE', center=self.center, latin_full_name='Amina B')
        self._make(gender='', latin_full_name='Legacy Row')

        for orientation in (PORTRAIT, LANDSCAPE):
            with self.subTest(orientation=orientation):
                pdf = generate_roster(
                    Registration.objects.all(), subtitle='Season 2025/2026',
                    orientation=orientation,
                ).getvalue()
                self.assertTrue(pdf.startswith(b'%PDF'))

    def test_missing_sex_renders_a_dash_rather_than_crashing(self):
        legacy = self._make(gender='')
        _, _, read_sex = next(c for c in COLUMN_SETS[PORTRAIT] if c[0] == 'Sex')
        self.assertEqual(read_sex(legacy), '—')

    def test_unknown_orientation_falls_back_to_portrait(self):
        # A hand-edited query string must not 500 the print button.
        pdf = generate_roster(Registration.objects.none(), orientation='sideways').getvalue()
        self.assertTrue(pdf.startswith(b'%PDF'))

    def test_empty_roster_still_builds(self):
        pdf = generate_roster(Registration.objects.none()).getvalue()
        self.assertTrue(pdf.startswith(b'%PDF'))
