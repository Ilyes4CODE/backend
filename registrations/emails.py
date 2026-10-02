"""Telling candidates the club's decision, by email.

The email is written in the language the candidate filled the form in, comes
from the club — its name on the sender, its address to reply to — and carries
the club's logo and the platform's illustrations inside the message itself.
Embedded images show in Gmail and Outlook without the "display images" click
that linked ones need.

A decision is saved before the email is attempted, and stands whatever happens
to it: notify_decision() records whether the candidate was told, so the
dashboard can offer to try again.
"""

import io
import logging
from email.mime.image import MIMEImage
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone
from PIL import Image

logger = logging.getLogger(__name__)

ASSETS = Path(__file__).resolve().parent / 'assets'
EMAIL_ASSETS = ASSETS / 'email'

# The frontend carries the same names; these are for the email alone, which
# has no access to the site's translations.
CATEGORY_NAMES = {
    'ar': {
        'SENIOR': 'كبار', 'VETERAN': 'أكابر', 'JUNIOR': 'أواسط', 'CADET': 'أشبال',
        'MINIME': 'صغار', 'BENJAMIN': 'براعم', 'POUSSIN': 'كتاكيت', 'MINIBAD': 'أصاغر جداً',
    },
    'en': {
        'SENIOR': 'Seniors', 'VETERAN': 'Veterans', 'JUNIOR': 'Juniors', 'CADET': 'Cadets',
        'MINIME': 'Minimes', 'BENJAMIN': 'Benjamins', 'POUSSIN': 'Poussins', 'MINIBAD': 'Minibad',
    },
    'vi': {
        'SENIOR': 'Người lớn', 'VETERAN': 'Lão tướng', 'JUNIOR': 'Thiếu niên lớn', 'CADET': 'Thiếu niên',
        'MINIME': 'Thiếu nhi lớn', 'BENJAMIN': 'Thiếu nhi', 'POUSSIN': 'Nhi đồng', 'MINIBAD': 'Mẫu giáo',
    },
}

