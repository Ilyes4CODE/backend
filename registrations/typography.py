"""Fonts and text shaping shared by the certificate and badge PDFs.

Arabic is set in Tajawal and English in Poppins, as the club asked. Poppins has
no Vietnamese diacritics (ấ ậ ị ứ all render as tofu), so the Vietnamese version
uses Be Vietnam Pro — the geometric face designed for that script, which sits
next to Poppins without a visible change of voice.
"""

from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONTS_DIR = Path(__file__).resolve().parent / 'fonts'

# family -> (regular file, bold file)
FAMILIES = {
    'Tajawal': ('Tajawal-Regular.ttf', 'Tajawal-Bold.ttf'),
    'Poppins': ('Poppins-Regular.ttf', 'Poppins-SemiBold.ttf'),
    'BeVietnamPro': ('BeVietnamPro-Regular.ttf', 'BeVietnamPro-SemiBold.ttf'),
    # Tahoma carries Arabic and Latin in one family and was drawn for small
    # sizes on screen, which is exactly the problem a dense register has.
    # Certificates and badges stay on the display faces above; the roster,
    # where a name has to be read at 8pt in two scripts, uses this.
    'Tahoma': ('tahoma.ttf', 'tahomabd.ttf'),
}

# Which family carries which language.
LANGUAGE_FONTS = {
    'ar': 'Tajawal',
    'en': 'Poppins',
    'vi': 'BeVietnamPro',
}

_REGISTERED = False


def register_fonts():
    global _REGISTERED
    if _REGISTERED:
        return
    for family, (regular, bold) in FAMILIES.items():
        pdfmetrics.registerFont(TTFont(family, str(FONTS_DIR / regular)))
        pdfmetrics.registerFont(TTFont(f'{family}-Bold', str(FONTS_DIR / bold)))
    _REGISTERED = True


def fonts_for(language: str) -> tuple[str, str]:
    """(regular, bold) font names for a language."""
    family = LANGUAGE_FONTS.get(language, 'Poppins')
    return family, f'{family}-Bold'


# Arabic, Arabic Supplement, Extended-A, and the presentation-form blocks.
ARABIC_RANGES = ((0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF),
                 (0xFB50, 0xFDFF), (0xFE70, 0xFEFF))


def has_arabic(text) -> bool:
    return any(
        any(low <= ord(ch) <= high for low, high in ARABIC_RANGES)
        for ch in str(text)
    )


def shape(text) -> str:
    """Reshape and reorder Arabic so reportlab draws it joined and right-to-left.

    Latin-only text is returned untouched, so this is safe to call on any string —
    including an Arabic competitor name printed on the English certificate.
    """
    text = '' if text is None else str(text)
    if not text or not has_arabic(text):
        return text
    return get_display(arabic_reshaper.reshape(text))


def _covered_codepoints(font_name: str) -> set[int]:
    """Which codepoints a registered font can actually draw."""
    register_fonts()
    try:
        return set(pdfmetrics.getFont(font_name).face.charToGlyph.keys())
    except Exception:
        return set()


def _substitute_missing(text: str, font_name: str) -> str:
    """Swap presentation forms the font lacks for ones it has.

    The reshaper emits Arabic presentation forms (U+FE70–U+FEFF), and Tajawal
    ships the *final* form of alef and reh but not their *isolated* form. In that
    block the two sit next to each other (isolated, then final), and for letters
    that never join to the left the two glyphs are the same shape — so stepping
    to the neighbour restores the letter instead of printing a blank box.
    """
    covered = _covered_codepoints(font_name)
    if not covered:
        return text
    out = []
    for char in text:
        code = ord(char)
        if code in covered:
            out.append(char)
        elif 0xFE70 <= code <= 0xFEFF and code + 1 in covered:
            out.append(chr(code + 1))
        else:
            out.append(char)
    return ''.join(out)


def resolve(text, language: str) -> tuple[str, str, str]:
    """Prepare a string for drawing: (text, regular font, bold font).

    The font follows the *text*, not the page: an Arabic name on the English
    certificate is still set in Tajawal, because Poppins has no Arabic at all.
    """
    text = '' if text is None else str(text)
    family = 'Tajawal' if has_arabic(text) else LANGUAGE_FONTS.get(language, 'Poppins')
    regular, bold = family, f'{family}-Bold'
    return _substitute_missing(shape(text), regular), regular, bold
