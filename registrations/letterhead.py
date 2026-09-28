"""The official letterhead of the club's printed documents.

The registration form and the candidate list end up in the same places — the
club's own file and the wilaya directorate — so they open with the same
wording, and it lives here once rather than typed into each document.
"""

REPUBLIC = 'الجمهورية الجزائرية الديمقراطية الشعبية'
MINISTRY = 'وزارة الشباب والرياضة'

# The national administrator prints lists that cover every club, which belong
# to no single wilaya directorate. They carry the platform's national name, the
# one the public site uses for itself.
NATIONAL_NAME = 'بيندين زا — الجزائر'


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


def official_lines(club) -> list[tuple[str, float, bool]]:
    """(text, size, bold) for each line of the letterhead, top to bottom."""
    lines = [(REPUBLIC, 11.5, True), (MINISTRY, 10.0, False)]
    if club is None:
        lines.append((NATIONAL_NAME, 10.5, True))
    else:
        lines.append((directorate(club), 10.0, False))
        lines.append((club_heading(club), 10.5, True))
    return lines
