"""Generates a PDF registration form styled after the club's official docx form
(استمارة تسجيل اصاغر): ministry header, club name/season, personal info, a blank
medical-certificate block for the doctor's physical signature, a parental-
authorization block (only for minors), and the required-documents checklist.
"""

import io
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from django.db.models import Q
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .letterhead import ASSETS, club_heading, draw_letterhead
from .models import RequiredDocument, SiteSettings, UploadedDocument

FONTS_DIR = Path(__file__).resolve().parent / 'fonts'
FONT_REGULAR = 'Tahoma'
FONT_BOLD = 'Tahoma-Bold'

_FONTS_REGISTERED = False


def _register_fonts():
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    pdfmetrics.registerFont(TTFont(FONT_REGULAR, str(FONTS_DIR / 'tahoma.ttf')))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, str(FONTS_DIR / 'tahomabd.ttf')))
    _FONTS_REGISTERED = True


def rtl(text: str) -> str:
    """Reshape + reorder Arabic (and mixed Arabic/Latin/digit) text for drawString."""
    if not text:
        return ''
    return get_display(arabic_reshaper.reshape(str(text)))


PAGE_W, PAGE_H = A4
MM = 2.834645669  # 1mm in points


class FormBuilder:
    def __init__(self, c: canvas.Canvas):
        self.c = c
        self.y = PAGE_H - 15 * MM
        self.right = PAGE_W - 18 * MM
        self.left = 18 * MM

    def move(self, dy):
        self.y -= dy * MM

    def centered(self, text, size=11, bold=False, dy=6):
        self.c.setFont(FONT_BOLD if bold else FONT_REGULAR, size)
        self.c.drawCentredString(PAGE_W / 2, self.y, rtl(text))
        self.move(dy)

    def line_rtl(self, text, size=10.5, bold=False, dy=6.5):
        self.c.setFont(FONT_BOLD if bold else FONT_REGULAR, size)
        self.c.drawRightString(self.right, self.y, rtl(text))
        self.move(dy)

    def two_col_rtl(self, text_a, text_b, size=10.5, dy=6.5):
        self.c.setFont(FONT_REGULAR, size)
        self.c.drawRightString(self.right, self.y, rtl(text_a))
        self.c.drawRightString(PAGE_W / 2 - 4 * MM, self.y, rtl(text_b))
        self.move(dy)

    def rule(self, dy=4):
        self.move(2)
        self.c.setLineWidth(0.6)
        self.c.line(self.left, self.y, self.right, self.y)
        self.move(dy)

    def ensure_space(self, needed_mm):
        if self.y - needed_mm * MM < 15 * MM:
            self.c.showPage()
            self.y = PAGE_H - 15 * MM

    def section_title(self, text):
        self.ensure_space(20)
        self.move(3)
        self.c.setFillGray(0.93)
        self.c.rect(self.left, self.y - 4.6 * MM, self.right - self.left, 7 * MM, fill=1, stroke=0)
        self.c.setFillGray(0)
        self.c.setFont(FONT_BOLD, 11.5)
        self.c.drawCentredString(PAGE_W / 2, self.y - 3.2 * MM, rtl(text))
        self.move(10)


def generate_registration_pdf(registration) -> io.BytesIO:
    _register_fonts()
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    f = FormBuilder(c)

    # The club's letterhead — its logos on both sides, its header between
    # them — drawn by the same code as the candidate list's.
    club = registration.club
    bottom = draw_letterhead(
        c, club, top=PAGE_H - 12 * MM, page_w=PAGE_W, margin=f.left,
        regular=FONT_REGULAR, bold=FONT_BOLD, default_logo=ASSETS / 'logo.png',
    )
    f.y = bottom - 6 * MM
    f.centered(f'الموسم الرياضي: {registration.season}', size=10, dy=9)

    f.centered('استمارة الانخراط في رياضة البيندين زا  Binh Dinh Gia', size=13, bold=True, dy=10)

    f.two_col_rtl(f'المرجع: {registration.reference}', f'الفئة: {registration.get_category_display()}')
    f.rule(dy=6)

    f.section_title('المعلومات الشخصية')
    f.two_col_rtl(f'الاسم: {registration.first_name}', f'اللقب: {registration.last_name}')
    f.line_rtl(f'الاسم واللقب بالأحرف اللاتينية: {registration.latin_full_name}')
    f.two_col_rtl(
        f'تاريخ الميلاد: {registration.birth_date.strftime("%Y/%m/%d")}',
        f'مكان الميلاد: {registration.birth_place}',
    )
    f.line_rtl(f'العنوان: {registration.address}')
    f.two_col_rtl(f'رقم هاتف: {registration.phone}', f'السن: {registration.age_at_registration}')
    if registration.education_level or registration.institution:
        f.two_col_rtl(
            f'المستوى الدراسي: {registration.education_level or "—"}',
            f'المؤسسة التعليمية: {registration.institution or "—"}',
        )

    f.section_title('شهادة طبيــــــــــــة')
    f.line_rtl('نحن الطبيب: ..........................................................................')
    f.line_rtl(f'قمنا بفحص السيد(ة): {registration.first_name} {registration.last_name}')
    f.move(2)
    f.two_col_rtl('نشهد أنه مؤهل لممارسة الرياضة', 'امضاء وختم الطبيب')
    f.move(10)

    if registration.is_minor:
        f.section_title('رخصــــــة أبويـــــــــــــة')
        f.line_rtl(f'أنا السيد: {registration.parent_name or "..."}')
        id_type_label = 'بطاقة التعريف الوطنية' if registration.parent_id_type == 'CNI' else 'رخصة السياقة'
        f.two_col_rtl(
            f'صاحب {id_type_label} رقم: {registration.parent_id_number or "..."}',
            f'الصادرة بتاريخ: {registration.parent_id_issue_date.strftime("%Y/%m/%d") if registration.parent_id_issue_date else "..."}',
        )
        wrapped = (
            f'أرخص لابني: {registration.first_name} {registration.last_name} بالانخراط ب{club_heading(club)} '
            'بغرض ممارسة الفن القتالي بيندين زا، والمشاركة في التظاهرات والمنافسات '
            'الرياضية وكذلك التنقلات داخل وخارج تراب الولاية، كما أتعهد بدفع حقوق المساهمة الشهرية بانتظام.'
        )
        for chunk in _wrap_arabic(wrapped, width=78):
            f.ensure_space(8)
            f.line_rtl(chunk, size=9.5, dy=5.2)
        f.move(6)
        f.two_col_rtl('امضاء الولي', 'مصادقة مصالح البلدية')
        f.move(10)

    f.section_title('ملف الانخراط')
    is_minor = registration.is_minor
    docs = RequiredDocument.objects.filter(active=True).filter(
        Q(applies_to='ALL') | Q(applies_to='MINOR' if is_minor else 'MAJOR')
    ).order_by('order')
    uploaded_keys = set(
        UploadedDocument.objects.filter(registration=registration).values_list('required_document__key', flat=True)
    )
    f.line_rtl('[X] استمارة الانخراط', size=10, dy=5.5)
    for doc in docs:
        f.ensure_space(8)
        mark = '[X]' if doc.key in uploaded_keys else '[  ]'
        suffix = ' (اختياري)' if not doc.required else ''
        f.line_rtl(f'{mark} {doc.label_ar}{suffix}', size=10, dy=5.5)

    f.move(12)
    c.setFont(FONT_REGULAR, 8)
    c.setFillGray(0.4)
    c.drawCentredString(PAGE_W / 2, f.y, rtl(f'{registration.reference} — {SiteSettings.load().active_season}'))

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer


def _wrap_arabic(text: str, width: int = 78) -> list[str]:
    words = text.split(' ')
    lines: list[str] = []
    current = ''
    for word in words:
        candidate = f'{current} {word}'.strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines
