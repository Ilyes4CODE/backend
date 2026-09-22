import uuid

from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils.text import slugify

from .categorization import CATEGORY_CHOICES


class SiteSettings(models.Model):
    """Singleton row holding club-wide settings editable by the admin."""

    active_season = models.CharField(max_length=20, default='2025/2026')

    # The admin opens and closes the registration window from the dashboard.
    registrations_open = models.BooleanField(default=True)
    closed_message_ar = models.CharField(max_length=300, blank=True)
    closed_message_en = models.CharField(max_length=300, blank=True)
    closed_message_vi = models.CharField(max_length=300, blank=True)

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> 'SiteSettings':
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return f'Site settings ({self.active_season})'


class RequiredDocument(models.Model):
    """A document type the admin requires candidates to upload at registration."""

    APPLIES_TO_CHOICES = [
        ('ALL', 'All candidates'),
        ('MINOR', 'Minors only'),
        ('MAJOR', 'Adults only'),
    ]

    # Internal identifier used in upload field names. Derived from the label so
    # the admin never has to invent one.
    key = models.SlugField(max_length=50, unique=True, blank=True)
    label_ar = models.CharField(max_length=200)
    label_en = models.CharField(max_length=200)
    label_vi = models.CharField(max_length=200)
    applies_to = models.CharField(max_length=5, choices=APPLIES_TO_CHOICES, default='ALL')
    required = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return self.label_en

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = self._unique_key_from_label()
        super().save(*args, **kwargs)

    def _unique_key_from_label(self) -> str:
        base = slugify(self.label_en or self.label_ar or 'document', allow_unicode=False).replace('-', '_')[:40]
        if not base:
            base = 'document'
        candidate, suffix = base, 2
        taken = RequiredDocument.objects.exclude(pk=self.pk)
        while taken.filter(key=candidate).exists():
            candidate = f'{base}_{suffix}'
            suffix += 1
        return candidate


def upload_to_registration(instance: 'UploadedDocument', filename: str) -> str:
    return f'{instance.registration.reference}/{instance.required_document.key}_{filename}'


class Registration(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    ]
    PAYMENT_CHOICES = [
        ('UNPAID', 'Unpaid'),
        ('PAID', 'Paid'),
    ]
    PARENT_ID_TYPE_CHOICES = [
        ('CNI', 'National ID card'),
        ('PERMIS', "Driving license"),
    ]
    GENDER_CHOICES = [
        ('MALE', 'Male'),
        ('FEMALE', 'Female'),
    ]

    reference = models.CharField(max_length=20, unique=True, editable=False)

    # Which club (and optionally which of its centers) the candidate is joining.
    club = models.ForeignKey(
        'organization.Club', null=True, blank=True,
        on_delete=models.PROTECT, related_name='registrations',
    )
    center = models.ForeignKey(
        'organization.Center', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='registrations',
    )

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    latin_full_name = models.CharField(max_length=200)
    # Blank only for rows that predate this field; required on new submissions.
    gender = models.CharField(max_length=6, choices=GENDER_CHOICES, blank=True)
    birth_date = models.DateField()
    birth_place = models.CharField(max_length=150)
    address = models.CharField(max_length=255)
    phone = models.CharField(max_length=30)
    education_level = models.CharField(max_length=150, blank=True)
    institution = models.CharField(max_length=200, blank=True)

    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES, editable=False)
    is_minor = models.BooleanField(editable=False)
    age_at_registration = models.PositiveSmallIntegerField(editable=False)

    parent_name = models.CharField(max_length=200, blank=True)
    parent_id_type = models.CharField(max_length=10, choices=PARENT_ID_TYPE_CHOICES, blank=True)
    parent_id_number = models.CharField(max_length=50, blank=True)
    parent_id_issue_date = models.DateField(null=True, blank=True)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    payment_status = models.CharField(max_length=10, choices=PAYMENT_CHOICES, default='UNPAID')
    season = models.CharField(max_length=20)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.reference} - {self.first_name} {self.last_name}'

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f'BDG-{uuid.uuid4().hex[:8].upper()}'
        super().save(*args, **kwargs)


class UploadedDocument(models.Model):
    registration = models.ForeignKey(Registration, related_name='documents', on_delete=models.CASCADE)
    required_document = models.ForeignKey(RequiredDocument, on_delete=models.PROTECT)
    file = models.FileField(
        upload_to=upload_to_registration,
        validators=[FileExtensionValidator(['pdf', 'jpg', 'jpeg', 'png'])],
    )
    original_name = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('registration', 'required_document')

    def __str__(self):
        return f'{self.registration.reference} / {self.required_document.key}'
