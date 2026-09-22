from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from organization.models import Center, Club, UserProfile, Wilaya
from organization.wilayas import ALGERIAN_WILAYAS
from registrations.models import Registration

# The club this platform was originally built for, with its known centers.
HOME_CLUB = {
    'wilaya_code': 30,
    'name_ar': 'النادي الرياضي للهواة مدرسة الجنوب للبيندين زا',
    'name_en': 'École du Sud — Binh Dinh Gia',
    'centers': [
        ('خفجي', 'Khafji'),
        ('لاسيليس', 'Lassilis'),
    ],
}


class Command(BaseCommand):
    help = 'Seed the 58 wilayas, the home club and its centers, and admin roles.'

    def handle(self, *args, **options):
        created = 0
        for code, name_ar, name_en in ALGERIAN_WILAYAS:
            _, made = Wilaya.objects.get_or_create(
                code=code, defaults={'name_ar': name_ar, 'name_en': name_en}
            )
            created += int(made)
        self.stdout.write(self.style.SUCCESS(f'Wilayas ready ({created} new, {Wilaya.objects.count()} total).'))

        ouargla = Wilaya.objects.get(code=HOME_CLUB['wilaya_code'])
        club, made = Club.objects.get_or_create(
            wilaya=ouargla,
            name_en=HOME_CLUB['name_en'],
            defaults={'name_ar': HOME_CLUB['name_ar']},
        )
        self.stdout.write(self.style.SUCCESS(f'{"Created" if made else "Found"} club: {club.name_en}'))

        for name_ar, name_en in HOME_CLUB['centers']:
            _, made = Center.objects.get_or_create(
                club=club, name_en=name_en, defaults={'name_ar': name_ar}
            )
            if made:
                self.stdout.write(self.style.SUCCESS(f'  Created center: {name_en}'))

        # Existing accounts predate roles: superusers become platform administrators.
        User = get_user_model()
        for user in User.objects.all():
            profile, made = UserProfile.objects.get_or_create(
                user=user,
                defaults={
                    'role': UserProfile.SUPER_ADMIN if user.is_superuser else UserProfile.CLUB_OWNER,
                    'club': None if user.is_superuser else club,
                },
            )
            if made:
                self.stdout.write(self.style.SUCCESS(f'  Profile for "{user.username}": {profile.role}'))

        # Registrations taken before clubs existed belong to the home club.
        orphans = Registration.objects.filter(club__isnull=True)
        if orphans.exists():
            count = orphans.update(club=club)
            self.stdout.write(self.style.SUCCESS(f'Attached {count} existing registration(s) to {club.name_en}.'))
