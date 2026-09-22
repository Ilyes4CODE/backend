from django.contrib import admin

from .models import RequiredDocument, Registration, SiteSettings, UploadedDocument


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    list_display = ['active_season']


@admin.register(RequiredDocument)
class RequiredDocumentAdmin(admin.ModelAdmin):
    list_display = ['key', 'label_en', 'applies_to', 'required', 'order', 'active']
    list_filter = ['applies_to', 'required', 'active']


class UploadedDocumentInline(admin.TabularInline):
    model = UploadedDocument
    extra = 0


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = ['reference', 'first_name', 'last_name', 'category', 'is_minor', 'status', 'payment_status', 'created_at']
    list_filter = ['category', 'is_minor', 'status', 'payment_status', 'season']
    search_fields = ['reference', 'first_name', 'last_name', 'latin_full_name', 'phone']
    inlines = [UploadedDocumentInline]
