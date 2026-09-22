"""Printable lists — the roster of candidates, and a group's weekly timetable.

Portrait A4 by default, with a repeating header, so the club can put a signed
copy in the file or hand one to the wilaya directorate. Portrait is what a
register is meant to look like; landscape stays available (?orientation=
landscape) for when every column matters more than the shape of the page.

Portrait is 186 mm wide against landscape's 273 mm, so it cannot carry the same
twelve columns legibly. It drops the phone number — the one field nobody reads
off a signature sheet — and keeps everything else.
"""

import io
from datetime import date
from pathlib import Path

from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.pdfgen import canvas

from .models import SiteSettings
from .typography import fonts_for, register_fonts, resolve

MM = 2.834645669
LOGO = Path(__file__).resolve().parent / 'assets' / 'logo-transparent.png'

MARGIN = 12 * MM
ROW_H = 7.2 * MM
HEADER_H = 38 * MM
# The row is indented this far from the margin, so the columns have that much
# less to work with.
TABLE_INSET = 2

PORTRAIT = 'portrait'
LANDSCAPE = 'landscape'
PAGE_SIZES = {PORTRAIT: portrait(A4), LANDSCAPE: landscape(A4)}

# (heading, width in mm, how to read the value off a registration)
REFERENCE = ('Reference', 24, lambda r: r.reference)
NAME = ('Name', 40, lambda r: f'{r.first_name} {r.last_name}'.strip())
LATIN = ('Latin name', 38, lambda r: r.latin_full_name)
SEX = ('Sex', 14, lambda r: r.get_gender_display() if r.gender else '—')
BORN = ('Born', 22, lambda r: r.birth_date.strftime('%Y/%m/%d'))
AGE = ('Age', 11, lambda r: str(r.age_at_registration))
CATEGORY = ('Category', 22, lambda r: r.get_category_display())
BRANCH = ('Branch', 24, lambda r: r.center.name_en if r.center else '—')
PHONE = ('Phone', 22, lambda r: r.phone)
PAID = ('Paid', 12, lambda r: 'Yes' if r.payment_status == 'PAID' else 'No')


def _resize(column, width):
    heading, _, reader = column
    return (heading, width, reader)


LANDSCAPE_COLUMNS = [
    ('#', 10, None), REFERENCE, NAME, LATIN, SEX, BORN, AGE, CATEGORY, BRANCH, PHONE, PAID,
    ('Signature', 28, lambda r: ''),
]

# Narrower page, so every column is trimmed and Phone is dropped outright.
PORTRAIT_COLUMNS = [
    ('#', 7, None),
    _resize(REFERENCE, 22),
    _resize(NAME, 29),
    _resize(LATIN, 25),
    _resize(SEX, 11),
    _resize(BORN, 17),
    _resize(AGE, 8),
    _resize(CATEGORY, 17),
    _resize(BRANCH, 16),
    _resize(PAID, 9),
    ('Signature', 21, lambda r: ''),
]

COLUMN_SETS = {PORTRAIT: PORTRAIT_COLUMNS, LANDSCAPE: LANDSCAPE_COLUMNS}

# Kept for callers that just want "the default layout".
COLUMNS = PORTRAIT_COLUMNS


def usable_mm(orientation: str = PORTRAIT) -> float:
    page_w, _ = PAGE_SIZES[orientation]
    return (page_w - 2 * MARGIN) / MM


def columns_mm(orientation: str = PORTRAIT) -> float:
    """Total width the columns need. Overflow doesn't error at draw time — it
    silently runs the last column off the page — so it has to be checkable.
    test_roster_fits_the_page guards both orientations."""
    return TABLE_INSET + sum(width for _, width, _ in COLUMN_SETS[orientation])


USABLE_MM = usable_mm(PORTRAIT)
COLUMNS_MM = columns_mm(PORTRAIT)


BRAND = (0.894, 0.098, 0.114)      # #E4191D
HEAD_BG = (0.129, 0.129, 0.129)    # near-black header band
RULE = 0.86
ZEBRA = 0.965


def _shape(value, heading):
    """Text plus the font that can actually draw it.

    The whole table is set in Tahoma, which covers Arabic and Latin in one
    family — a register where the name column jumps to a different typeface
    than the column beside it looks like two documents stapled together.
    """
    text, _, _ = resolve(value, 'ar' if heading in ('Name',) else 'en')
    return text


def _fit(c, text, font, width_mm, start=8.0, floor=5.0):
    """Largest size that still fits the column."""
    size = start
    while size > floor and c.stringWidth(text, font, size) > (width_mm - 3.4) * MM:
        size -= 0.25
    return size