STRINGS = {
    'ar': {
        'dir': 'rtl', 'align': 'right',
        'greeting': 'مرحباً {name}،',
        'approved_subject': 'تم قبول طلب انخراطك — {club}',
        'approved_preheader': 'مرحباً بك في {club}! طلبك {reference} مقبول.',
        'approved_title': 'مرحباً بك في النادي!',
        'approved_intro': 'يسعدنا إعلامك بأن طلب انخراطك في {club} قد قُبل.',
        'approved_next': 'الخطوة التالية: توجّه إلى فرعك لإتمام إجراءات الدفع واستلام بطاقة العضوية.',
        'rejected_subject': 'بخصوص طلب انخراطك — {club}',
        'rejected_preheader': 'معلومات حول طلبك {reference}.',
        'rejected_title': 'لم نتمكن من قبول طلبك',
        'rejected_intro': 'شكراً لاهتمامك بالانضمام إلى {club}. بعد دراسة طلبك، نأسف لإعلامك بأنه لم يُقبل.',
        'rejected_next': 'يمكنك تقديم طلب جديد بعد معالجة هذا السبب. يسعدنا انضمامك متى كان ذلك ممكناً.',
        'reason_label': 'السبب',
        'note_label': 'ملاحظة من النادي',
        'details_title': 'تفاصيل الطلب',
        'reference': 'المرجع', 'name': 'الاسم', 'category': 'الفئة',
        'branch': 'الفرع', 'season': 'الموسم الرياضي',
        'view_button': 'عرض طلبك',
        'register_button': 'تقديم طلب جديد',
        'contact': 'للتواصل مع النادي',
        'automated': 'هذه رسالة آلية، يرجى عدم الرد عليها مباشرة.',
        'reasons': {
            'INCOMPLETE': 'الملف غير مكتمل',
            'UNREADABLE': 'بعض الوثائق غير واضحة أو غير مقروءة',
            'MISMATCH': 'المعلومات لا تطابق الوثائق المرفوعة',
            'NO_PLACE': 'لا توجد أماكن شاغرة في هذه الفئة حالياً',
            'DUPLICATE': 'تسجيل مكرر',
            'OTHER': 'سبب آخر',
        },
    },
    'en': {
        'dir': 'ltr', 'align': 'left',
        'greeting': 'Hello {name},',
        'approved_subject': 'Your registration has been accepted — {club}',
        'approved_preheader': 'Welcome to {club}! Registration {reference} is accepted.',
        'approved_title': 'Welcome to the club!',
        'approved_intro': 'We are glad to let you know that your registration with {club} has been accepted.',
        'approved_next': 'Next step: visit your branch to complete payment and collect your membership card.',
        'rejected_subject': 'About your registration — {club}',
        'rejected_preheader': 'An update on registration {reference}.',
        'rejected_title': 'We could not accept your registration',
        'rejected_intro': 'Thank you for wanting to join {club}. Having reviewed your registration, we are sorry to tell you it was not accepted.',
        'rejected_next': 'You are welcome to register again once this has been addressed. We would be glad to have you.',
        'reason_label': 'Reason',
        'note_label': 'A note from the club',
        'details_title': 'Registration details',
        'reference': 'Reference', 'name': 'Name', 'category': 'Category',
        'branch': 'Branch', 'season': 'Season',
        'view_button': 'View your registration',
        'register_button': 'Register again',
        'contact': 'To contact the club',
        'automated': 'This is an automated message; please do not reply to it directly.',
        'reasons': {
            'INCOMPLETE': 'The file is incomplete',
            'UNREADABLE': 'Some documents are unclear or unreadable',
            'MISMATCH': 'The information does not match the documents uploaded',
            'NO_PLACE': 'There is no place left in this category at the moment',
            'DUPLICATE': 'Duplicate registration',
            'OTHER': 'Another reason',
        },
    },
    'vi': {
        'dir': 'ltr', 'align': 'left',
        'greeting': 'Xin chào {name},',
        'approved_subject': 'Đơn đăng ký của bạn đã được chấp nhận — {club}',
        'approved_preheader': 'Chào mừng đến với {club}! Đơn {reference} đã được chấp nhận.',
        'approved_title': 'Chào mừng bạn đến với câu lạc bộ!',
        'approved_intro': 'Chúng tôi vui mừng thông báo đơn đăng ký của bạn tại {club} đã được chấp nhận.',
        'approved_next': 'Bước tiếp theo: hãy đến chi nhánh của bạn để hoàn tất thanh toán và nhận thẻ hội viên.',
        'rejected_subject': 'Về đơn đăng ký của bạn — {club}',
        'rejected_preheader': 'Thông tin về đơn {reference}.',
        'rejected_title': 'Chúng tôi chưa thể chấp nhận đơn của bạn',
        'rejected_intro': 'Cảm ơn bạn đã muốn tham gia {club}. Sau khi xem xét, chúng tôi rất tiếc phải thông báo đơn của bạn chưa được chấp nhận.',
        'rejected_next': 'Bạn có thể đăng ký lại sau khi khắc phục lý do này. Chúng tôi luôn sẵn lòng chào đón bạn.',
        'reason_label': 'Lý do',
        'note_label': 'Ghi chú từ câu lạc bộ',
        'details_title': 'Chi tiết đơn đăng ký',
        'reference': 'Mã đơn', 'name': 'Họ tên', 'category': 'Hạng mục',
        'branch': 'Chi nhánh', 'season': 'Mùa giải',
        'view_button': 'Xem đơn của bạn',
        'register_button': 'Đăng ký lại',
        'contact': 'Liên hệ câu lạc bộ',
        'automated': 'Đây là thư tự động, vui lòng không trả lời trực tiếp.',
        'reasons': {
            'INCOMPLETE': 'Hồ sơ chưa đầy đủ',
            'UNREADABLE': 'Một số giấy tờ không rõ hoặc không đọc được',
            'MISMATCH': 'Thông tin không khớp với giấy tờ đã tải lên',
            'NO_PLACE': 'Hạng mục này hiện đã hết chỗ',
            'DUPLICATE': 'Đăng ký trùng lặp',
            'OTHER': 'Lý do khác',
        },
    },
}


def _image_bytes(path, max_width, photo):
    """A file shrunk for email: a 2 MB logo has no business in an inbox.

    Illustrations sit on a solid background and go out as JPEG; logos keep
    their transparency as PNG.
    """
    try:
        with Image.open(path) as image:
            image.thumbnail((max_width, max_width * 4))
            buffer = io.BytesIO()
            if photo:
                image.convert('RGB').save(buffer, 'JPEG', quality=82, optimize=True, progressive=True)
                return buffer.getvalue(), 'jpeg'
            image.save(buffer, 'PNG', optimize=True)
            return buffer.getvalue(), 'png'
    except Exception:  # noqa: BLE001 - a missing or broken picture just stays out
        return None, None


