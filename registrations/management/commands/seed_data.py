import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from registrations.models import RequiredDocument, SiteSettings

DEFAULT_REQUIRED_DOCUMENTS = [
    dict(key='birth_certificate', label_ar='شهادة ميلاد', label_en='Birth certificate',
         label_vi='Giấy khai sinh', applies_to='MINOR', required=True, order=1),
    dict(key='national_id_copy', label_ar='نسخة من بطاقة التعريف الوطنية', label_en='National ID copy',
         label_vi='Bản sao chứng minh nhân dân', applies_to='MAJOR', required=True, order=1),
    dict(key='photos', label_ar='صورتان شمسيتان', label_en='2 ID photos',
         label_vi='2 ảnh chân dung', applies_to='ALL', required=True, order=2),
    dict(key='blood_type_card', label_ar='صورة طبق الأصل لبطاقة زمرة الدم', label_en='Blood type card copy',
         label_vi='Bản sao thẻ nhóm máu', applies_to='ALL', required=True, order=3),
    dict(key='medical_certificate', label_ar='شهادة طبية ممضاة ومختومة', label_en='Signed medical certificate',
         label_vi='Giấy chứng nhận sức khỏe có chữ ký', applies_to='ALL', required=True, order=4),
]


class Command(BaseCommand):
    help = 'Seed the default admin account, required-document list, and site settings.'

    def handle(self, *args, **options):
        SiteSettings.load()
        self.stdout.write(self.style.SUCCESS('Site settings ready.'))

        for doc in DEFAULT_REQUIRED_DOCUMENTS:
            obj, created = RequiredDocument.objects.get_or_create(key=doc['key'], defaults=doc)
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created required document: {obj.key}'))

        User = get_user_model()
        username = os.environ.get('ADMIN_USERNAME', 'admin')
        password = os.environ.get('ADMIN_PASSWORD', 'BinhDinhGia2026!')
        if not User.objects.filter(username=username).exists():
            User.objects.create_superuser(username=username, password=password, email='admin@binhdinhgia.local')
            self.stdout.write(self.style.SUCCESS(
                f'Created admin user "{username}". Set ADMIN_USERNAME/ADMIN_PASSWORD env vars to customize.'
            ))
        else:
            self.stdout.write(f'Admin user "{username}" already exists, skipping.')
