"""Deleting registrations and required documents.

The files here are identity documents, so what matters is that a deleted
candidate leaves nothing on disk, that only the people who can see a candidate
can delete them, and that deleting a document type never takes people's
uploads with it.
"""

import os
import shutil
import tempfile
from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from organization.activity import ActivityLog
from organization.models import Center, Club, UserProfile, Wilaya

from .categorization import categorize
from .models import Registration, RequiredDocument, UploadedDocument

User = get_user_model()


def staff(email, role, club=None, center=None):
    user = User.objects.create_user(email, email, 'pw-for-tests')
    UserProfile.objects.create(user=user, role=role, club=club, center=center)
    return user


class DeletionTestBase(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)

        wilaya = Wilaya.objects.create(code=30, name_ar='ورقلة', name_en='Ouargla')
        self.club = Club.objects.create(wilaya=wilaya, name_ar='نادي', name_en='Club')
        self.other_club = Club.objects.create(wilaya=wilaya, name_ar='آخر', name_en='Other')
        self.branch = Center.objects.create(club=self.club, name_ar='شمال', name_en='North')
        self.sibling = Center.objects.create(club=self.club, name_ar='جنوب', name_en='South')

        self.national = staff('n@x.dz', UserProfile.SUPER_ADMIN)
        self.president = staff('p@x.dz', UserProfile.CLUB_OWNER, club=self.club)
        self.other_president = staff('o@x.dz', UserProfile.CLUB_OWNER, club=self.other_club)
        self.manager = staff('m@x.dz', UserProfile.BRANCH_MANAGER, club=self.club, center=self.branch)

        self.doc_type = RequiredDocument.objects.create(
            key='medical', label_ar='شهادة طبية', label_en='Medical', label_vi='Medical')
        self.client = APIClient()

    _DEFAULT = object()

    def registration(self, center=_DEFAULT, club=None):
        born = date(2000, 1, 1)
        category, is_minor, age = categorize(born)
        reg = Registration.objects.create(
            club=club or self.club, center=self.branch if center is self._DEFAULT else center,
            first_name='أمين', last_name='بلقاسم', latin_full_name='Amine B',
            gender='MALE', birth_date=born, birth_place='Ouargla', address='Rue 1',
            phone='0555000000', season='2026/2027',
            category=category, is_minor=is_minor, age_at_registration=age)
        UploadedDocument.objects.create(
            registration=reg, required_document=self.doc_type, original_name='id.pdf',
            file=SimpleUploadedFile('id.pdf', b'%PDF-1.4 identity document'))
        return reg


class DeletingARegistration(DeletionTestBase):
    def delete(self, user, reg):
        self.client.force_authenticate(user)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.delete(f'/api/admin/registrations/{reg.pk}/')

    def test_the_branch_manager_can_delete_their_candidate(self):
        reg = self.registration()
        self.assertEqual(self.delete(self.manager, reg).status_code, 204)
        self.assertFalse(Registration.objects.filter(pk=reg.pk).exists())

    def test_the_president_can_delete_any_candidate_of_their_club(self):
        reg = self.registration(center=self.sibling)
        self.assertEqual(self.delete(self.president, reg).status_code, 204)

    def test_the_national_admin_can_delete_anyone(self):
        reg = self.registration(club=self.other_club, center=None)
        self.assertEqual(self.delete(self.national, reg).status_code, 204)

    def test_a_manager_cannot_delete_a_sibling_branchs_candidate(self):
        reg = self.registration(center=self.sibling)
        self.assertEqual(self.delete(self.manager, reg).status_code, 404)
        self.assertTrue(Registration.objects.filter(pk=reg.pk).exists())

    def test_a_president_cannot_delete_another_clubs_candidate(self):
        reg = self.registration()
        self.assertEqual(self.delete(self.other_president, reg).status_code, 404)
        self.assertTrue(Registration.objects.filter(pk=reg.pk).exists())

    def test_anonymous_callers_are_refused(self):
        reg = self.registration()
        response = APIClient().delete(f'/api/admin/registrations/{reg.pk}/')
        self.assertEqual(response.status_code, 401)

    def test_the_uploaded_files_leave_the_disk(self):
        reg = self.registration()
        path = reg.documents.get().file.path
        folder = os.path.dirname(path)
        self.assertTrue(os.path.exists(path))
        self.delete(self.manager, reg)
        self.assertFalse(os.path.exists(path))
        self.assertFalse(os.path.exists(folder), 'the per-candidate folder is left behind')

    def test_files_survive_a_refused_delete(self):
        reg = self.registration(center=self.sibling)
        path = reg.documents.get().file.path
        self.delete(self.manager, reg)                       # 404
        self.assertTrue(os.path.exists(path))

    def test_who_deleted_whom_is_logged(self):
        reg = self.registration()
        reference = reg.reference
        self.delete(self.manager, reg)
        entry = ActivityLog.objects.get(action=ActivityLog.REGISTRATION_DELETED)
        self.assertEqual(entry.actor_label, 'm@x.dz')
        self.assertIn(reference, entry.target)
        self.assertEqual(entry.center, self.branch)


class DeletingARequiredDocument(DeletionTestBase):
    def delete(self, doc):
        self.client.force_authenticate(self.national)
        return self.client.delete(f'/api/admin/required-documents/{doc.pk}/')

    def test_an_unused_document_is_deleted(self):
        spare = RequiredDocument.objects.create(
            key='spare', label_ar='x', label_en='x', label_vi='x')
        self.assertEqual(self.delete(spare).status_code, 204)
        self.assertFalse(RequiredDocument.objects.filter(pk=spare.pk).exists())

    def test_a_document_candidates_uploaded_is_refused_in_words(self):
        """It used to escape as a bare 500."""
        self.registration()
        self.registration()
        response = self.delete(self.doc_type)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'DOCUMENT_IN_USE')
        self.assertEqual(response.json()['uploads'], 2)

    def test_the_refusal_keeps_the_uploads(self):
        self.registration()
        self.delete(self.doc_type)
        self.assertTrue(RequiredDocument.objects.filter(pk=self.doc_type.pk).exists())
        self.assertEqual(UploadedDocument.objects.count(), 1)

    def test_a_president_cannot_delete_document_types(self):
        spare = RequiredDocument.objects.create(
            key='spare', label_ar='x', label_en='x', label_vi='x')
        self.client.force_authenticate(self.president)
        response = self.client.delete(f'/api/admin/required-documents/{spare.pk}/')
        self.assertEqual(response.status_code, 403)
