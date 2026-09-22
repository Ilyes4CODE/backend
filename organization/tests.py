"""The access hierarchy, proved rule by rule.

    national administrator  — all of Algeria
      └ club president      — their club and every branch in it
          └ branch manager  — their branch (فرع) and nothing else

The rule: you see your own level and everything beneath it. Never above, never
sideways. Every test here pins one consequence of that rule at the API, because
the API is the guarantee — a hidden button in the dashboard is not.

Fixture used throughout:

    Ouargla club  ── Khafji   (k1)       president: ouargla@
                  ├─ Lassilis (l1)       managers:  khafji@, lassilis@
                  └─ no branch (o0)
    Alger club    ── Harrach  (a1)       president: alger@
"""

import io
import shutil
import tempfile
from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from competitions.models import Competition, Participant
from registrations.categorization import categorize
from registrations.models import Registration, RequiredDocument, UploadedDocument

from .models import ActivityLog, Center, Club, TrainingGroup, UserProfile, Wilaya

User = get_user_model()
PASSWORD = 'Str0ng-Pass-2026!'


def make_user(email, role, club=None, center=None):
    user = User.objects.create_user(email, email=email, password=PASSWORD)
    UserProfile.objects.create(user=user, role=role, club=club, center=center)
    return user


def make_registration(club, center, first):
    birth = date(2000, 1, 1)
    category, is_minor, age = categorize(birth)
    return Registration.objects.create(
        club=club, center=center, first_name=first, last_name='Test',
        latin_full_name=f'{first} Test', gender='MALE', birth_date=birth,
        birth_place='X', address='Y', phone='0555000000',
        category=category, is_minor=is_minor, age_at_registration=age,
    )


class HierarchyFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        ouargla = Wilaya.objects.create(code=30, name_ar='ورقلة', name_en='Ouargla')
        alger = Wilaya.objects.create(code=16, name_ar='الجزائر', name_en='Alger')

        cls.ouargla_club = Club.objects.create(wilaya=ouargla, name_ar='نادي ورقلة', name_en='Ouargla Club')
        cls.alger_club = Club.objects.create(wilaya=alger, name_ar='نادي الجزائر', name_en='Alger Club')

        cls.khafji = Center.objects.create(club=cls.ouargla_club, name_ar='الخفجي', name_en='Khafji')
        cls.lassilis = Center.objects.create(club=cls.ouargla_club, name_ar='لاسيليس', name_en='Lassilis')
        cls.harrach = Center.objects.create(club=cls.alger_club, name_ar='الحراش', name_en='Harrach')

        cls.national = make_user('national@dz', UserProfile.SUPER_ADMIN)
        cls.ouargla_pres = make_user('ouargla@dz', UserProfile.CLUB_OWNER, club=cls.ouargla_club)
        cls.alger_pres = make_user('alger@dz', UserProfile.CLUB_OWNER, club=cls.alger_club)
        cls.khafji_mgr = make_user('khafji@dz', UserProfile.BRANCH_MANAGER,
                                   club=cls.ouargla_club, center=cls.khafji)
        cls.lassilis_mgr = make_user('lassilis@dz', UserProfile.BRANCH_MANAGER,
                                     club=cls.ouargla_club, center=cls.lassilis)

        cls.k1 = make_registration(cls.ouargla_club, cls.khafji, 'Khafjiboy')
        cls.l1 = make_registration(cls.ouargla_club, cls.lassilis, 'Lassilisboy')
        cls.o0 = make_registration(cls.ouargla_club, None, 'Unassigned')
        cls.a1 = make_registration(cls.alger_club, cls.harrach, 'Algerboy')

    def as_(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def references(self, user):
        rows = self.as_(user).get('/api/admin/registrations/').json()['results']
        return sorted(r['first_name'] for r in rows)


# ── Seeing candidates ──────────────────────────────────────────────────────

class CandidateVisibilityTests(HierarchyFixture):
    def test_national_admin_sees_all_of_algeria(self):
        self.assertEqual(self.references(self.national),
                         ['Algerboy', 'Khafjiboy', 'Lassilisboy', 'Unassigned'])

    def test_president_sees_every_branch_of_their_club_and_nothing_else(self):
        self.assertEqual(self.references(self.ouargla_pres),
                         ['Khafjiboy', 'Lassilisboy', 'Unassigned'])

    def test_branch_manager_sees_only_their_branch(self):
        self.assertEqual(self.references(self.khafji_mgr), ['Khafjiboy'])
        self.assertEqual(self.references(self.lassilis_mgr), ['Lassilisboy'])

    def test_branch_manager_cannot_open_a_sibling_branchs_candidate(self):
        response = self.as_(self.khafji_mgr).get(f'/api/admin/registrations/{self.l1.pk}/')
        self.assertEqual(response.status_code, 404)

    def test_branch_manager_cannot_open_another_clubs_candidate(self):
        response = self.as_(self.khafji_mgr).get(f'/api/admin/registrations/{self.a1.pk}/')
        self.assertEqual(response.status_code, 404)

    def test_unassigned_candidates_belong_to_the_president_not_a_branch(self):
        response = self.as_(self.khafji_mgr).get(f'/api/admin/registrations/{self.o0.pk}/')
        self.assertEqual(response.status_code, 404)

    def test_filtering_by_another_branch_does_not_widen_the_view(self):
        rows = self.as_(self.khafji_mgr).get(
            f'/api/admin/registrations/?center={self.lassilis.pk}').json()['results']
        self.assertEqual(rows, [])

    def test_a_branch_manager_with_no_branch_sees_nothing(self):
        # Fails closed: a manager whose branch was removed sees nothing, not the club.
        orphan = make_user('orphan@dz', UserProfile.BRANCH_MANAGER, club=self.ouargla_club)
        self.assertEqual(self.references(orphan), [])


class StatsVisibilityTests(HierarchyFixture):
    def total(self, user):
        return self.as_(user).get('/api/admin/stats/').json()['total']

    def test_each_level_counts_only_what_it_can_see(self):
        self.assertEqual(self.total(self.national), 4)
        self.assertEqual(self.total(self.ouargla_pres), 3)
        self.assertEqual(self.total(self.alger_pres), 1)
        self.assertEqual(self.total(self.khafji_mgr), 1)

    def test_president_gets_the_per_branch_breakdown(self):
        body = self.as_(self.ouargla_pres).get('/api/admin/stats/').json()
        self.assertEqual(body['breakdown_by'], 'center')
        names = sorted(row['name'] for row in body['breakdown'])
        self.assertEqual(names, ['Khafji', 'Lassilis', '—'])


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix='bdg-hier-'))
class DocumentsBadgesAndListsTests(HierarchyFixture):
    @classmethod
    def tearDownClass(cls):
        from django.conf import settings
        super().tearDownClass()
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)

    def test_a_sibling_branchs_document_is_unreachable(self):
        kind = RequiredDocument.objects.create(label_ar='ص', label_en='Photo', label_vi='Ảnh')
        doc = UploadedDocument.objects.create(
            registration=self.l1, required_document=kind, original_name='x.pdf',
            file=SimpleUploadedFile('x.pdf', b'%PDF-1.4 test'),
        )
        url = f'/api/admin/documents/{doc.pk}/download/'
        self.assertEqual(self.as_(self.khafji_mgr).get(url).status_code, 404)
        self.assertEqual(self.as_(self.lassilis_mgr).get(url).status_code, 200)
        self.assertEqual(self.as_(self.ouargla_pres).get(url).status_code, 200)

    def test_badges_follow_the_branch(self):
        Registration.objects.filter(pk__in=[self.k1.pk, self.l1.pk]).update(payment_status='PAID')
        client = self.as_(self.khafji_mgr)
        self.assertEqual(client.get(f'/api/admin/registrations/{self.k1.pk}/badge/').status_code, 200)
        self.assertEqual(client.get(f'/api/admin/registrations/{self.l1.pk}/badge/').status_code, 404)

    def test_printed_list_holds_only_the_branch(self):
        from pypdf import PdfReader
        pdf = self.as_(self.khafji_mgr).get('/api/admin/registrations-print/').content
        text = ''.join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)
        self.assertIn(self.k1.reference, text)
        self.assertNotIn(self.l1.reference, text)
        self.assertNotIn(self.a1.reference, text)


# ── Changing candidates ────────────────────────────────────────────────────

