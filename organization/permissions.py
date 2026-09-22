"""Who may see and change what.

Three levels — national administrator, club president, branch manager — and one
rule: you see your own level and everything beneath it, never above and never
sideways. Everything here enforces that rule on the *server*. Hiding a button
in the dashboard is a convenience; these checks are the guarantee.
"""

from rest_framework import permissions

from .models import profile_for


class IsSuperAdmin(permissions.BasePermission):
    """Only the national administrator: clubs, wilayas, platform settings."""

    message = 'Only the national administrator may do this.'

    def has_permission(self, request, view):
        profile = profile_for(request.user)
        return bool(profile and profile.is_super_admin)


class IsSuperAdminOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        profile = profile_for(request.user)
        return bool(profile and profile.is_super_admin)


class IsClubLevel(permissions.BasePermission):
    """The national administrator or a club president — not a branch manager.

    Guards the club-wide screens: competitions, community posts, the carousel,
    branch and account management. A branch manager's world is one branch's
    candidates, groups and stats; none of these belong to a single branch.
    """

    message = 'Branch managers do not have access to this.'

    def has_permission(self, request, view):
        profile = profile_for(request.user)
        return bool(profile and (profile.is_super_admin or profile.is_club_owner))


def scope_queryset_to_club(queryset, user, field='club', center_field=None):
    """Limits a queryset to what this account is allowed to see.

    * national administrator  -> everything
    * club president          -> rows of their club (`field`)
    * branch manager          -> rows of their club AND their branch
                                 (`center_field`)

    Fails closed at every step. A president with no club sees nothing, not
    everything. And a branch manager sees nothing unless the caller says where
    the branch lives on this model (`center_field`): data that has no branch
    dimension is not theirs to read, and a call site that forgets to pass the
    field must leak *nothing* rather than the whole club.
    """
    profile = profile_for(user)
    if profile is None:
        return queryset.none()
    if profile.is_super_admin:
        return queryset
    if profile.club_id is None:
        return queryset.none()

    scoped = queryset.filter(**{field: profile.club_id})
    if profile.is_branch_manager:
        if not center_field or profile.center_id is None:
            return queryset.none()
        scoped = scoped.filter(**{center_field: profile.center_id})
    return scoped


def can_manage_club(user, club_id) -> bool:
    """May this account change something that belongs to `club_id`?

    The national administrator may change anything; a president only their own
    club; a branch manager nothing at club level. `club_id=None` means a
    national record (a national championship, a platform-wide post) — only the
    national administrator touches those.
    """
    profile = profile_for(user)
    if profile is None:
        return False
    if profile.is_super_admin:
        return True
    if profile.is_club_owner:
        return club_id is not None and club_id == profile.club_id
    return False
