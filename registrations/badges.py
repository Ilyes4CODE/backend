"""Member badges.

A badge is proof of a paid-up membership for the season, so it is only issued
once the admin has marked the registration PAID. Printed two-up on A4 — the
front carries the photo, name and category; the back carries the club details
and the fee terms.
"""

import io
from pathlib import Path

import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .models import SiteSettings
from .typography import fonts_for, register_fonts, resolve

MM = 2.834645669
PAGE_W, PAGE_H = A4

# Slightly larger than a credit card, so the photo and Arabic name stay legible.
CARD_W, CARD_H = 90 * MM, 58 * MM

# Big enough to scan off a laminated card with a phone.
QR_SIZE = 21 * MM

# Transparent cut-out, so the emblem sits on the red header band without a white box.
LOGO = Path(__file__).resolve().parent / 'assets' / 'logo-transparent.png'

BRAND_RED = (0.894, 0.098, 0.114)
BRAND_GOLD = (0.984, 0.961, 0.012)

TEXT = {
    'ar': {
        'card': 'بطاقة انخراط',
        'season': 'الموسم',
        'category': 'الفئة',
        'reference': 'المرجع',
        'club': 'النادي',
        'center': 'المركز',
        'paid': 'مدفوع',
        'member': 'العضو',
        'terms': 'بطاقة شخصية، ملك للنادي. تُقدَّم عند كل حصة.',
    },
    'en': {
        'card': 'Membership card',
        'season': 'Season',
        'category': 'Category',
        'reference': 'Reference',
        'club': 'Club',
        'center': 'Center',
        'paid': 'PAID',
        'member': 'Member',
        'terms': 'Personal card, property of the club. Present at every session.',
    },
}


def _text(c, x, y, text, size, bold=False, align='left', language='en', max_width=None):
    """Draw a string, letting the script of the text choose the font.

    With `max_width`, the type shrinks to fit rather than being chopped — a long
    club name should get smaller, not lose its last word.
    """
    drawn, regular, bold_font = resolve(text, language)
    font = bold_font if bold else regular

    if max_width:
        while size > 4.5 and c.stringWidth(drawn, font, size) > max_width:
            size -= 0.25

    c.setFont(font, size)
    if align == 'right':
        c.drawRightString(x, y, drawn)
    elif align == 'center':
        c.drawCentredString(x, y, drawn)
    else:
        c.drawString(x, y, drawn)


def _photo_for(registration):
    """The candidate's own photograph for the card.

    The ID-photo upload is preferred; only if that is missing (or is a PDF) do we
    fall back to another uploaded image, so a scan of a blood-type card never
    ends up being printed as somebody's portrait.
    """
    documents = list(registration.documents.select_related('required_document'))
    documents.sort(key=lambda d: 0 if 'photo' in (d.required_document.key or '') else 1)

    for document in documents:
        name = (document.original_name or '').lower()
        if not name.endswith(('.jpg', '.jpeg', '.png')):
            continue
        try:
            document.file.open('rb')
            return ImageReader(io.BytesIO(document.file.read()))
        except Exception:
            continue
        finally:
            try:
                document.file.close()
            except Exception:
                pass
    return None


def qr_payload(registration) -> str:
    """What a phone shows when the badge is scanned.

    Plain text rather than a URL, so any reader displays it as-is and a steward
    can check the card against the person without a network.

    Every byte costs modules, and past roughly 120 bytes the code gets too fine
    to read reliably off a printed card — so the detail line is packed rather
    than labelled, and the paid status is left out (the card carries the stamp,
    and a badge is only ever issued to a paid member).
    """
    club = registration.club
    detail = ' | '.join(filter(None, [
        registration.reference,
        registration.get_category_display(),
        registration.season,
        registration.center.name_en if registration.center else '',
    ]))
    lines = [
        club.name_en if club else 'Binh Dinh Gia',
        registration.latin_full_name,
        f'{registration.first_name} {registration.last_name}',
        detail,
    ]
    return '\n'.join(line for line in lines if line)


def _qr_for(registration):
    # Error correction M keeps it readable through a scuffed laminate; a modest
    # quiet zone leaves the code as large as possible on the card.
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(qr_payload(registration))
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    return ImageReader(buffer)


