"""The ID-photo document stays an image.

file_kind arrives defaulting to a scanned PDF, which is right for official
papers. The photo is different: the membership card prints it, and a PDF
cannot be printed as a portrait. The same rule the card uses to find the photo
— "photo" in the key — picks it out here.
"""

from django.db import migrations


def photos_are_images(apps, schema_editor):
    RequiredDocument = apps.get_model('registrations', 'RequiredDocument')
    RequiredDocument.objects.filter(key__icontains='photo').update(file_kind='IMAGE')


def back_to_default(apps, schema_editor):
    RequiredDocument = apps.get_model('registrations', 'RequiredDocument')
    RequiredDocument.objects.update(file_kind='SCAN_PDF')


class Migration(migrations.Migration):

    dependencies = [
        ('registrations', '0005_email_decisions_scans'),
    ]

    operations = [
        migrations.RunPython(photos_are_images, back_to_default),
    ]
