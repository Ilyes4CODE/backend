from django.conf import settings
from django.db import models


class Wilaya(models.Model):
    """An Algerian province. Seeded once; clubs are opened inside one."""

    code = models.PositiveSmallIntegerField(unique=True)
    name_ar = models.CharField(max_length=100)
    name_en = models.CharField(max_length=100)

    class Meta:
        ordering = ['code']
        verbose_name_plural = 'Wilayas'

    def __str__(self):
        return f'{self.code:02d} - {self.name_en}'


class Club(models.Model):
    """A club inside a wilaya. Each one may have an owner who signs in and sees
    only that club's registrations."""

    wilaya = models.ForeignKey(Wilaya, related_name='clubs', on_delete=models.PROTECT)
    name_ar = models.CharField(max_length=200)
    name_en = models.CharField(max_length=200)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='owned_clubs',
    )
    address = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['wilaya__code', 'name_en']
        unique_together = ('wilaya', 'name_en')

    def __str__(self):
        return f'{self.name_en} ({self.wilaya.name_en})'


class Center(models.Model):
    """A training location belonging to a club — Khafji, Lassilis, and so on."""

    club = models.ForeignKey(Club, related_name='centers', on_delete=models.CASCADE)
    name_ar = models.CharField(max_length=200)
    name_en = models.CharField(max_length=200)
    address = models.CharField(max_length=255, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name_en']
        unique_together = ('club', 'name_en')

    def __str__(self):
        return f'{self.name_en} — {self.club.name_en}'


class UserProfile(models.Model):
    """Role and scope for a dashboard account. Three levels, each seeing its own
    level and everything beneath it — never above, never sideways:

      SUPER_ADMIN     the national administrator: every wilaya, every club.
      CLUB_OWNER      a club's president: their club and all of its branches.
                      Creates the branches and the branch managers' accounts.
      BRANCH_MANAGER  one branch (فرع) of one club, and nothing else.
    """

    SUPER_ADMIN = 'SUPER_ADMIN'
    CLUB_OWNER = 'CLUB_OWNER'
    BRANCH_MANAGER = 'BRANCH_MANAGER'
    ROLE_CHOICES = [
        (SUPER_ADMIN, 'National administrator'),
        (CLUB_OWNER, 'Club president'),
        (BRANCH_MANAGER, 'Branch manager'),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, related_name='profile', on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=CLUB_OWNER)
    club = models.ForeignKey(Club, null=True, blank=True, on_delete=models.SET_NULL, related_name='staff')
    # Set only for branch managers. SET_NULL rather than CASCADE: deleting a
    # branch must not delete the person's account, and a manager left with no
    # branch sees nothing at all (the scoping fails closed).
    center = models.ForeignKey(
        'organization.Center', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='managers',
    )
    full_name = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=30, blank=True)

    def __str__(self):
        return f'{self.user.username} ({self.get_role_display()})'

    @property
    def is_super_admin(self) -> bool:
        return self.role == self.SUPER_ADMIN

    @property
    def is_club_owner(self) -> bool:
        return self.role == self.CLUB_OWNER

    @property
    def is_branch_manager(self) -> bool:
        return self.role == self.BRANCH_MANAGER


def profile_for(user):
    """Returns the user's profile, creating a super-admin one for superusers that
    predate this model (the original seeded admin account)."""
    if not user or not user.is_authenticated:
        return None
    profile = UserProfile.objects.filter(user=user).first()
    if profile is None:
        profile = UserProfile.objects.create(
            user=user,
            role=UserProfile.SUPER_ADMIN if user.is_superuser else UserProfile.CLUB_OWNER,
        )
    return profile


# Training groups and their weekly timetable live in their own module for
# readability; re-exported here so `organization.models` stays the single
# import point and Django picks the models up.
from .training import TrainingGroup, WeeklySession  # noqa: E402,F401
from .activity import ActivityLog  # noqa: E402,F401
