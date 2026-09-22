from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models
from rest_framework import serializers

from registrations.models import Registration

from .models import Center, Club, TrainingGroup, UserProfile, WeeklySession, Wilaya

User = get_user_model()


def sync_club_ownership(user, profile):
    """Keep `Club.owner` and `UserProfile.club` telling the same story.

    Assigning someone as a club owner on the Accounts screen used to set only
    the profile, so the Clubs screen went on reporting the club as unowned.
    Whichever screen makes the change, both sides are updated here.
    """
    # Drop any club this user owned but is no longer attached to.
    stale = Club.objects.filter(owner=user)
    if profile.role == UserProfile.CLUB_OWNER and profile.club_id:
        stale = stale.exclude(pk=profile.club_id)
    stale.update(owner=None)

    if profile.role == UserProfile.CLUB_OWNER and profile.club_id:
        Club.objects.filter(pk=profile.club_id).update(owner=user)


class WilayaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wilaya
        fields = ['id', 'code', 'name_ar', 'name_en']


class CenterSerializer(serializers.ModelSerializer):
    managers = serializers.SerializerMethodField()
    registration_count = serializers.SerializerMethodField()

    class Meta:
        model = Center
        fields = ['id', 'club', 'name_ar', 'name_en', 'address', 'active',
                  'managers', 'registration_count']

    def get_managers(self, obj):
        rows = (
            UserProfile.objects
            .filter(center=obj, role=UserProfile.BRANCH_MANAGER)
            .select_related('user')
            .order_by('user__email')
        )
        return [
            {
                'id': p.user_id,
                'email': p.user.email,
                'full_name': p.full_name,
                'is_active': p.user.is_active,
                'last_login': p.user.last_login,
            }
            for p in rows
        ]

    def get_registration_count(self, obj) -> int:
        return obj.registrations.count()


class ClubSerializer(serializers.ModelSerializer):
    centers = CenterSerializer(many=True, read_only=True)
    wilaya_name_ar = serializers.CharField(source='wilaya.name_ar', read_only=True)
    wilaya_name_en = serializers.CharField(source='wilaya.name_en', read_only=True)
    owner_username = serializers.CharField(source='owner.username', read_only=True)
    owner_name = serializers.SerializerMethodField()
    registration_count = serializers.SerializerMethodField()

    class Meta:
        model = Club
        fields = [
            'id', 'wilaya', 'wilaya_name_ar', 'wilaya_name_en',
            'name_ar', 'name_en', 'owner', 'owner_username', 'owner_name',
            'address', 'phone', 'email', 'active', 'centers', 'registration_count',
        ]

    def get_registration_count(self, obj) -> int:
        return obj.registrations.count()

    def get_owner_name(self, obj) -> str:
        """Display name for the owner — their full name if we have one."""
        if not obj.owner:
            return ''
        profile = UserProfile.objects.filter(user=obj.owner).first()
        return (profile.full_name if profile and profile.full_name else '') or obj.owner.username

    def _attach_owner(self, club):
        """Setting an owner here must also scope that account to this club,
        otherwise they would sign in and see nothing."""
        if club.owner_id is None:
            return
        profile, _ = UserProfile.objects.get_or_create(user=club.owner)
        if not profile.is_super_admin:
            profile.role = UserProfile.CLUB_OWNER
            profile.club = club
            profile.center = None
            profile.save(update_fields=['role', 'club', 'center'])
        Club.objects.filter(owner=club.owner).exclude(pk=club.pk).update(owner=None)

    def create(self, validated_data):
        club = super().create(validated_data)
        self._attach_owner(club)
        return club

    def update(self, instance, validated_data):
        club = super().update(instance, validated_data)
        self._attach_owner(club)
        return club


class ClubPublicSerializer(serializers.ModelSerializer):
    """What the public registration form needs — no owner or contact details."""

    centers = serializers.SerializerMethodField()

    class Meta:
        model = Club
        fields = ['id', 'wilaya', 'name_ar', 'name_en', 'centers']

    def get_centers(self, obj):
        return CenterSerializer(obj.centers.filter(active=True), many=True).data


class AdminUserSerializer(serializers.ModelSerializer):
    """Dashboard accounts. The email *is* the username, so staff have one
    credential to remember.

    Who may issue what:
      national administrator -> any role, any club, any branch
      club president         -> branch-manager accounts, for their own club's
                                branches only
      branch manager         -> nothing (blocked before it reaches here)
    """

    email = serializers.EmailField(required=True)
    role = serializers.ChoiceField(source='profile.role', choices=UserProfile.ROLE_CHOICES)
    club = serializers.PrimaryKeyRelatedField(
        source='profile.club', queryset=Club.objects.all(), allow_null=True, required=False,
    )
    club_name = serializers.CharField(source='profile.club.name_en', read_only=True, default='')
    center = serializers.PrimaryKeyRelatedField(
        source='profile.center', queryset=Center.objects.all(), allow_null=True, required=False,
    )
    center_name = serializers.CharField(source='profile.center.name_en', read_only=True, default='')
    full_name = serializers.CharField(source='profile.full_name', required=False, allow_blank=True)
    phone = serializers.CharField(source='profile.phone', required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'password', 'role', 'club', 'club_name',
                  'center', 'center_name', 'full_name', 'phone', 'is_active', 'last_login']
        # Mirrored from the email on save, never typed in.
        read_only_fields = ['last_login', 'username']

    def _requester(self):
        from .models import profile_for
        request = self.context.get('request')
        return profile_for(request.user) if request else None

    def validate_password(self, value):
        if value:
            try:
                validate_password(value)
            except DjangoValidationError as exc:
                raise serializers.ValidationError(list(exc.messages))
        return value

    def validate_email(self, value):
        value = value.strip().lower()
        clash = User.objects.filter(models.Q(email__iexact=value) | models.Q(username__iexact=value))
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError('An account with this email already exists.')
        return value

    def validate(self, attrs):
        profile_in = attrs.get('profile', {})
        current = getattr(self.instance, 'profile', None)

        role = profile_in.get('role') or (current.role if current else None)
        club = profile_in['club'] if 'club' in profile_in else (current.club if current else None)
        center = profile_in['center'] if 'center' in profile_in else (current.center if current else None)

        # Everyone signs in with a password; the creator sets the first one.
        # (Previously a blank one fell through to make_random_password(),
        # which Django 5.1 removed — creating such an account crashed.)
        if self.instance is None and not attrs.get('password'):
            raise serializers.ValidationError({'password': 'Set a password for the new account.'})

        if role == UserProfile.BRANCH_MANAGER:
            if not center:
                raise serializers.ValidationError(
                    {'center': 'A branch manager must be assigned to a branch.'})
            # The club always follows the branch, so the two can never disagree.
            club = center.club
            profile_in['club'] = club
        else:
            # Only branch managers carry a branch.
            profile_in['center'] = None
            center = None

        if role == UserProfile.CLUB_OWNER and not club:
            # A club president with no club would see nothing at all.
            raise serializers.ValidationError(
                {'club': 'A club president must be assigned to a club.'})

        requester = self._requester()
        if requester and not requester.is_super_admin:
            # A president issues branch-manager accounts and nothing else:
            # never another president, never a national administrator.
            if role != UserProfile.BRANCH_MANAGER:
                raise serializers.ValidationError(
                    {'role': 'You can only create branch manager accounts.'})
            if center is None or center.club_id != requester.club_id:
                raise serializers.ValidationError(
                    {'center': 'That branch does not belong to your club.'})

        if self.instance is not None and attrs.get('is_active') is False:
            request = self.context.get('request')
            if request and self.instance.pk == request.user.pk:
                raise serializers.ValidationError(
                    {'is_active': 'You cannot deactivate your own account.'})

        attrs['profile'] = profile_in
        return attrs

    def create(self, validated_data):
        profile_data = validated_data.pop('profile', {})
        password = validated_data.pop('password')
        email = validated_data.pop('email')

        user = User.objects.create_user(username=email, email=email, **validated_data)
        user.set_password(password)
        user.is_staff = True
        user.save()

        profile, _ = UserProfile.objects.update_or_create(user=user, defaults=profile_data)
        sync_club_ownership(user, profile)
        return user

    def update(self, instance, validated_data):
        profile_data = validated_data.pop('profile', {})
        password = validated_data.pop('password', '')

        if 'email' in validated_data:
            # Keep the login name in step with the address.
            instance.email = validated_data.pop('email')
            instance.username = instance.email
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password:
            instance.set_password(password)
        instance.save()

        profile, _ = UserProfile.objects.update_or_create(user=instance, defaults=profile_data)
        sync_club_ownership(instance, profile)
        return instance


