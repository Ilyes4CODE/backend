"""Age-category and minority rules for the club, as given by the federation breakdown.

Adultes: Seniors 18-34 inclus, Veterans 35+.
Jeunes: Juniors <19 & >=17, Cadets <17 & >=15, Minimes <15 & >=13,
        Benjamins <13 & >=11, Poussins <11 & >=9, Minibad <9.

The Juniors (17-18) and Seniors (18-34) brackets overlap at age 18 in the source
breakdown. Youth brackets are checked first, so an 18-year-old lands in Juniors
rather than Seniors - this is the club's existing convention for that boundary age.
"""

from datetime import date


SENIOR = 'SENIOR'
VETERAN = 'VETERAN'
JUNIOR = 'JUNIOR'
CADET = 'CADET'
MINIME = 'MINIME'
BENJAMIN = 'BENJAMIN'
POUSSIN = 'POUSSIN'
MINIBAD = 'MINIBAD'

CATEGORY_CHOICES = [
    (SENIOR, 'Seniors'),
    (VETERAN, 'Veterans'),
    (JUNIOR, 'Juniors'),
    (CADET, 'Cadets'),
    (MINIME, 'Minimes'),
    (BENJAMIN, 'Benjamins'),
    (POUSSIN, 'Poussins'),
    (MINIBAD, 'Minibad'),
]

MINOR_AGE_LIMIT = 18


def compute_age(birth_date: date, as_of: date | None = None) -> int:
    as_of = as_of or date.today()
    age = as_of.year - birth_date.year
    if (as_of.month, as_of.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


def compute_category(age: int) -> str:
    if age < 9:
        return MINIBAD
    if age < 11:
        return POUSSIN
    if age < 13:
        return BENJAMIN
    if age < 15:
        return MINIME
    if age < 17:
        return CADET
    if age < 19:
        return JUNIOR
    if age <= 34:
        return SENIOR
    return VETERAN


def compute_is_minor(age: int) -> bool:
    return age < MINOR_AGE_LIMIT


def categorize(birth_date: date, as_of: date | None = None) -> tuple[str, bool, int]:
    age = compute_age(birth_date, as_of)
    return compute_category(age), compute_is_minor(age), age
