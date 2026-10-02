"""Official papers must be scanned PDFs; the ID photo must be an image."""

import io
import shutil
import tempfile
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from rest_framework.test import APIClient

from organization.models import Club, Wilaya

from .models import Registration, RequiredDocument
from .uploads import UploadProblem, check_scanned_pdf


def scanned_pdf(pages=1, dpi=150):
    images = [Image.new('L', (int(8.27 * dpi), int(11.69 * dpi)), 235) for _ in range(pages)]
    buffer = io.BytesIO()
    images[0].save(buffer, 'PDF', save_all=True, append_images=images[1:], resolution=dpi)
    return buffer.getvalue()


def typed_pdf(with_small_logo=False):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    if with_small_logo:
        logo = io.BytesIO()
        Image.new('RGB', (120, 120), (200, 0, 0)).save(logo, 'PNG')
        logo.seek(0)
        c.drawImage(ImageReader(logo), 50, 750, 40, 40)
    c.drawString(100, 700, 'A typed birth certificate')
    c.save()
    return buffer.getvalue()


def jpeg(size=(600, 800)):
    buffer = io.BytesIO()
    Image.new('RGB', size, (180, 150, 120)).save(buffer, 'JPEG')
    return buffer.getvalue()


def as_upload(name, data, content_type='application/pdf'):
    return SimpleUploadedFile(name, data, content_type=content_type)


class WhatCountsAsAScan(TestCase):
    def refused(self, name, data):
        with self.assertRaises(UploadProblem) as caught:
            check_scanned_pdf(as_upload(name, data))
        return caught.exception.code

    def test_a_scan_is_accepted(self):
        check_scanned_pdf(as_upload('scan.pdf', scanned_pdf(pages=2)))

    def test_a_low_resolution_scan_is_still_a_scan(self):
        check_scanned_pdf(as_upload('scan.pdf', scanned_pdf(dpi=72)))

    def test_a_typed_pdf_is_not_a_scan(self):
        self.assertEqual(self.refused('doc.pdf', typed_pdf()), 'NOT_SCANNED')

    def test_a_small_logo_does_not_make_it_a_scan(self):
        self.assertEqual(self.refused('doc.pdf', typed_pdf(with_small_logo=True)), 'NOT_SCANNED')

    def test_every_page_must_be_scanned(self):
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        page = io.BytesIO()
        Image.new('L', (1240, 1754), 230).save(page, 'PNG')
        page.seek(0)
        c.drawImage(ImageReader(page), 0, 0, A4[0], A4[1])
        c.showPage()
        c.drawString(100, 700, 'typed second page')
        c.save()
        self.assertEqual(self.refused('mixed.pdf', buffer.getvalue()), 'NOT_SCANNED')

    def test_a_renamed_image_is_not_a_pdf(self):
        self.assertEqual(self.refused('photo.pdf', jpeg()), 'NOT_PDF')

    def test_the_extension_must_say_pdf_too(self):
        self.assertEqual(self.refused('scan.jpg', scanned_pdf()), 'NOT_PDF')

    def test_a_damaged_pdf_is_refused(self):
        self.assertEqual(self.refused('broken.pdf', b'%PDF-1.4\nthis is not a pdf'), 'DAMAGED')

    def test_an_empty_file_is_refused(self):
        self.assertEqual(self.refused('empty.pdf', b''), 'EMPTY')


class CheckingAsTheCandidateChooses(TestCase):
    def setUp(self):
        self.scan_doc = RequiredDocument.objects.create(
            key='birth', label_ar='شهادة ميلاد', label_en='Birth', label_vi='Birth')
        self.photo_doc = RequiredDocument.objects.create(
            key='photos', label_ar='صورة', label_en='Photo', label_vi='Photo',
            file_kind=RequiredDocument.IMAGE)
        self.client = APIClient()

    def check(self, key, name, data, content_type='application/pdf'):
        return self.client.post('/api/documents/check/',
                                {'key': key, 'file': as_upload(name, data, content_type)},
                                format='multipart')

    def test_a_scan_passes(self):
        response = self.check('birth', 'scan.pdf', scanned_pdf())
        self.assertEqual(response.status_code, 200)

    def test_a_typed_pdf_is_caught_straight_away(self):
        response = self.check('birth', 'doc.pdf', typed_pdf())
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'NOT_SCANNED')

    def test_the_photo_takes_an_image(self):
        self.assertEqual(self.check('photos', 'me.jpg', jpeg(), 'image/jpeg').status_code, 200)

    def test_the_photo_refuses_a_pdf(self):
        """The card prints the photo; a PDF cannot be printed as a portrait."""
        response = self.check('photos', 'me.pdf', scanned_pdf())
        self.assertEqual(response.json()['code'], 'NOT_IMAGE')

    def test_a_thumbnail_is_too_small_for_a_card(self):
        response = self.check('photos', 'me.jpg', jpeg((120, 160)), 'image/jpeg')
        self.assertEqual(response.json()['code'], 'TOO_SMALL')

    def test_nothing_is_stored(self):
        self.check('birth', 'scan.pdf', scanned_pdf())
        self.assertFalse(Registration.objects.exists())


class TheSubmissionChecksToo(TestCase):
    """The form checks each file as it is chosen, but the form can be
    bypassed; the submission itself must refuse a wrong file."""

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        wilaya = Wilaya.objects.create(code=30, name_ar='ورقلة', name_en='Ouargla')
        self.club = Club.objects.create(wilaya=wilaya, name_ar='نادي', name_en='Club')
        RequiredDocument.objects.create(key='birth', label_ar='شهادة', label_en='Birth', label_vi='B')

    def submit(self, birth_file):
        return APIClient().post('/api/registrations/', {
            'club': self.club.pk, 'first_name': 'أمين', 'last_name': 'ب',
            'latin_full_name': 'Amine B', 'gender': 'MALE',
            'birth_date': date(date.today().year - 30, 1, 1).isoformat(),
            'birth_place': 'x', 'address': 'x', 'phone': '0555', 'email': 'amine@example.dz',
            'doc_birth': birth_file,
        }, format='multipart')

    def test_a_typed_pdf_is_refused_and_nothing_saved(self):
        response = self.submit(as_upload('doc.pdf', typed_pdf()))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['invalid_documents']['birth']['code'], 'NOT_SCANNED')
        self.assertFalse(Registration.objects.exists())

    def test_a_scan_goes_through(self):
        response = self.submit(as_upload('scan.pdf', scanned_pdf()))
        self.assertEqual(response.status_code, 201, response.content)

    def test_an_email_address_is_required(self):
        response = APIClient().post('/api/registrations/', {
            'club': self.club.pk, 'first_name': 'أ', 'last_name': 'ب', 'latin_full_name': 'A B',
            'gender': 'MALE', 'birth_date': '1995-01-01', 'birth_place': 'x', 'address': 'x',
            'phone': '0', 'doc_birth': as_upload('scan.pdf', scanned_pdf()),
        }, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertIn('email', response.json())
