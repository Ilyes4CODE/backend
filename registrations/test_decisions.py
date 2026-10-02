"""Accepting and refusing registrations, and the email that tells the candidate."""

from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from rest_framework.test import APIClient

from organization.activity import ActivityLog
from organization.models import Center, Club, UserProfile, Wilaya

from .categorization import categorize
from .models import Registration

User = get_user_model()


def staff(email, role, club=None, center=None):
    user = User.objects.create_user(email, email, 'pw-for-tests')
    UserProfile.objects.create(user=user, role=role, club=club, center=center)
    return user


class DecisionTestBase(TestCase):
    def setUp(self):
        wilaya = Wilaya.objects.create(code=30, name_ar='ورقلة', name_en='Ouargla')
        self.club = Club.objects.create(wilaya=wilaya, name_ar='نادي النجمة', name_en='Najma',
                                        email='club@najma.dz')
        self.branch = Center.objects.create(club=self.club, name_ar='الخفجي', name_en='Khafji')
        self.sibling = Center.objects.create(club=self.club, name_ar='لصيلص', name_en='Lassilis')
        self.president = staff('p@x.dz', UserProfile.CLUB_OWNER, club=self.club)
        self.manager = staff('m@x.dz', UserProfile.BRANCH_MANAGER, club=self.club, center=self.branch)
        self.client = APIClient()

    def registration(self, **kwargs):
        born = date(2000, 1, 1)
        category, is_minor, age = categorize(born)
        fields = dict(
            club=self.club, center=self.branch, first_name='أمين', last_name='بلقاسم',
            latin_full_name='Amine B', gender='MALE', birth_date=born, birth_place='x',
            address='x', phone='0555', season='2026/2027', category=category,
            is_minor=is_minor, age_at_registration=age, email='amine@example.dz', language='ar',
        )
        fields.update(kwargs)
        return Registration.objects.create(**fields)

    def approve(self, reg, user=None):
        self.client.force_authenticate(user or self.president)
        return self.client.post(f'/api/admin/registrations/{reg.pk}/approve/')

    def reject(self, reg, reason='INCOMPLETE', note='', user=None):
        self.client.force_authenticate(user or self.president)
        return self.client.post(f'/api/admin/registrations/{reg.pk}/reject/',
                                {'reason': reason, 'note': note}, format='json')


class Accepting(DecisionTestBase):
    def test_it_is_saved_and_the_candidate_emailed(self):
        reg = self.registration()
        response = self.approve(reg)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['email_result'], 'SENT')
        reg.refresh_from_db()
        self.assertEqual(reg.status, 'APPROVED')
        self.assertEqual(reg.decision_email_status, 'SENT')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['amine@example.dz'])

    def test_the_email_is_in_the_candidates_language(self):
        self.approve(self.registration(language='ar'))
        self.approve(self.registration(language='en', email='en@example.dz'))
        arabic, english = mail.outbox
        self.assertIn('تم قبول طلب انخراطك', arabic.subject)
        self.assertIn('accepted', english.subject)

    def test_it_comes_from_the_club_and_replies_go_to_it(self):
        self.approve(self.registration())
        message = mail.outbox[0]
        self.assertIn('نادي النجمة', message.from_email)
        self.assertEqual(message.reply_to, ['club@najma.dz'])

    def test_the_html_names_the_registration_and_embeds_the_logo(self):
        reg = self.registration()
        self.approve(reg)
        message = mail.outbox[0]
        html = message.alternatives[0][0]
        self.assertIn(reg.reference, html)
        self.assertIn('الخفجي', html)              # the branch, in the candidate's language
        self.assertIn('cid:logo', html)
        cids = [part['Content-ID'] for part in message.attachments if hasattr(part, 'get')]
        self.assertIn('<logo>', cids)

    def test_a_plain_text_version_comes_with_it(self):
        reg = self.registration()
        self.approve(reg)
        self.assertIn(reg.reference, mail.outbox[0].body)

    def test_it_is_logged(self):
        reg = self.registration()
        self.approve(reg)
        entry = ActivityLog.objects.get(action=ActivityLog.REGISTRATION_STATUS)
        self.assertEqual(entry.detail['to'], 'APPROVED')

    def test_accepting_twice_sends_nothing_twice(self):
        reg = self.registration()
        self.approve(reg)
        response = self.approve(reg)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(mail.outbox), 1)

    def test_a_branch_manager_decides_for_their_own_branch(self):
        self.assertEqual(self.approve(self.registration(), self.manager).status_code, 200)

    def test_but_not_for_a_sibling_branch(self):
        reg = self.registration(center=self.sibling)
        self.assertEqual(self.approve(reg, self.manager).status_code, 404)
        self.assertEqual(len(mail.outbox), 0)