def _draw_header(c, title, subtitle, page, page_w, page_h, columns):
    top = page_h - MARGIN

    if LOGO.exists():
        c.drawImage(str(LOGO), MARGIN, top - 17 * MM, width=17 * MM, height=17 * MM, mask='auto')

    c.setFillColorRGB(0.1, 0.1, 0.1)
    c.setFont('Tahoma-Bold', 15)
    c.drawString(MARGIN + 21 * MM, top - 6.5 * MM, title)

    c.setFillGray(0.42)
    c.setFont('Tahoma', 9)
    c.drawString(MARGIN + 21 * MM, top - 12 * MM, subtitle)

    c.setFont('Tahoma', 8.5)
    c.drawRightString(page_w - MARGIN, top - 6.5 * MM, date.today().strftime('%Y/%m/%d'))
    c.drawRightString(page_w - MARGIN, top - 12 * MM, f'Page {page}')

    # A brand rule under the masthead separates it from the table.
    c.setStrokeColorRGB(*BRAND)
    c.setLineWidth(1.1)
    c.line(MARGIN, top - 19 * MM, page_w - MARGIN, top - 19 * MM)

    # Column headings: reversed out of a dark band, which is what makes a
    # table read as a table rather than as shaded rows.
    y = page_h - HEADER_H
    table_w = page_w - 2 * MARGIN
    c.setFillColorRGB(*HEAD_BG)
    c.rect(MARGIN, y - 1 * MM, table_w, ROW_H, fill=1, stroke=0)

    c.setFillGray(1)
    c.setFont('Tahoma-Bold', 7)
    x = MARGIN + TABLE_INSET * MM
    for heading, width, _ in columns:
        c.drawString(x, y + 1.5 * MM, heading.upper())
        x += width * MM
    return y - 1 * MM


def _draw_grid(c, columns, top_y, bottom_y, page_w):
    """Vertical separators, drawn once per page behind the rows."""
    c.setStrokeGray(RULE)
    c.setLineWidth(0.25)
    x = MARGIN
    for _, width, _ in columns[:-1]:
        x += width * MM
        c.line(x, top_y, x, bottom_y)
    # Box the table so the last column has an edge to sit against.
    c.rect(MARGIN, bottom_y, page_w - 2 * MARGIN, top_y - bottom_y, fill=0, stroke=1)


def generate_roster(
    registrations, title='Candidates', subtitle='', orientation=PORTRAIT,
) -> io.BytesIO:
    """One row per candidate, with a ruled signature column for the paper file.

    Portrait unless asked otherwise — a register should read down the page, not
    across it.
    """
    register_fonts()
    orientation = orientation if orientation in PAGE_SIZES else PORTRAIT
    page_w, page_h = PAGE_SIZES[orientation]
    columns = COLUMN_SETS[orientation]
    rows = list(registrations)
    total = len(rows)

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(page_w, page_h))
    c.setTitle(title)

    subtitle = subtitle or f'Season {SiteSettings.load().active_season}'
    # Work out the page count up front so the footer can say "1 of 3".
    per_page = int((page_h - HEADER_H - MARGIN - 12 * MM) // ROW_H)
    pages = max(1, -(-total // per_page)) if total else 1

    page = 1
    y = _draw_header(c, title, subtitle, page, page_w, page_h, columns)
    table_top = y
    signature_col = columns[-1]

    def close_page(last_y):
        _draw_grid(c, columns, table_top, last_y, page_w)
        c.setFillGray(0.45)
        c.setFont('Tahoma', 8)
        c.drawString(MARGIN, MARGIN - 3 * MM, f'{total} candidate(s)')
        c.drawRightString(page_w - MARGIN, MARGIN - 3 * MM, f'Page {page} of {pages}')

    for index, registration in enumerate(rows, start=1):
        if y < MARGIN + ROW_H + 8 * MM:
            close_page(y)
            c.showPage()
            page += 1
            y = _draw_header(c, title, subtitle, page, page_w, page_h, columns)
            table_top = y

        y -= ROW_H
        if index % 2 == 0:
            c.setFillGray(ZEBRA)
            c.rect(MARGIN, y, page_w - 2 * MARGIN, ROW_H, fill=1, stroke=0)

        x = MARGIN + TABLE_INSET * MM
        for heading, width, reader in columns:
            if reader is signature_col[2]:
                # A line to sign on, not an empty cell.
                c.setStrokeGray(0.75)
                c.setLineWidth(0.4)
                c.line(x, y + 2 * MM, x + (width - 5) * MM, y + 2 * MM)
                x += width * MM
                continue

            value = str(index) if reader is None else str(reader(registration) or '')
            if value:
                text = _shape(value, heading)
                font = 'Tahoma-Bold' if heading == 'Reference' else 'Tahoma'
                size = _fit(c, text, font, width)
                c.setFillGray(0.32 if heading in ('Born', 'Age') else 0.15)
                c.setFont(font, size)
                c.drawString(x, y + 2.3 * MM, text)
            x += width * MM

        c.setStrokeGray(RULE)
        c.setLineWidth(0.25)
        c.line(MARGIN, y, page_w - MARGIN, y)

    close_page(y)
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer
