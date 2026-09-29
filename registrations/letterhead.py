"""The letterhead of the club's printed documents.

The registration form and the candidate list end up in the same places — the
club's own file and the wilaya directorate — so they open with the same
letterhead, drawn here once.

Each club may set its own logos and header lines from the dashboard. Whatever
it leaves empty falls back to the platform's logo and the official wording.
"""

import os
from pathlib import Path

from .typography import shape

MM = 2.834645669

REPUBLIC = 'الجمهورية الجزائرية الديمقراطية الشعبية'
MINISTRY = 'وزارة الشباب والرياضة'

# The national administrator prints lists that cover every club, which belong
# to no single wilaya directorate. They carry the platform's national name, the
# one the public site uses for itself.
NATIONAL_NAME = 'بيندين زا — الجزائر'

ASSETS = Path(__file__).resolve().parent / 'assets'
DEFAULT_LOGO = ASSETS / 'logo-transparent.png'

LOGO_SIZE = 20 * MM
LINE_STEP = 5.4 * MM
FIRST_BASELINE = 5 * MM      # below the top of the letterhead
DESCENT = 2 * MM             # below the last baseline

MAX_LINES = 6


def directorate(club) -> str:
    """The directorate follows the club's wilaya — clubs open all over Algeria,
    so no single province can be named for everyone."""
    wilaya = getattr(getattr(club, 'wilaya', None), 'name_ar', '') if club else ''
    return f'مديرية الشباب والرياضة لولاية {wilaya}' if wilaya else 'مديرية الشباب والرياضة'


def club_heading(club) -> str:
    """The club's Arabic name as printed, naming the discipline exactly once.

    Many clubs already have it in their name ("… للبيندين زا"), and appending it
    blindly printed it twice.
    """
    name = (club.name_ar if club and club.name_ar else 'النادي الرياضي للهواة').strip()
    return name if 'بيندين' in name else f'{name} للبيندين زا'


def default_lines(club) -> list[str]:
    """The official wording, used whenever a club has not written its own."""
    if club is None:
        return [REPUBLIC, MINISTRY, NATIONAL_NAME]
    return [REPUBLIC, MINISTRY, directorate(club), club_heading(club)]


def custom_lines(club) -> list[str]:
    """The club's own header, one entry per line; empty if it has none."""
    raw = getattr(club, 'letterhead_lines', '') if club else ''
    return [line.strip() for line in (raw or '').splitlines() if line.strip()][:MAX_LINES]


def official_lines(club) -> list[tuple[str, float, bool]]:
    """(text, size, bold) for each line of the letterhead, top to bottom.

    The first and last lines are set heavier — in the official wording those
    are the Republic and the club — and a club's own lines follow the same rule,
    so what it types reads like the default it replaces.
    """
    lines = custom_lines(club) or default_lines(club)
    last = len(lines) - 1
    styled = []
    for index, text in enumerate(lines):
        if index == 0:
            styled.append((text, 11.5, True))
        elif index == last:
            styled.append((text, 10.5, True))
        else:
            styled.append((text, 10.0, False))
    return styled


def _stored(file_field) -> str | None:
    """The file on disk behind an image field, if there is one."""
    if not file_field:
        return None
    try:
        path = file_field.path
    except (NotImplementedError, ValueError):
        return None
    return path if os.path.exists(path) else None


def logo_files(club, default: Path = DEFAULT_LOGO) -> tuple[str | None, str | None]:
    """(start side, end side) — right and left on an Arabic page.

    The club's logo leads; its second logo, if any, takes the other side,
    otherwise its own logo appears on both. A club with none gets the
    platform's.
    """
    fallback = str(default) if default and Path(default).exists() else None
    primary = (_stored(club.logo) if club else None) or fallback
    secondary = (_stored(club.logo_secondary) if club else None) or primary
    return primary, secondary


def primary_logo(club, default: Path = DEFAULT_LOGO) -> str | None:
    """The one logo for documents with room for one — cards, certificates."""
    return logo_files(club, default)[0]


def draw_logo(c, path, x, y, size, fallback: Path = DEFAULT_LOGO):
    """Draw a logo into a square, keeping its proportions.

    Uploaded logos are rarely square. And if a stored file turns out to be
    unreadable, the platform's logo takes its place rather than the whole
    document failing to print.
    """
    for candidate in (path, str(fallback) if fallback else None):
        if not candidate:
            continue
        try:
            c.drawImage(candidate, x, y, width=size, height=size,
                        preserveAspectRatio=True, anchor='c', mask='auto')
            return
        except Exception:  # noqa: BLE001 - any unreadable image falls back
            continue


def letterhead_depth(club) -> float:
    """How far the letterhead reaches down from its top edge."""
    lines = len(official_lines(club))
    text = FIRST_BASELINE + (lines - 1) * LINE_STEP + DESCENT
    return max(LOGO_SIZE, text)


def draw_letterhead(c, club, *, top, page_w, margin, regular='Tahoma', bold='Tahoma-Bold',
                    default_logo: Path = DEFAULT_LOGO) -> float:
    """Logos on both sides, the header lines centred between them.

    Returns the y just below the letterhead, for the document to carry on from.
    """
    # Centred on the text beside them: with six lines the text block is taller
    # than a logo, and logos pinned to the top would sit high against it.
    depth = letterhead_depth(club)
    logo_bottom = top - (depth + LOGO_SIZE) / 2
    start_logo, end_logo = logo_files(club, default_logo)
    draw_logo(c, start_logo, page_w - margin - LOGO_SIZE, logo_bottom, LOGO_SIZE, default_logo)
    draw_logo(c, end_logo, margin, logo_bottom, LOGO_SIZE, default_logo)

    # A long line shrinks rather than run underneath a logo.
    between_logos = page_w - 2 * margin - 2 * LOGO_SIZE - 8 * MM
    y = top - FIRST_BASELINE
    for text, size, is_bold in official_lines(club):
        font = bold if is_bold else regular
        drawn = shape(text)
        while size > 7 and c.stringWidth(drawn, font, size) > between_logos:
            size -= 0.25
        c.setFont(font, size)
        c.drawCentredString(page_w / 2, y, drawn)
        y -= LINE_STEP
    return top - depth
