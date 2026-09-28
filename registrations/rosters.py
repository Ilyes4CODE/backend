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

from .letterhead import official_lines
from .models import SiteSettings
from .typography import fonts_for, register_fonts, resolve, shape

MM = 2.834645669
LOGO = Path(__file__).resolve().parent / 'assets' / 'logo-transparent.png'

MARGIN = 12 * MM
ROW_H = 7.2 * MM
# From the top edge of the page down to the column headings. Page one carries
# the full official letterhead; the pages after it only need to say which list
# they belong to, and giving them the whole masthead again cost a third of
# every page on a long register.
HEADER_FIRST = 61 * MM
HEADER_REST = 25 * MM
LOGO_SIZE = 20 * MM

ROSTER_TITLE = 'قائمة المنخرطين'
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


def _centred(c, x, y, text, font, size, max_width=None):
    """Centred, and shrunk until it fits — a long club name must not run
    underneath the logos."""
    drawn = shape(text)
    if max_width:
        while size > 7 and c.stringWidth(drawn, font, size) > max_width:
            size -= 0.25
    c.setFont(font, size)
    c.drawCentredString(x, y, drawn)


def _draw_letterhead(c, club, title, subtitle, page_w, page_h):
    """Page one: the official letterhead, the club's logo on both sides of it."""
    top = page_h - MARGIN
    middle = page_w / 2

    if LOGO.exists():
        for x in (MARGIN, page_w - MARGIN - LOGO_SIZE):
            c.drawImage(str(LOGO), x, top - LOGO_SIZE, width=LOGO_SIZE,
                        height=LOGO_SIZE, mask='auto')

    c.setFillColorRGB(0.1, 0.1, 0.1)
    between_logos = page_w - 2 * MARGIN - 2 * LOGO_SIZE - 8 * MM
    y = top - 5 * MM
    for text, size, bold in official_lines(club):
        _centred(c, middle, y, text, 'Tahoma-Bold' if bold else 'Tahoma', size,
                 max_width=between_logos)
        y -= 5.4 * MM

    # A brand rule closes the letterhead off from the document itself.
    rule_y = top - LOGO_SIZE - 5 * MM
    c.setStrokeColorRGB(*BRAND)
    c.setLineWidth(1.1)
    c.line(MARGIN, rule_y, page_w - MARGIN, rule_y)

    _centred(c, middle, rule_y - 7.5 * MM, title, 'Tahoma-Bold', 15)

    c.setFillGray(0.42)
    _centred(c, middle, rule_y - 13 * MM, subtitle, 'Tahoma', 9.5)
    c.setFont('Tahoma', 8.5)
    c.drawRightString(page_w - MARGIN, rule_y - 13 * MM,
                      shape(f'التاريخ: {date.today().strftime("%Y/%m/%d")}'))


def _draw_running_head(c, title, subtitle, page_w, page_h):
    """Every page after the first: enough to tell which list a loose sheet is."""
    top = page_h - MARGIN
    c.setFillColorRGB(0.1, 0.1, 0.1)
    c.setFont('Tahoma-Bold', 11)
    c.drawRightString(page_w - MARGIN, top - 5 * MM, shape(title))
    c.setFillGray(0.42)
    c.setFont('Tahoma', 8.5)
    c.drawString(MARGIN, top - 5 * MM, shape(subtitle))
    c.setStrokeColorRGB(*BRAND)
    c.setLineWidth(0.8)
    c.line(MARGIN, top - 8 * MM, page_w - MARGIN, top - 8 * MM)


def _draw_header(c, title, subtitle, page, page_w, page_h, columns, club=None):
    if page == 1:
        _draw_letterhead(c, club, title, subtitle, page_w, page_h)
        header = HEADER_FIRST
    else:
        _draw_running_head(c, title, subtitle, page_w, page_h)
        header = HEADER_REST

    # Column headings: reversed out of a dark band, which is what makes a
    # table read as a table rather than as shaded rows.
    y = page_h - header
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


# Rows stop this far above the bottom margin, leaving room for the footer.
ROWS_FLOOR = MARGIN + ROW_H + 8 * MM


def _capacity(page_h, header):
    """How many rows the loop below will put on a page with this header.

    Worked out from the same floor the loop breaks on, so "page 1 of N" cannot
    disagree with how many pages actually get printed.
    """
    table_top = page_h - header - 1 * MM
    if table_top < ROWS_FLOOR:
        return 0
    return int((table_top - ROWS_FLOOR) // ROW_H) + 1


def _page_count(total, page_h):
    first, rest = _capacity(page_h, HEADER_FIRST), _capacity(page_h, HEADER_REST)
    if total <= first:
        return 1
    return 1 + -(-(total - first) // rest)


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
    registrations, title=ROSTER_TITLE, subtitle='', orientation=PORTRAIT,
    club=None, center=None,
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

    if not subtitle:
        subtitle = f'الموسم الرياضي: {SiteSettings.load().active_season}'
        if center is not None:
            subtitle += f'  ·  فرع {center.name_ar or center.name_en}'
    # Worked out up front so the footer can say "1 of 3".
    pages = _page_count(total, page_h)

    page = 1
    y = _draw_header(c, title, subtitle, page, page_w, page_h, columns, club)
    table_top = y
    signature_col = columns[-1]

    def close_page(last_y):
        _draw_grid(c, columns, table_top, last_y, page_w)
        c.setFillGray(0.45)
        c.setFont('Tahoma', 8)
        c.drawRightString(page_w - MARGIN, MARGIN - 3 * MM, shape(f'عدد المنخرطين: {total}'))
        c.drawString(MARGIN, MARGIN - 3 * MM, shape(f'الصفحة {page} من {pages}'))

    for index, registration in enumerate(rows, start=1):
        if y < ROWS_FLOOR:
            close_page(y)
            c.showPage()
            page += 1
            y = _draw_header(c, title, subtitle, page, page_w, page_h, columns, club)
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
