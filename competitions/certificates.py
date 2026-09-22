"""Competition certificates.

Two kinds, as the club asked: an achievement diploma for the first three places
(gold, silver, bronze — and both bronzes, since the regulations put the two
semi-final losers on the third step together), and a participation certificate
for everyone else who competed.

Every competitor's PDF carries three pages — Arabic, English and Vietnamese —
so one file serves the whole federation.
"""

import io
from pathlib import Path

from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

from registrations.models import SiteSettings
from registrations.typography import fonts_for, register_fonts, resolve

from .bracket import standings

PAGE_W, PAGE_H = landscape(A4)
MM = 2.834645669

LOGO = Path(__file__).resolve().parent.parent / 'registrations' / 'assets' / 'logo.png'

LANGUAGES = ('ar', 'en', 'vi')

# Ribbon colour per award.
AWARD_COLOURS = {
    'GOLD': (0.85, 0.65, 0.13),
    'SILVER': (0.62, 0.62, 0.65),
    'BRONZE': (0.72, 0.45, 0.20),
    'PARTICIPATION': (0.13, 0.13, 0.13),
}

TEXT = {
    'ar': {
        'republic': 'الجمهورية الجزائرية الديمقراطية الشعبية',
        'ministry': 'وزارة الشباب و الرياضة',
        'title_award': 'شهادة تتويج',
        'title_participation': 'شهادة مشاركة',
        'awarded_to': 'تُمنح هذه الشهادة إلى',
        'season': 'الموسم الرياضي',
        'club_president': 'رئيس النادي',
        'committee': 'رئيس اللجنة المنظمة',
        'awards': {
            'GOLD': 'المرتبة الأولى',
            'SILVER': 'المرتبة الثانية',
            'BRONZE': 'المرتبة الثالثة',
            'PARTICIPATION': 'شهادة مشاركة',
        },
    },
    'en': {
        'republic': "People's Democratic Republic of Algeria",
        'ministry': 'Ministry of Youth and Sports',
        'title_award': 'Certificate of Achievement',
        'title_participation': 'Certificate of Participation',
        'awarded_to': 'This certificate is awarded to',
        'season': 'Season',
        'club_president': 'Club president',
        'committee': 'Organising committee',
        'awards': {
            'GOLD': 'First place',
            'SILVER': 'Second place',
            'BRONZE': 'Third place',
            'PARTICIPATION': 'Participation',
        },
    },
    'vi': {
        'republic': 'Cộng hòa Dân chủ Nhân dân Algeria',
        'ministry': 'Bộ Thanh niên và Thể thao',
        'title_award': 'Giấy chứng nhận thành tích',
        'title_participation': 'Giấy chứng nhận tham dự',
        'awarded_to': 'Giấy chứng nhận này được trao cho',
        'season': 'Mùa giải',
        'club_president': 'Chủ nhiệm câu lạc bộ',
        'committee': 'Ban tổ chức',
        'awards': {
            'GOLD': 'Hạng nhất',
            'SILVER': 'Hạng nhì',
            'BRONZE': 'Hạng ba',
            'PARTICIPATION': 'Tham dự',
        },
    },
}

DEFAULT_CLUB_NAME = {
    'ar': 'النادي الرياضي للهواة مدرسة الجنوب للبيندين زا',
    'en': 'École du Sud — Binh Dinh Gia',
    'vi': 'École du Sud — Bình Định Gia',
}


def _award_for(competition, participant):
    """GOLD / SILVER / BRONZE for a medallist, otherwise PARTICIPATION."""
    if competition.is_combat:
        for row in standings(competition):
            if row['participant'].id == participant.id:
                return row['medal'], row['place']
    else:
        scored = [p for p in competition.performances.all() if p.final_score is not None]
        scored.sort(key=lambda p: p.final_score, reverse=True)
        medals = ['GOLD', 'SILVER', 'BRONZE']
        for index, performance in enumerate(scored):
            if performance.participant_id == participant.id:
                return (medals[index], index + 1) if index < 3 else ('PARTICIPATION', index + 1)
    return 'PARTICIPATION', None


def _club_name(competition, language: str) -> str:
    club = competition.club
    if club is None:
        return DEFAULT_CLUB_NAME[language]
    return club.name_ar if language == 'ar' else club.name_en


def _draw_certificate(c: canvas.Canvas, competition, participant, award: str, place, language: str):
    words = TEXT[language]
    colour = AWARD_COLOURS[award]
    centre = PAGE_W / 2

    def centred(text, y, size, bold=False, fill=None):
        # resolve() picks the font from the script of the text itself, so an
        # Arabic name still renders on the English and Vietnamese pages.
        drawn, regular_font, bold_font = resolve(text, language)
        c.setFont(bold_font if bold else regular_font, size)
        if fill is None:
            c.setFillGray(0)
        else:
            c.setFillColorRGB(*fill)
        c.drawCentredString(centre, y, drawn)

    # Double border in the award colour
    c.setStrokeColorRGB(*colour)
    c.setLineWidth(3)
    c.rect(12 * MM, 12 * MM, PAGE_W - 24 * MM, PAGE_H - 24 * MM)
    c.setLineWidth(0.8)
    c.rect(15 * MM, 15 * MM, PAGE_W - 30 * MM, PAGE_H - 30 * MM)

    if LOGO.exists():
        size = 26 * MM
        c.drawImage(str(LOGO), centre - size / 2, PAGE_H - 48 * MM, width=size, height=size, mask='auto')

    centred(words['republic'], PAGE_H - 55 * MM, 10)
    centred(words['ministry'], PAGE_H - 61 * MM, 9)
    centred(_club_name(competition, language), PAGE_H - 68 * MM, 10.5, bold=True)

    is_award = place is not None
    centred(words['title_award'] if is_award else words['title_participation'],
            PAGE_H - 88 * MM, 28, bold=True, fill=colour)

    centred(words['awarded_to'], PAGE_H - 106 * MM, 11, fill=(0.35, 0.35, 0.35))
    centred(participant.name, PAGE_H - 121 * MM, 26, bold=True)

    if participant.club:
        centred(participant.club, PAGE_H - 130 * MM, 11, fill=(0.4, 0.4, 0.4))

    detail = (
        competition.get_weight_class_display() if competition.is_combat
        else competition.get_technique_event_display()
    )
    line = f'{competition.name} — {detail}' if detail else competition.name
    centred(line, PAGE_H - 145 * MM, 12, fill=(0.2, 0.2, 0.2))
    centred(words['awards'][award], PAGE_H - 157 * MM, 16, bold=True, fill=colour)

    season = competition.season or SiteSettings.load().active_season
    centred(f"{words['season']}: {season}", 30 * MM, 10, fill=(0.35, 0.35, 0.35))

    # Signature blocks
    c.setFillGray(0)
    for text, x in ((words['club_president'], PAGE_W / 4), (words['committee'], 3 * PAGE_W / 4)):
        drawn, regular_font, _ = resolve(text, language)
        c.setFont(regular_font, 10)
        c.drawCentredString(x, 22 * MM, drawn)
        c.setStrokeGray(0.6)
        c.setLineWidth(0.5)
        c.line(x - 25 * MM, 26 * MM, x + 25 * MM, 26 * MM)

    # Quiet language marker, so a printed stack is easy to sort
    c.setFillGray(0.65)
    c.setFont(fonts_for('en')[0], 7.5)
    c.drawRightString(PAGE_W - 18 * MM, 17 * MM, language.upper())


def _draw_all_languages(c: canvas.Canvas, competition, participant, award, place):
    """One page per language for a single competitor."""
    for language in LANGUAGES:
        _draw_certificate(c, competition, participant, award, place, language)
        c.showPage()


def generate_certificate(competition, participant) -> io.BytesIO:
    """One competitor: Arabic, English and Vietnamese, in that order."""
    register_fonts()
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=landscape(A4))
    award, place = _award_for(competition, participant)
    _draw_all_languages(c, competition, participant, award, place)
    c.save()
    buffer.seek(0)
    return buffer


def generate_all_certificates(competition) -> io.BytesIO:
    """Every competitor, three pages each, medallists first."""
    register_fonts()
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=landscape(A4))

    entrants = list(competition.participants.filter(withdrawn=False))
    order = {'GOLD': 0, 'SILVER': 1, 'BRONZE': 2, 'PARTICIPATION': 3}
    decorated = [(participant,) + _award_for(competition, participant) for participant in entrants]
    decorated.sort(key=lambda row: (order[row[1]], row[0].name))

    for participant, award, place in decorated:
        _draw_all_languages(c, competition, participant, award, place)

    c.save()
    buffer.seek(0)
    return buffer