class CandidateChangeTests(HierarchyFixture):
    def test_branch_manager_can_mark_their_own_candidate_paid(self):
        response = self.as_(self.khafji_mgr).patch(
            f'/api/admin/registrations/{self.k1.pk}/', {'payment_status': 'PAID'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Registration.objects.get(pk=self.k1.pk).payment_status, 'PAID')

    def test_marking_paid_is_logged_with_who_did_it(self):
        self.as_(self.khafji_mgr).patch(
            f'/api/admin/registrations/{self.k1.pk}/', {'payment_status': 'PAID'}, format='json')
        entry = ActivityLog.objects.get(action=ActivityLog.REGISTRATION_PAYMENT)
        self.assertEqual(entry.actor_label, 'khafji@dz')
        self.assertEqual(entry.target, self.k1.reference)
        self.assertEqual(entry.detail, {'from': 'UNPAID', 'to': 'PAID'})

    def test_branch_manager_cannot_change_a_sibling_branchs_candidate(self):
        response = self.as_(self.khafji_mgr).patch(
            f'/api/admin/registrations/{self.l1.pk}/', {'payment_status': 'PAID'}, format='json')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Registration.objects.get(pk=self.l1.pk).payment_status, 'UNPAID')

    def test_branch_manager_cannot_move_a_member_to_another_branch(self):
        response = self.as_(self.khafji_mgr).patch(
            f'/api/admin/registrations/{self.k1.pk}/', {'center': self.lassilis.pk}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Registration.objects.get(pk=self.k1.pk).center_id, self.khafji.pk)

    def test_president_can_move_a_member_between_their_branches(self):
        response = self.as_(self.ouargla_pres).patch(
            f'/api/admin/registrations/{self.k1.pk}/', {'center': self.lassilis.pk}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Registration.objects.get(pk=self.k1.pk).center_id, self.lassilis.pk)
        self.assertTrue(ActivityLog.objects.filter(
            action=ActivityLog.REGISTRATION_TRANSFER, target=self.k1.reference).exists())

    def test_president_cannot_move_a_member_into_another_clubs_branch(self):
        response = self.as_(self.ouargla_pres).patch(
            f'/api/admin/registrations/{self.k1.pk}/', {'center': self.harrach.pk}, format='json')
        self.assertEqual(response.status_code, 400)


# ── Branches ───────────────────────────────────────────────────────────────

class BranchManagementTests(HierarchyFixture):
    def test_president_opens_a_branch_in_their_own_club_whatever_they_send(self):
        response = self.as_(self.ouargla_pres).post('/api/admin/centers/', {
            'club': self.alger_club.pk, 'name_ar': 'تقرت', 'name_en': 'Touggourt',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Center.objects.get(name_en='Touggourt').club, self.ouargla_club)

    def test_president_cannot_touch_another_clubs_branch(self):
        response = self.as_(self.ouargla_pres).patch(
            f'/api/admin/centers/{self.harrach.pk}/', {'name_en': 'Hijacked'}, format='json')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Center.objects.get(pk=self.harrach.pk).name_en, 'Harrach')

    def test_branch_manager_cannot_open_branches(self):
        response = self.as_(self.khafji_mgr).post('/api/admin/centers/', {
            'club': self.ouargla_club.pk, 'name_ar': 'x', 'name_en': 'Rogue',
        }, format='json')
        self.assertEqual(response.status_code, 403)

    def test_branch_manager_sees_only_their_own_branch_in_the_list(self):
        rows = self.as_(self.khafji_mgr).get('/api/admin/centers/').json()
        self.assertEqual([row['name_en'] for row in rows], ['Khafji'])

    def test_president_sees_all_their_branches_with_their_managers(self):
        rows = self.as_(self.ouargla_pres).get('/api/admin/centers/').json()
        by_name = {row['name_en']: row for row in rows}
        self.assertEqual(sorted(by_name), ['Khafji', 'Lassilis'])
        self.assertEqual([m['email'] for m in by_name['Khafji']['managers']], ['khafji@dz'])

    def test_deleting_a_branch_switches_off_its_managers(self):
        response = self.as_(self.ouargla_pres).delete(f'/api/admin/centers/{self.lassilis.pk}/')
        self.assertEqual(response.status_code, 204)
        self.lassilis_mgr.refresh_from_db()
        self.assertFalse(self.lassilis_mgr.is_active)


# ── Accounts ───────────────────────────────────────────────────────────────