class Refusing(DecisionTestBase):
    def test_the_reason_is_saved_and_emailed(self):
        reg = self.registration()
        response = self.reject(reg, 'UNREADABLE', 'شهادة الميلاد غير واضحة')
        self.assertEqual(response.status_code, 200, response.content)
        reg.refresh_from_db()
        self.assertEqual((reg.status, reg.rejection_reason), ('REJECTED', 'UNREADABLE'))
        html = mail.outbox[0].alternatives[0][0]
        self.assertIn('بعض الوثائق غير واضحة أو غير مقروءة', html)
        self.assertIn('شهادة الميلاد غير واضحة', html)

    def test_other_needs_the_reason_written(self):
        response = self.reject(self.registration(), 'OTHER', '')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)

    def test_other_with_a_note_sends_the_note_as_the_reason(self):
        self.reject(self.registration(), 'OTHER', 'Please come to the branch first.')
        html = mail.outbox[0].alternatives[0][0]
        self.assertIn('Please come to the branch first.', html)
        self.assertNotIn('سبب آخر', html)

    def test_an_unknown_reason_is_refused(self):
        self.assertEqual(self.reject(self.registration(), 'BECAUSE').status_code, 400)

    def test_accepting_after_a_refusal_clears_the_reason(self):
        reg = self.registration()
        self.reject(reg, 'INCOMPLETE', 'missing card')
        self.approve(reg)
        reg.refresh_from_db()
        self.assertEqual((reg.status, reg.rejection_reason, reg.rejection_note), ('APPROVED', '', ''))


class WhenTheEmailCannotGo(DecisionTestBase):
    def test_no_address_on_file_still_saves_the_decision(self):
        reg = self.registration(email='')
        response = self.approve(reg)
        self.assertEqual(response.json()['email_result'], 'NO_EMAIL')
        reg.refresh_from_db()
        self.assertEqual(reg.status, 'APPROVED')
        self.assertEqual(len(mail.outbox), 0)

    def test_a_mail_server_failure_keeps_the_decision_and_says_so(self):
        reg = self.registration()
        with mock.patch('django.core.mail.EmailMultiAlternatives.send', side_effect=OSError('down')):
            response = self.approve(reg)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['email_result'], 'FAILED')
        reg.refresh_from_db()
        self.assertEqual((reg.status, reg.decision_email_status), ('APPROVED', 'FAILED'))

    def test_it_can_be_sent_again(self):
        reg = self.registration()
        with mock.patch('django.core.mail.EmailMultiAlternatives.send', side_effect=OSError('down')):
            self.approve(reg)
        self.client.force_authenticate(self.president)
        response = self.client.post(f'/api/admin/registrations/{reg.pk}/resend-email/')
        self.assertEqual(response.json()['email_result'], 'SENT')
        self.assertEqual(len(mail.outbox), 1)

    def test_nothing_to_resend_before_a_decision(self):
        reg = self.registration()
        self.client.force_authenticate(self.president)
        response = self.client.post(f'/api/admin/registrations/{reg.pk}/resend-email/')
        self.assertEqual(response.status_code, 400)


class TheOldWayIsClosed(DecisionTestBase):
    def test_patch_can_no_longer_accept_without_an_email(self):
        reg = self.registration()
        self.client.force_authenticate(self.president)
        response = self.client.patch(f'/api/admin/registrations/{reg.pk}/',
                                     {'status': 'APPROVED'}, format='json')
        self.assertEqual(response.status_code, 400)
        reg.refresh_from_db()
        self.assertEqual(reg.status, 'PENDING')

    def test_patch_can_still_reopen_a_decision(self):
        reg = self.registration(status='REJECTED')
        self.client.force_authenticate(self.president)
        response = self.client.patch(f'/api/admin/registrations/{reg.pk}/',
                                     {'status': 'PENDING'}, format='json')
        self.assertEqual(response.status_code, 200)


class Privacy(DecisionTestBase):
    def test_the_public_page_does_not_show_the_email_or_the_reason(self):
        reg = self.registration()
        self.reject(reg, 'MISMATCH', 'private note')
        body = APIClient().get(f'/api/registrations/{reg.reference}/').json()
        for field in ('email', 'rejection_reason', 'rejection_note', 'decision_email_status'):
            self.assertNotIn(field, body)

    def test_staff_see_them(self):
        reg = self.registration()
        self.client.force_authenticate(self.president)
        body = self.client.get(f'/api/admin/registrations/{reg.pk}/').json()
        self.assertEqual(body['email'], 'amine@example.dz')


class TheEmailItself(DecisionTestBase):
    def test_no_template_comment_leaks_into_the_email(self):
        """A two-line {# … #} is printed literally by Django; one was."""
        for status, extra in (('approve', {}), ('reject', {'reason': 'OTHER', 'note': 'x'})):
            with self.subTest(status=status):
                mail.outbox.clear()
                reg = self.registration()
                if status == 'approve':
                    self.approve(reg)
                else:
                    self.reject(reg, **extra)
                message = mail.outbox[0]
                for text in (message.alternatives[0][0], message.body):
                    self.assertNotIn('{#', text)
                    self.assertNotIn('#}', text)
                    self.assertNotIn('{%', text)

    def test_the_illustrations_travel_inside_the_message(self):
        self.approve(self.registration())
        cids = {part['Content-ID'] for part in mail.outbox[0].attachments if hasattr(part, 'get')}
        self.assertEqual(cids, {'<logo>', '<header>', '<hero>'})

    def test_embedded_images_are_kept_small(self):
        self.approve(self.registration())
        total = sum(len(part.get_payload(decode=True)) for part in mail.outbox[0].attachments
                    if hasattr(part, 'get'))
        self.assertLess(total, 600 * 1024, f'{total // 1024} KB of images in one email')