def _draw_front(c: canvas.Canvas, x: float, y: float, registration):
    """x, y is the bottom-left corner of the card."""
    settings = SiteSettings.load()

    c.saveState()
    c.setStrokeGray(0.8)
    c.setLineWidth(0.5)
    c.roundRect(x, y, CARD_W, CARD_H, 3 * MM, stroke=1, fill=0)

    # Header band
    c.setFillColorRGB(*BRAND_RED)
    c.roundRect(x, y + CARD_H - 15 * MM, CARD_W, 15 * MM, 3 * MM, stroke=0, fill=1)
    c.setFillColorRGB(*BRAND_RED)
    c.rect(x, y + CARD_H - 15 * MM, CARD_W, 3 * MM, stroke=0, fill=1)

    if LOGO.exists():
        c.drawImage(str(LOGO), x + 3 * MM, y + CARD_H - 13.5 * MM, width=12 * MM, height=12 * MM, mask='auto')

    club_name = registration.club.name_en if registration.club else 'Binh Dinh Gia'
    c.setFillGray(1)
    _text(c, x + 17 * MM, y + CARD_H - 7 * MM, club_name, 9, bold=True, max_width=CARD_W - 22 * MM)
    _text(c, x + 17 * MM, y + CARD_H - 11 * MM, TEXT['en']['card'].upper(), 6.5)
    _text(c, x + CARD_W - 3 * MM, y + CARD_H - 11 * MM, TEXT['ar']['card'], 8,
          bold=True, align='right', language='ar')

    # Photo
    photo_x, photo_y, photo_w, photo_h = x + 4 * MM, y + 12 * MM, 20 * MM, 26 * MM
    photo = _photo_for(registration)
    if photo is not None:
        c.saveState()
        path = c.beginPath()
        path.roundRect(photo_x, photo_y, photo_w, photo_h, 1.5 * MM)
        c.clipPath(path, stroke=0, fill=0)
        c.drawImage(photo, photo_x, photo_y, width=photo_w, height=photo_h,
                    preserveAspectRatio=True, anchor='c', mask='auto')
        c.restoreState()
    else:
        c.setFillGray(0.93)
        c.roundRect(photo_x, photo_y, photo_w, photo_h, 1.5 * MM, stroke=0, fill=1)
    c.setStrokeGray(0.75)
    c.setLineWidth(0.4)
    c.roundRect(photo_x, photo_y, photo_w, photo_h, 1.5 * MM, stroke=1, fill=0)

    # Identity
    text_x = photo_x + photo_w + 4 * MM
    c.setFillGray(0)
    name_width = CARD_W - (text_x - x) - 4 * MM
    _text(c, text_x, y + CARD_H - 22 * MM, registration.latin_full_name, 11, bold=True, max_width=name_width)
    _text(c, text_x, y + CARD_H - 27 * MM,
          f'{registration.first_name} {registration.last_name}', 9, language='ar', max_width=name_width)

    # The QR occupies the bottom-right corner, so field labels stop short of it.
    label_right = x + CARD_W - QR_SIZE - 5 * MM

    def field(label_en, label_ar, value, row):
        top = y + CARD_H - 33 * MM - row * 6 * MM
        c.setFillGray(0.45)
        _text(c, text_x, top + 2.6 * MM, label_en.upper(), 6)
        _text(c, label_right, top + 2.6 * MM, label_ar, 6, align='right', language='ar')
        c.setFillGray(0)
        _text(c, text_x, top - 1 * MM, str(value)[:30], 8.5, bold=True,
              max_width=label_right - text_x - 2 * MM)

    field(TEXT['en']['category'], TEXT['ar']['category'], registration.get_category_display(), 0)
    field(TEXT['en']['season'], TEXT['ar']['season'], registration.season or settings.active_season, 1)

    # Reference + paid stamp + QR
    c.setFillGray(0.45)
    _text(c, x + 4 * MM, y + 7 * MM, TEXT['en']['reference'].upper(), 6)
    c.setFillGray(0)
    _text(c, x + 4 * MM, y + 3.5 * MM, registration.reference, 8, bold=True)

    c.setFillColorRGB(*BRAND_GOLD)
    c.roundRect(x + 30 * MM, y + 3 * MM, 18 * MM, 6 * MM, 3 * MM, stroke=0, fill=1)
    c.setFillGray(0.1)
    _text(c, x + 39 * MM, y + 5 * MM, TEXT['en']['paid'], 7, bold=True, align='center')

    c.drawImage(_qr_for(registration), x + CARD_W - QR_SIZE - 4 * MM, y + 3.5 * MM,
                width=QR_SIZE, height=QR_SIZE, mask='auto')
    c.restoreState()


def _draw_back(c: canvas.Canvas, x: float, y: float, registration):
    c.saveState()
    c.setStrokeGray(0.8)
    c.setLineWidth(0.5)
    c.roundRect(x, y, CARD_W, CARD_H, 3 * MM, stroke=1, fill=0)

    c.setFillGray(0.1)
    _text(c, x + 5 * MM, y + CARD_H - 9 * MM, TEXT['en']['club'].upper(), 8, bold=True)

    club = registration.club
    inner = CARD_W - 10 * MM
    c.setFillGray(0.25)
    _text(c, x + 5 * MM, y + CARD_H - 14 * MM, club.name_en if club else '—', 8, max_width=inner)
    _text(c, x + 5 * MM, y + CARD_H - 19 * MM, club.name_ar if club else '—', 8,
          language='ar', max_width=inner)

    if registration.center:
        _text(c, x + 5 * MM, y + CARD_H - 24 * MM,
              f"{TEXT['en']['center']}: {registration.center.name_en}", 7.5, max_width=inner)

    if club and (club.phone or club.address):
        c.setFillGray(0.45)
        detail = ' · '.join(filter(None, [club.address, club.phone]))
        _text(c, x + 5 * MM, y + CARD_H - 29 * MM, detail, 7, max_width=inner)

    c.setStrokeGray(0.85)
    c.setLineWidth(0.4)
    c.line(x + 5 * MM, y + 16 * MM, x + CARD_W - 5 * MM, y + 16 * MM)

    c.setFillGray(0.4)
    _text(c, x + CARD_W - 5 * MM, y + 11 * MM, TEXT['ar']['terms'], 6.5,
          align='right', language='ar', max_width=inner)
    _text(c, x + 5 * MM, y + 7 * MM, TEXT['en']['terms'], 6, max_width=inner)

    c.setFillGray(0.6)
    _text(c, x + 5 * MM, y + 3 * MM, registration.reference, 6)
    c.restoreState()


def generate_badge(registration) -> io.BytesIO:
    """Front and back of one badge, side by side on a single A4 sheet."""
    register_fonts()
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)

    left = (PAGE_W - CARD_W) / 2
    _draw_front(c, left, PAGE_H - 40 * MM - CARD_H, registration)
    _draw_back(c, left, PAGE_H - 50 * MM - 2 * CARD_H, registration)

    _register_marks(c)
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer


PER_ROW, PER_COLUMN = 2, 4
PER_SHEET = PER_ROW * PER_COLUMN  # 8 badges to a page
GAP_X, GAP_Y = 5 * MM, 5 * MM
MARGIN_X = (PAGE_W - (PER_ROW * CARD_W + (PER_ROW - 1) * GAP_X)) / 2
MARGIN_Y = 12 * MM


def _slot_position(slot: int, mirrored: bool = False) -> tuple[float, float]:
    """Bottom-left corner of a slot on the 2x4 grid.

    `mirrored` flips the columns for the reverse side: printers turn the sheet
    over on its long edge, so the backs have to run right-to-left if each one is
    to land behind its own front.
    """
    column, row = slot % PER_ROW, slot // PER_ROW
    if mirrored:
        column = PER_ROW - 1 - column
    x = MARGIN_X + column * (CARD_W + GAP_X)
    y = PAGE_H - MARGIN_Y - (row + 1) * CARD_H - row * GAP_Y
    return x, y


def generate_badge_sheet(registrations, mirror_backs: bool = False) -> io.BytesIO:
    """Badges laid out 8 to a page: a page of fronts, then that page's backs.

    By default each back sits in the *same* slot as its front, so the two pages
    line up when held together — the layout to use when cutting the cards and
    pairing them by hand, or printing the two pages separately.

    `mirror_backs` flips the columns instead, which is what an automatic
    double-sided printer needs when it turns the sheet on its long edge.
    """
    register_fonts()
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)

    registrations = list(registrations)
    for start in range(0, len(registrations), PER_SHEET):
        batch = registrations[start:start + PER_SHEET]
        span = f'{start + 1}–{start + len(batch)}'

        for slot, registration in enumerate(batch):
            x, y = _slot_position(slot)
            _draw_front(c, x, y, registration)
        _sheet_note(c, f'Fronts · {span}')
        c.showPage()

        for slot, registration in enumerate(batch):
            x, y = _slot_position(slot, mirrored=mirror_backs)
            _draw_back(c, x, y, registration)
        _sheet_note(
            c,
            f'Backs · {span} · ' + (
                'mirrored for double-sided printing (flip on long edge)'
                if mirror_backs else
                'same position as the fronts'
            ),
        )
        c.showPage()

    c.save()
    buffer.seek(0)
    return buffer


def _sheet_note(c: canvas.Canvas, text: str):
    c.setFillGray(0.6)
    regular, _ = fonts_for('en')
    c.setFont(regular, 7)
    c.drawCentredString(PAGE_W / 2, 7 * MM, text)


def _register_marks(c: canvas.Canvas):
    c.setFillGray(0.6)
    regular, _ = fonts_for('en')
    c.setFont(regular, 7)
    c.drawCentredString(PAGE_W / 2, 15 * MM, 'Cut along the card edges · Front (top) and back (bottom)')