class AccountManagementTests(HierarchyFixture):
    def create_account(self, as_user, **fields):
        payload = {'email': 'new@club.dz', 'password': PASSWORD, 'full_name': 'New',
                   'role': UserProfile.BRANCH_MANAGER, 'center': self.khafji.pk}
        payload.update(fields)
        return self.as_(as_user).post('/api/admin/users/', payload, format='json')

    def test_president_creates_a_branch_manager_who_can_then_log_in(self):
        created = self.create_account(self.ouargla_pres)
        self.assertEqual(created.status_code, 201, created.content)
        token = APIClient().post('/api/auth/token/',
                                 {'username': 'new@club.dz', 'password': PASSWORD}, format='json')
        self.assertEqual(token.status_code, 200)
        profile = UserProfile.objects.get(user__email='new@club.dz')
        self.assertEqual((profile.club, profile.center), (self.ouargla_club, self.khafji))

    def test_president_cannot_create_a_manager_for_another_clubs_branch(self):
        self.assertEqual(self.create_account(self.ouargla_pres, center=self.harrach.pk).status_code, 400)

    def test_president_cannot_create_a_president(self):
        response = self.create_account(self.ouargla_pres, role=UserProfile.CLUB_OWNER,
                                       club=self.ouargla_club.pk, center=None)
        self.assertEqual(response.status_code, 400)

    def test_president_cannot_create_a_national_admin(self):
        response = self.create_account(self.ouargla_pres, role=UserProfile.SUPER_ADMIN, center=None)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(email='new@club.dz').exists())

    def test_an_account_needs_a_password(self):
        self.assertEqual(self.create_account(self.ouargla_pres, password='').status_code, 400)

    def test_president_sees_only_their_own_clubs_branch_managers(self):
        rows = self.as_(self.ouargla_pres).get('/api/admin/users/').json()
        self.assertEqual(sorted(r['email'] for r in rows), ['khafji@dz', 'lassilis@dz'])

    def test_president_cannot_see_or_edit_the_national_admin(self):
        response = self.as_(self.ouargla_pres).patch(
            f'/api/admin/users/{self.national.pk}/', {'full_name': 'x'}, format='json')
        self.assertEqual(response.status_code, 404)

    def test_president_cannot_see_another_presidents_account(self):
        response = self.as_(self.ouargla_pres).get(f'/api/admin/users/{self.alger_pres.pk}/')
        self.assertEqual(response.status_code, 404)

    def test_president_deactivates_but_never_deletes(self):
        client = self.as_(self.ouargla_pres)
        self.assertEqual(client.delete(f'/api/admin/users/{self.khafji_mgr.pk}/').status_code, 403)
        response = client.patch(f'/api/admin/users/{self.khafji_mgr.pk}/',
                                {'is_active': False}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(pk=self.khafji_mgr.pk).exists())

    def test_a_deactivated_manager_can_no_longer_log_in(self):
        self.as_(self.ouargla_pres).patch(f'/api/admin/users/{self.khafji_mgr.pk}/',
                                          {'is_active': False}, format='json')
        token = APIClient().post('/api/auth/token/',
                                 {'username': 'khafji@dz', 'password': PASSWORD}, format='json')
        self.assertEqual(token.status_code, 401)

    def test_a_token_issued_before_deactivation_stops_working(self):
        access = APIClient().post('/api/auth/token/', {'username': 'khafji@dz', 'password': PASSWORD},
                                  format='json').json()['access']
        self.as_(self.ouargla_pres).patch(f'/api/admin/users/{self.khafji_mgr.pk}/',
                                          {'is_active': False}, format='json')
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        self.assertEqual(client.get('/api/admin/registrations/').status_code, 401)

    def test_branch_manager_cannot_manage_accounts(self):
        self.assertEqual(self.as_(self.khafji_mgr).get('/api/admin/users/').status_code, 403)
        self.assertEqual(self.create_account(self.khafji_mgr).status_code, 403)


# ── Club-wide screens are not a branch manager's ──────────────────────────

class BranchManagerBoundaryTests(HierarchyFixture):
    def test_club_level_screens_are_closed_to_branch_managers(self):
        client = self.as_(self.khafji_mgr)
        for url in ('/api/admin/clubs/', '/api/admin/competitions/', '/api/admin/posts/',
                    '/api/admin/gallery/', '/api/admin/comments/'):
            with self.subTest(url=url):
                self.assertEqual(client.get(url).status_code, 403)

    def test_identity_tells_the_dashboard_who_this_is(self):
        me = self.as_(self.khafji_mgr).get('/api/auth/me/').json()
        self.assertTrue(me['is_branch_manager'])
        self.assertFalse(me['is_super_admin'])
        self.assertEqual(me['center_name'], 'Khafji')


# ── Groups and sessions ───────────────────────────────────────────────────

class GroupScopingTests(HierarchyFixture):
    def test_branch_manager_groups_are_pinned_to_their_branch(self):
        response = self.as_(self.khafji_mgr).post('/api/admin/groups/', {
            'club': self.alger_club.pk, 'center': self.lassilis.pk,
            'name_ar': 'فوج', 'name_en': 'Morning',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        group = TrainingGroup.objects.get(name_en='Morning')
        self.assertEqual((group.club, group.center), (self.ouargla_club, self.khafji))

    def test_branch_manager_sees_only_their_branchs_groups(self):
        TrainingGroup.objects.create(club=self.ouargla_club, center=self.lassilis,
                                     name_ar='ل', name_en='Lassilis group')
        TrainingGroup.objects.create(club=self.ouargla_club, center=self.khafji,
                                     name_ar='خ', name_en='Khafji group')
        rows = self.as_(self.khafji_mgr).get('/api/admin/groups/').json()
        self.assertEqual([r['name_en'] for r in rows], ['Khafji group'])

    def test_branch_manager_cannot_enrol_a_sibling_branchs_candidate(self):
        group = TrainingGroup.objects.create(club=self.ouargla_club, center=self.khafji,
                                             name_ar='خ', name_en='Khafji group')
        response = self.as_(self.khafji_mgr).post(
            f'/api/admin/groups/{group.pk}/members/', {'ids': [self.l1.pk]}, format='json')
        self.assertEqual(response.status_code, 400)


# ── Competitions (the pre-existing holes) ─────────────────────────────────

class CompetitionOwnershipTests(HierarchyFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.national_cup = Competition.objects.create(name='National Cup', type='COMBAT', club=None)
        cls.alger_event = Competition.objects.create(name='Alger Open', type='COMBAT',
                                                     club=cls.alger_club)
        cls.alger_fighter = Participant.objects.create(competition=cls.alger_event, name='Fighter')

    def test_president_can_read_the_national_championship(self):
        response = self.as_(self.ouargla_pres).get(f'/api/admin/competitions/{self.national_cup.pk}/')
        self.assertEqual(response.status_code, 200)

    def test_president_cannot_edit_or_delete_the_national_championship(self):
        client = self.as_(self.ouargla_pres)
        url = f'/api/admin/competitions/{self.national_cup.pk}/'
        self.assertEqual(client.patch(url, {'name': 'Hijacked'}, format='json').status_code, 403)
        self.assertEqual(client.delete(url).status_code, 403)
        self.assertTrue(Competition.objects.filter(pk=self.national_cup.pk, name='National Cup').exists())

    def test_president_cannot_see_another_clubs_event(self):
        response = self.as_(self.ouargla_pres).get(f'/api/admin/competitions/{self.alger_event.pk}/')
        self.assertEqual(response.status_code, 404)

    def test_president_cannot_touch_another_clubs_competitor(self):
        client = self.as_(self.ouargla_pres)
        url = f'/api/admin/participants/{self.alger_fighter.pk}/'
        self.assertEqual(client.get(url).status_code, 404)
        self.assertEqual(client.patch(url, {'name': 'Renamed'}, format='json').status_code, 404)

    def test_president_cannot_add_competitors_to_another_clubs_event(self):
        response = self.as_(self.ouargla_pres).post('/api/admin/participants/', {
            'competition': self.alger_event.pk, 'name': 'Intruder',
        }, format='json')
        self.assertIn(response.status_code, (400, 403))
        self.assertFalse(Participant.objects.filter(name='Intruder').exists())

    def test_owning_president_can_still_run_their_event(self):
        response = self.as_(self.alger_pres).patch(
            f'/api/admin/participants/{self.alger_fighter.pk}/', {'name': 'Renamed'}, format='json')
        self.assertEqual(response.status_code, 200)


# ── The activity log follows the same rule ────────────────────────────────

class ActivityLogScopingTests(HierarchyFixture):
    def test_each_level_reads_only_its_own_history(self):
        self.as_(self.khafji_mgr).patch(f'/api/admin/registrations/{self.k1.pk}/',
                                        {'status': 'APPROVED'}, format='json')
        self.as_(self.lassilis_mgr).patch(f'/api/admin/registrations/{self.l1.pk}/',
                                          {'status': 'APPROVED'}, format='json')
        self.as_(self.alger_pres).patch(f'/api/admin/registrations/{self.a1.pk}/',
                                        {'status': 'APPROVED'}, format='json')

        def targets(user):
            rows = self.as_(user).get('/api/admin/activity/').json()['results']
            return sorted(r['target'] for r in rows)

        self.assertEqual(targets(self.khafji_mgr), [self.k1.reference])
        self.assertEqual(targets(self.ouargla_pres), sorted([self.k1.reference, self.l1.reference]))
        self.assertEqual(len(targets(self.national)), 3)