class WeeklySessionSerializer(serializers.ModelSerializer):
    weekday_display = serializers.CharField(source='get_weekday_display', read_only=True)
    # A timetable reads "17:30", never "17:30:00" — and the <input type="time">
    # that posts these sends either form.
    start_time = serializers.TimeField(format='%H:%M', input_formats=['%H:%M', '%H:%M:%S'])
    end_time = serializers.TimeField(format='%H:%M', input_formats=['%H:%M', '%H:%M:%S'])

    class Meta:
        model = WeeklySession
        fields = ['id', 'group', 'weekday', 'weekday_display', 'start_time', 'end_time', 'note']
        read_only_fields = ['group']

    def validate(self, attrs):
        start = attrs.get('start_time') or getattr(self.instance, 'start_time', None)
        end = attrs.get('end_time') or getattr(self.instance, 'end_time', None)
        if start and end and end <= start:
            raise serializers.ValidationError({'end_time': 'The session must end after it starts.'})
        return attrs


class GroupMemberSerializer(serializers.ModelSerializer):
    """The slim view of a member used inside a group."""

    full_name = serializers.SerializerMethodField()
    category_display = serializers.CharField(source='get_category_display', read_only=True)

    class Meta:
        model = Registration
        fields = ['id', 'reference', 'full_name', 'latin_full_name', 'gender',
                  'category', 'category_display', 'payment_status']

    def get_full_name(self, obj) -> str:
        return f'{obj.first_name} {obj.last_name}'.strip()


class TrainingGroupSerializer(serializers.ModelSerializer):
    sessions = WeeklySessionSerializer(many=True, read_only=True)
    members = GroupMemberSerializer(many=True, read_only=True)
    member_ids = serializers.PrimaryKeyRelatedField(
        source='members', many=True, write_only=True, required=False,
        queryset=Registration.objects.all(),
    )
    club_name = serializers.CharField(source='club.name_en', read_only=True)
    center_name = serializers.CharField(source='center.name_en', read_only=True, default='')
    member_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = TrainingGroup
        fields = ['id', 'club', 'club_name', 'center', 'center_name', 'name_ar', 'name_en',
                  'coach', 'capacity', 'active', 'sessions', 'members', 'member_ids',
                  'member_count', 'created_at']

    def validate(self, attrs):
        club = attrs.get('club') or getattr(self.instance, 'club', None)
        center = attrs.get('center') if 'center' in attrs else getattr(self.instance, 'center', None)
        if center and club and center.club_id != club.id:
            raise serializers.ValidationError({'center': 'That center belongs to a different club.'})

        # Members must come from the same club, or a group could quietly hold
        # someone another club is responsible for.
        for member in attrs.get('members', []):
            if club and member.club_id != club.id:
                raise serializers.ValidationError(
                    {'member_ids': f'{member.reference} is not registered with this club.'}
                )
        return attrs


class ActivityLogSerializer(serializers.ModelSerializer):
    action_display = serializers.CharField(source='get_action_display', read_only=True)
    club_name = serializers.CharField(source='club.name_en', read_only=True, default='')
    center_name = serializers.CharField(source='center.name_en', read_only=True, default='')

    class Meta:
        from .activity import ActivityLog
        model = ActivityLog
        fields = ['id', 'actor_label', 'action', 'action_display', 'target', 'detail',
                  'club', 'club_name', 'center', 'center_name', 'created_at']
