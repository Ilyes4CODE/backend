from django.contrib.auth import get_user_model
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from registrations.models import Registration

from .activity import ActivityLog, record
from .models import (
    Center, Club, TrainingGroup, UserProfile, WeeklySession, Wilaya, profile_for,
)
from .permissions import IsClubLevel, IsSuperAdmin, can_manage_club, scope_queryset_to_club
from .serializers import (
    AdminUserSerializer,
    CenterSerializer,
    ClubPublicSerializer,
    ClubSerializer,
    TrainingGroupSerializer,
    WeeklySessionSerializer,
    WilayaSerializer,
)

User = get_user_model()


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def public_directory(request):
    """Wilayas that actually have an active club, with those clubs and their
    centers — everything the public registration form needs in one call."""
    clubs = Club.objects.filter(active=True).select_related('wilaya').prefetch_related('centers')
    wilaya_ids = {club.wilaya_id for club in clubs}
    return Response({
        'wilayas': WilayaSerializer(Wilaya.objects.filter(id__in=wilaya_ids), many=True).data,
        'clubs': ClubPublicSerializer(clubs, many=True).data,
    })


class WilayaViewSet(viewsets.ReadOnlyModelViewSet):
    """Reference data — seeded, never edited from the dashboard."""

    permission_classes = [permissions.IsAuthenticated]
    queryset = Wilaya.objects.all()
    serializer_class = WilayaSerializer
    pagination_class = None


class ClubViewSet(viewsets.ModelViewSet):
    serializer_class = ClubSerializer
    pagination_class = None

    def get_permissions(self):
        # Presidents read their own club; only the national admin changes clubs.
        # Branch managers are kept out entirely: a club record nests every
        # branch with its managers' emails, which is sideways information.
        if self.request.method in permissions.SAFE_METHODS:
            return [IsClubLevel()]
        return [IsSuperAdmin()]

    def get_queryset(self):
        qs = Club.objects.select_related('wilaya').prefetch_related('centers')
        if wilaya := self.request.query_params.get('wilaya'):
            qs = qs.filter(wilaya_id=wilaya)
        profile = profile_for(self.request.user)
        if profile and not profile.is_super_admin:
            qs = qs.filter(id=profile.club_id) if profile.club_id else qs.none()
        return qs


class CenterViewSet(viewsets.ModelViewSet):
    """Branches (فروع). The national admin manages any; a club president opens
    and runs their own club's; a branch manager reads their own branch only."""

    serializer_class = CenterSerializer
    pagination_class = None

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        return [IsClubLevel()]

    def get_queryset(self):
        qs = Center.objects.select_related('club')
        if club := self.request.query_params.get('club'):
            qs = qs.filter(club_id=club)
        profile = profile_for(self.request.user)
        if profile and profile.is_branch_manager:
            # Their own branch and nothing beside it.
            return qs.filter(pk=profile.center_id) if profile.center_id else qs.none()
        return scope_queryset_to_club(qs, self.request.user)

    def perform_create(self, serializer):
        profile = profile_for(self.request.user)
        if profile and profile.is_club_owner:
            # Whatever club was sent, a president opens branches in their own.
            center = serializer.save(club_id=profile.club_id)
        else:
            center = serializer.save()
        record(self.request.user, ActivityLog.BRANCH_CREATED, center.name_en,
               club=center.club, center=center)

    def perform_update(self, serializer):
        if not can_manage_club(self.request.user, serializer.instance.club_id):
            raise PermissionDenied('That branch belongs to another club.')
        profile = profile_for(self.request.user)
        if profile and profile.is_club_owner:
            # A president cannot hand a branch over to another club.
            center = serializer.save(club_id=profile.club_id)
        else:
            center = serializer.save()
        record(self.request.user, ActivityLog.BRANCH_UPDATED, center.name_en,
               club=center.club, center=center)

    def perform_destroy(self, instance):
        if not can_manage_club(self.request.user, instance.club_id):
            raise PermissionDenied('That branch belongs to another club.')
        # A branch's managers would otherwise keep a working login that sees
        # nothing. Switch them off; the president can reassign them later.
        managers = User.objects.filter(
            profile__center=instance, profile__role=UserProfile.BRANCH_MANAGER)
        for manager in managers:
            if manager.is_active:
                manager.is_active = False
                manager.save(update_fields=['is_active'])
                record(self.request.user, ActivityLog.ACCOUNT_DEACTIVATED, manager.email,
                       club=instance.club, reason='branch deleted')
        record(self.request.user, ActivityLog.BRANCH_DELETED, instance.name_en,
               club=instance.club)
        instance.delete()


class AdminUserViewSet(viewsets.ModelViewSet):
    """Account management.

    The national admin manages every account. A club president manages only the
    branch-manager accounts of their own club — they never see the national
    admin, another president, or anyone from another club.
    """

    permission_classes = [IsClubLevel]
    serializer_class = AdminUserSerializer
    pagination_class = None

    def get_queryset(self):
        qs = User.objects.select_related(
            'profile', 'profile__club', 'profile__center').order_by('username')
        profile = profile_for(self.request.user)
        if profile and profile.is_super_admin:
            return qs
        if profile and profile.is_club_owner and profile.club_id:
            return qs.filter(
                profile__role=UserProfile.BRANCH_MANAGER,
                profile__club_id=profile.club_id,
            )
        return qs.none()

    def perform_create(self, serializer):
        user = serializer.save()
        p = user.profile
        record(self.request.user, ActivityLog.ACCOUNT_CREATED, user.email,
               club=p.club, center=p.center, role=p.role)

    def perform_update(self, serializer):
        was_active = serializer.instance.is_active
        password_changed = bool(self.request.data.get('password'))
        user = serializer.save()
        p = user.profile
        if was_active and not user.is_active:
            action = ActivityLog.ACCOUNT_DEACTIVATED
        elif not was_active and user.is_active:
            action = ActivityLog.ACCOUNT_REACTIVATED
        elif password_changed:
            action = ActivityLog.PASSWORD_RESET
        else:
            action = ActivityLog.ACCOUNT_UPDATED
        record(self.request.user, action, user.email, club=p.club, center=p.center)

    def destroy(self, request, *args, **kwargs):
        # Presidents deactivate; they never delete. Deleting erases who did what,
        # and a president changes more often than the history should.
        profile = profile_for(request.user)
        if not (profile and profile.is_super_admin):
            raise PermissionDenied('Deactivate the account instead of deleting it.')
        return super().destroy(request, *args, **kwargs)

    def perform_destroy(self, instance):
        if instance == self.request.user:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'detail': 'You cannot delete your own account.'})
        instance.delete()


# Identity lives at /api/auth/me/ (accounts app) so there is one source of truth.


class TrainingGroupViewSet(viewsets.ModelViewSet):
    """أفواج. A club owner manages their own club's groups; the super admin all."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TrainingGroupSerializer
    pagination_class = None

    def get_queryset(self):
        qs = (
            TrainingGroup.objects
            .select_related('club', 'center')
            .prefetch_related('sessions', 'members')
        )
        if club := self.request.query_params.get('club'):
            qs = qs.filter(club_id=club)
        if center := self.request.query_params.get('center'):
            qs = qs.filter(center_id=center)
        return scope_queryset_to_club(qs, self.request.user, center_field='center')

    def get_serializer(self, *args, **kwargs):
        # Decide club and branch *before* validation, from who is asking. The
        # serializer checks that the branch belongs to the club; validating the
        # values a caller sent and then overriding them afterwards would reject
        # a request for the wrong reason (or, done the other way round, accept
        # one it should not). For a branch manager, what they send is irrelevant.
        profile = profile_for(self.request.user)
        data = kwargs.get('data')
        if data is not None and profile and not profile.is_super_admin:
            data = data.copy() if hasattr(data, 'copy') else dict(data)
            data['club'] = profile.club_id
            if profile.is_branch_manager:
                data['center'] = profile.center_id
            kwargs['data'] = data
        return super().get_serializer(*args, **kwargs)

    def perform_create(self, serializer):
        # A president creates inside their own club; a branch manager inside
        # their own branch — whatever the request said.
        profile = profile_for(self.request.user)
        if profile and profile.is_branch_manager:
            serializer.save(club_id=profile.club_id, center_id=profile.center_id)
        elif profile and not profile.is_super_admin:
            serializer.save(club_id=profile.club_id)
        else:
            serializer.save()

    def perform_update(self, serializer):
        profile = profile_for(self.request.user)
        if profile and profile.is_branch_manager:
            # A branch manager cannot move a group out of their branch.
            serializer.save(club_id=profile.club_id, center_id=profile.center_id)
        else:
            serializer.save()

    @action(detail=True, methods=['post'], url_path='sessions')
    def add_session(self, request, pk=None):
        group = self.get_object()
        serializer = WeeklySessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(group=group)
        return Response(TrainingGroupSerializer(group).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='members')
    def set_members(self, request, pk=None):
        """Replaces the group's roster with the given registration ids."""
        group = self.get_object()
        ids = request.data.get('ids')
        if not isinstance(ids, list):
            return Response({'ids': 'A list of registration ids is required.'}, status=400)

        visible = scope_queryset_to_club(
            Registration.objects.all(), request.user, center_field='center')
        allowed = visible.filter(pk__in=ids, club_id=group.club_id)
        if allowed.count() != len(set(ids)):
            return Response(
                {'ids': 'Every member must be registered with this club.'}, status=400,
            )
        group.members.set(allowed)
        return Response(TrainingGroupSerializer(group).data)


class WeeklySessionViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = WeeklySessionSerializer
    pagination_class = None

    def get_queryset(self):
        qs = WeeklySession.objects.select_related('group__club')
        if group := self.request.query_params.get('group'):
            qs = qs.filter(group_id=group)
        return scope_queryset_to_club(
            qs, self.request.user, field='group__club', center_field='group__center')


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def weekly_timetable(request):
    """The whole week for the caller's scope, grouped by day — what the club
    owner sees on the Sessions screen."""
    sessions = scope_queryset_to_club(
        WeeklySession.objects.select_related('group', 'group__center', 'group__club'),
        request.user,
        field='group__club',
        center_field='group__center',
    ).filter(group__active=True)

    days = []
    for value, label in WeeklySession.WEEKDAY_CHOICES:
        rows = [
            {
                'id': s.id,
                'group': s.group_id,
                'group_name_en': s.group.name_en,
                'group_name_ar': s.group.name_ar,
                'center_name': s.group.center.name_en if s.group.center else '',
                'coach': s.group.coach,
                'start_time': s.start_time.strftime('%H:%M'),
                'end_time': s.end_time.strftime('%H:%M'),
                'member_count': s.group.member_count,
                'note': s.note,
            }
            for s in sessions if s.weekday == value
        ]
        days.append({'weekday': value, 'label': label, 'sessions': rows})
    return Response(days)


class ActivityLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Who did what. Scoped like everything else: a branch manager reads their
    branch's history, a president the whole club's, the national admin all."""

    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        from .serializers import ActivityLogSerializer
        return ActivityLogSerializer

    def get_queryset(self):
        qs = ActivityLog.objects.select_related('club', 'center')
        if action_ := self.request.query_params.get('action'):
            qs = qs.filter(action=action_)
        return scope_queryset_to_club(qs, self.request.user, center_field='center')
