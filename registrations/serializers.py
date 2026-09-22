from rest_framework import serializers

from .categorization import CATEGORY_CHOICES
from .models import RequiredDocument, Registration, SiteSettings, UploadedDocument


class SiteSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteSettings
        fields = [
            'active_season', 'registrations_open',
            'closed_message_ar', 'closed_message_en', 'closed_message_vi',
        ]


class RequiredDocumentPublicSerializer(serializers.ModelSerializer):
    class Meta:
        model = RequiredDocument
        fields = ['id', 'key', 'label_ar', 'label_en', 'label_vi', 'required', 'applies_to']


class RequiredDocumentAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = RequiredDocument
        fields = ['id', 'key', 'label_ar', 'label_en', 'label_vi', 'applies_to', 'required', 'order', 'active']
        # Generated from the label on save — the admin never types it.
        read_only_fields = ['key']


class RegistrationCreateSerializer(serializers.ModelSerializer):
    parent_id_issue_date = serializers.DateField(required=False, allow_null=True)

    class Meta:
        model = Registration
        fields = [
            'club', 'center',
            'first_name', 'last_name', 'latin_full_name', 'gender', 'birth_date', 'birth_place',
            'address', 'phone', 'education_level', 'institution',
            'parent_name', 'parent_id_type', 'parent_id_number', 'parent_id_issue_date',
        ]
        extra_kwargs = {
            'club': {'required': True, 'allow_null': False},
            'center': {'required': False, 'allow_null': True},
            # The column allows blank for rows that predate the field, but every
            # new submission must state it.
            'gender': {'required': True, 'allow_blank': False},
            'education_level': {'required': False},
            'institution': {'required': False},
            'parent_name': {'required': False},
            'parent_id_type': {'required': False},
            'parent_id_number': {'required': False},
        }

    def validate(self, attrs):
        # A center always belongs to exactly one club; accepting a mismatched
        # pair would file the candidate under a center their club doesn't run.
        club, center = attrs.get('club'), attrs.get('center')
        if club and center and center.club_id != club.id:
            raise serializers.ValidationError(
                {'center': 'That center does not belong to the selected club.'}
            )
        return attrs


class UploadedDocumentSerializer(serializers.ModelSerializer):
    document_key = serializers.CharField(source='required_document.key', read_only=True)
    label_en = serializers.CharField(source='required_document.label_en', read_only=True)
    label_ar = serializers.CharField(source='required_document.label_ar', read_only=True)
    label_vi = serializers.CharField(source='required_document.label_vi', read_only=True)

    class Meta:
        model = UploadedDocument
        fields = ['id', 'document_key', 'label_en', 'label_ar', 'label_vi', 'original_name', 'uploaded_at']


class RegistrationDetailSerializer(serializers.ModelSerializer):
    documents = UploadedDocumentSerializer(many=True, read_only=True)
    gender_display = serializers.CharField(source='get_gender_display', read_only=True)
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    club_name = serializers.CharField(source='club.name_en', read_only=True, default='')
    club_name_ar = serializers.CharField(source='club.name_ar', read_only=True, default='')
    center_name = serializers.CharField(source='center.name_en', read_only=True, default='')
    wilaya_name = serializers.CharField(source='club.wilaya.name_en', read_only=True, default='')

    class Meta:
        model = Registration
        fields = [
            'id', 'reference', 'club', 'club_name', 'club_name_ar', 'center', 'center_name',
            'wilaya_name', 'first_name', 'last_name', 'latin_full_name',
            'gender', 'gender_display',
            'birth_date', 'birth_place', 'address', 'phone', 'education_level', 'institution',
            'category', 'category_display', 'is_minor', 'age_at_registration',
            'parent_name', 'parent_id_type', 'parent_id_number', 'parent_id_issue_date',
            'status', 'payment_status', 'season', 'created_at', 'documents',
        ]


class RegistrationListSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    gender_display = serializers.CharField(source='get_gender_display', read_only=True)
    document_count = serializers.IntegerField(source='documents.count', read_only=True)
    club_name = serializers.CharField(source='club.name_en', read_only=True, default='')
    center_name = serializers.CharField(source='center.name_en', read_only=True, default='')

    class Meta:
        model = Registration
        fields = [
            'id', 'reference', 'first_name', 'last_name', 'gender', 'gender_display',
            'category', 'category_display',
            'is_minor', 'age_at_registration', 'status', 'payment_status', 'season',
            'created_at', 'document_count', 'club_name', 'center_name',
        ]


class RegistrationAdminUpdateSerializer(serializers.ModelSerializer):
    """What staff may change on a candidate.

    Status and payment: anyone who can see the candidate — the branch manager
    collecting the fee included. Every change is written to the activity log.

    Branch (a transfer): the president or the national admin only, and only to
    a branch of the candidate's own club. A branch manager cannot move a member
    out — or pull one in, since that would mean seeing the other branch.
    """

    class Meta:
        model = Registration
        fields = ['status', 'payment_status', 'center']
        extra_kwargs = {'center': {'required': False, 'allow_null': True}}

    def validate_center(self, center):
        from organization.models import profile_for

        request = self.context.get('request')
        profile = profile_for(request.user) if request else None
        if profile is None or profile.is_branch_manager:
            raise serializers.ValidationError(
                'Only the club president can move a member to another branch.')
        if center is not None and self.instance and center.club_id != self.instance.club_id:
            raise serializers.ValidationError(
                "That branch does not belong to this candidate's club.")
        return center