def _club_logo_path(club):
    if club is not None and club.logo:
        try:
            path = Path(club.logo.path)
            if path.exists():
                return path
        except (NotImplementedError, ValueError):
            pass
    return ASSETS / 'logo.png'


def build_decision_email(registration) -> EmailMultiAlternatives:
    approved = registration.status == 'APPROVED'
    language = registration.language if registration.language in STRINGS else 'ar'
    words = STRINGS[language]
    club = registration.club
    center = registration.center

    def localised(obj):
        if obj is None:
            return ''
        return (obj.name_ar if language == 'ar' else obj.name_en) or obj.name_en or obj.name_ar

    club_name = localised(club) or ('بيندين زا' if language == 'ar' else 'Binh Dinh Gia')
    full_name = f'{registration.first_name} {registration.last_name}'.strip()
    fill = {'club': club_name, 'reference': registration.reference, 'name': full_name}
    prefix = 'approved' if approved else 'rejected'

    # The pictures, embedded and referenced by Content-ID. Whatever is missing
    # simply stays out of the layout.
    images = {}
    for cid, path, width, photo in (
        ('logo', _club_logo_path(club), 160, False),
        ('header', EMAIL_ASSETS / 'email-header.png', 1200, True),
        ('hero', EMAIL_ASSETS / f'email-{prefix}.png', 1100, True),
    ):
        if Path(path).exists():
            data, subtype = _image_bytes(path, width, photo)
            if data:
                images[cid] = (data, subtype)

    reason = ''
    if not approved and registration.rejection_reason:
        reason = words['reasons'].get(registration.rejection_reason, '')
        if registration.rejection_reason == 'OTHER' and registration.rejection_note:
            reason = ''          # the note is the reason; no need to say "other"

    details = [
        (words['reference'], registration.reference),
        (words['name'], full_name),
        (words['category'], CATEGORY_NAMES[language].get(registration.category, registration.category)),
    ]
    if center is not None:
        details.append((words['branch'], localised(center)))
    details.append((words['season'], registration.season))

    site = settings.SITE_URL
    context = {
        'words': words,
        'approved': approved,
        'subject': words[f'{prefix}_subject'].format(**fill),
        'preheader': words[f'{prefix}_preheader'].format(**fill),
        'title': words[f'{prefix}_title'],
        'greeting': words['greeting'].format(**fill),
        'intro': words[f'{prefix}_intro'].format(**fill),
        'next': words[f'{prefix}_next'],
        'reason': reason,
        'note': registration.rejection_note if not approved else '',
        'details': details,
        'club_name': club_name,
        'club_email': getattr(club, 'email', '') or '',
        'club_phone': getattr(club, 'phone', '') or '',
        'button_label': words['view_button'] if approved else words['register_button'],
        'button_url': f'{site}/register/{registration.reference}' if approved else f'{site}/register',
        'site_url': site,
        'has': {cid: True for cid in images},
        'lang': language,
    }

    html = render_to_string('registrations/emails/decision.html', context)
    text = render_to_string('registrations/emails/decision.txt', context)

    # From the club, by name, through the platform's mailbox; replies go to
    # the club when it has an address, not to a no-reply box.
    sender = f'{club_name} <{settings.DEFAULT_FROM_EMAIL}>'
    message = EmailMultiAlternatives(
        subject=context['subject'], body=text, from_email=sender, to=[registration.email],
        reply_to=[club.email] if club is not None and club.email else None,
    )
    message.attach_alternative(html, 'text/html')
    if images:
        message.mixed_subtype = 'related'
        for cid, (data, subtype) in images.items():
            part = MIMEImage(data, _subtype=subtype)
            part.add_header('Content-ID', f'<{cid}>')
            part.add_header('Content-Disposition', 'inline', filename=f'{cid}.{subtype}')
            message.attach(part)
    return message


def notify_decision(registration) -> str:
    """Email the current decision; record and return whether it went.

    Never raises: the decision is already saved, and a mail server's bad day
    must not turn it into an error page.
    """
    from .models import Registration

    if not registration.email:
        status = Registration.EMAIL_NONE
    else:
        try:
            build_decision_email(registration).send(fail_silently=False)
            status = Registration.EMAIL_SENT
        except Exception:  # noqa: BLE001 - logged, recorded, offered for resending
            logger.exception('Decision email for %s failed', registration.reference)
            status = Registration.EMAIL_FAILED

    registration.decision_email_status = status
    registration.decision_email_at = timezone.now()
    registration.save(update_fields=['decision_email_status', 'decision_email_at', 'updated_at'])
    return status
