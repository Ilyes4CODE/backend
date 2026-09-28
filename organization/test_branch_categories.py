"""Each branch opens its own registrations, category by category.

What matters here is that the window is enforced where a candidate cannot get
round it — on submission — and that only the people who run a branch can move
it.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from registrations.models import Registration, SiteSettings

from .models import CATEGORY_CODES, Center, Club, UserProfile, Wilaya

User = get_user_model()


def adult_birth_date():
    return date(date.today().year - 30, 1, 1)      # SENIOR


def poussin_birth_date():
    return date(date.today().year - 10, 1, 1)      # POUSSIN, a minor


def payload(club, center=None, *, birth_date=None, minor=False):
    data = {
        'club': club.pk,
        'first_name': 'Amine', 'last_name': 'Benali', 'latin_full_name': 'Amine Benali',
        'gender': 'MALE', 'birth_date': (birth_date or adult_birth_date()).isoformat(),
        'birth_place': 'Ouargla', 'address': 'Rue 1', 'phone': '0555000000',
    }
    if center is not None:
        data['center'] = center.pk
    if minor:
        data.update(parent_name='Parent', parent_id_type='CNI',
                    parent_id_number='123', parent_id_issue_date='2015-01-01')
    return data


def staff(email, role, club=None, center=None):
    user = User.objects.create_user(email, email, 'pw-for-tests')
    UserProfile.objects.create(user=user, role=role, club=club, center=center)
    return user


class BranchCategoriesTestBase(TestCase):
    def setUp(self):
        wilaya = Wilaya.objects.create(code=30, name_ar='ورقلة', name_en='Ouargla')
        other_wilaya = Wilaya.objects.create(code=16, name_ar='الجزائر', name_en='Alger')
        self.club = Club.objects.create(wilaya=wilaya, name_ar='نادي', name_en='Club')
        self.other_club = Club.objects.create(wilaya=other_wilaya, name_ar='آخر', name_en='Other')
        self.branch = Center.objects.create(club=self.club, name_ar='فرع', name_en='North')
        self.sibling = Center.objects.create(club=self.club, name_ar='فرع ٢', name_en='South')
        self.foreign = Center.objects.create(club=self.other_club, name_ar='فرع ٣', name_en='East')

        self.national = staff('national@x.dz', UserProfile.SUPER_ADMIN)
        self.president = staff('president@x.dz', UserProfile.CLUB_OWNER, club=self.club)
        self.manager = staff('manager@x.dz', UserProfile.BRANCH_MANAGER,
                             club=self.club, center=self.branch)
        self.client = APIClient()

    def set_categories(self, user, center, categories):
        self.client.force_authenticate(user)
        return self.client.patch(
            f'/api/admin/centers/{center.pk}/categories/',
            {'open_categories': categories}, format='json')


class DefaultsAndStorage(BranchCategoriesTestBase):
    def test_a_new_branch_takes_every_category(self):
        self.assertEqual(self.branch.open_categories, CATEGORY_CODES)

    def test_branches_do_not_share_one_list(self):
        """The default is a callable; a list literal would be shared."""
        self.branch.open_categories.remove('SENIOR')
        self.assertIn('SENIOR', Center.objects.get(pk=self.sibling.pk).open_categories)

    def test_stored_in_federation_order_once_each(self):
        response = self.set_categories(
            self.manager, self.branch, ['VETERAN', 'SENIOR', 'VETERAN'])
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['open_categories'], ['SENIOR', 'VETERAN'])

    def test_an_unknown_category_is_refused(self):
        response = self.set_categories(self.manager, self.branch, ['SENIOR', 'TODDLER'])
        self.assertEqual(response.status_code, 400)
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.open_categories, CATEGORY_CODES)

    def test_closing_everything_is_allowed(self):
        response = self.set_categories(self.manager, self.branch, [])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['open_categories'], [])


class WhoMayMoveTheWindow(BranchCategoriesTestBase):
    def test_the_branch_manager_runs_their_own_branch(self):
        self.assertEqual(self.set_categories(self.manager, self.branch, ['SENIOR']).status_code, 200)

    def test_a_branch_manager_cannot_touch_a_sibling_branch(self):
        """Sideways inside the same club: invisible, so 404 rather than 403."""
        self.assertEqual(self.set_categories(self.manager, self.sibling, ['SENIOR']).status_code, 404)
        self.sibling.refresh_from_db()
        self.assertEqual(self.sibling.open_categories, CATEGORY_CODES)

    def test_the_president_runs_every_branch_of_their_club(self):
        self.assertEqual(self.set_categories(self.president, self.sibling, ['JUNIOR']).status_code, 200)

    def test_a_president_cannot_touch_another_clubs_branch(self):
        self.assertEqual(self.set_categories(self.president, self.foreign, ['SENIOR']).status_code, 404)

    def test_the_national_admin_runs_any_branch(self):
        self.assertEqual(self.set_categories(self.national, self.foreign, ['CADET']).status_code, 200)

    def test_anonymous_callers_are_refused(self):
        response = APIClient().patch(
            f'/api/admin/centers/{self.branch.pk}/categories/',
            {'open_categories': []}, format='json')
        self.assertEqual(response.status_code, 401)

    def test_the_endpoint_changes_nothing_but_the_windows(self):
        """A branch manager still may not rename their branch through it."""
        self.client.force_authenticate(self.manager)
        self.client.patch(f'/api/admin/centers/{self.branch.pk}/categories/',
                          {'open_categories': ['SENIOR'], 'name_en': 'Renamed'}, format='json')
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.name_en, 'North')

    def test_a_branch_manager_still_cannot_edit_the_branch_itself(self):
        self.client.force_authenticate(self.manager)
        response = self.client.patch(f'/api/admin/centers/{self.branch.pk}/',
                                     {'name_en': 'Renamed'}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_changes_are_logged(self):
        from .activity import ActivityLog

        self.set_categories(self.manager, self.branch, ['SENIOR'])
        entry = ActivityLog.objects.filter(action=ActivityLog.BRANCH_UPDATED).latest('id')
        self.assertEqual(entry.detail['opened'], [])
        self.assertIn('POUSSIN', entry.detail['closed'])


class TheWindowIsEnforcedOnSubmission(BranchCategoriesTestBase):
    def submit(self, data):
        return APIClient().post('/api/registrations/', data, format='multipart')

    def test_an_open_category_goes_through(self):
        response = self.submit(payload(self.club, self.branch))
        self.assertEqual(response.status_code, 201, response.content)

    def test_a_closed_category_is_refused(self):
        self.set_categories(self.manager, self.branch, ['POUSSIN'])
        response = self.submit(payload(self.club, self.branch))           # an adult
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['code'], 'CATEGORY_CLOSED')
        self.assertEqual(response.json()['category'], 'SENIOR')
        self.assertFalse(Registration.objects.exists())

    def test_the_same_category_can_be_open_at_a_sibling(self):
        self.set_categories(self.manager, self.branch, ['POUSSIN'])
        response = self.submit(payload(self.club, self.sibling))
        self.assertEqual(response.status_code, 201, response.content)

    def test_a_minor_is_checked_against_their_own_category(self):
        self.set_categories(self.manager, self.branch, ['SENIOR'])
        response = self.submit(
            payload(self.club, self.branch, birth_date=poussin_birth_date(), minor=True))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['category'], 'POUSSIN')

    def test_a_club_with_branches_needs_one_chosen(self):
        """Otherwise the club-only path goes round every window."""
        self.set_categories(self.manager, self.branch, [])
        self.set_categories(self.president, self.sibling, [])
        response = self.submit(payload(self.club))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'CENTER_REQUIRED')
        self.assertFalse(Registration.objects.exists())

    def test_a_club_with_no_branches_still_takes_candidates(self):
        lone = Club.objects.create(wilaya=self.club.wilaya, name_ar='وحيد', name_en='Lone')
        response = self.submit(payload(lone))
        self.assertEqual(response.status_code, 201, response.content)

    def test_an_inactive_branch_takes_nobody(self):
        self.branch.active = False
        self.branch.save()
        response = self.submit(payload(self.club, self.branch))
        self.assertEqual(response.json()['code'], 'CATEGORY_CLOSED')

    def test_the_national_switch_still_overrides_every_branch(self):
        settings = SiteSettings.load()
        settings.registrations_open = False
        settings.save()
        response = self.submit(payload(self.club, self.branch))
        self.assertEqual(response.json()['code'], 'REGISTRATIONS_CLOSED')


class ThePublicDirectory(BranchCategoriesTestBase):
    def centers(self):
        clubs = APIClient().get('/api/directory/').json()['clubs']
        return next(c for c in clubs if c['id'] == self.club.pk)['centers']

    def test_it_tells_the_form_which_categories_each_branch_takes(self):
        self.set_categories(self.manager, self.branch, ['JUNIOR'])
        north = next(c for c in self.centers() if c['id'] == self.branch.pk)
        self.assertEqual(north['open_categories'], ['JUNIOR'])

    def test_it_does_not_expose_the_branch_managers(self):
        """It used to: every manager's email, name and last login, to anyone."""
        for center in self.centers():
            self.assertNotIn('managers', center)
            self.assertNotIn('registration_count', center)
        self.assertNotIn('manager@x.dz', APIClient().get('/api/directory/').content.decode())
