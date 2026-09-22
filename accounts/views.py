from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def me(request):
    """Identity plus what this account is allowed to see — drives the dashboard nav."""
    from organization.models import UserProfile, profile_for

    profile = profile_for(request.user)
    return Response({
        'username': request.user.username,
        'email': request.user.email,
        'role': profile.role if profile else UserProfile.CLUB_OWNER,
        'is_super_admin': bool(profile and profile.is_super_admin),
        'is_club_owner': bool(profile and profile.is_club_owner),
        'is_branch_manager': bool(profile and profile.is_branch_manager),
        'club': profile.club_id if profile else None,
        'club_name': profile.club.name_en if profile and profile.club else None,
        'club_name_ar': profile.club.name_ar if profile and profile.club else None,
        'center': profile.center_id if profile else None,
        'center_name': profile.center.name_en if profile and profile.center else None,
        'center_name_ar': profile.center.name_ar if profile and profile.center else None,
        'full_name': profile.full_name if profile else '',
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def change_password(request):
    current_password = request.data.get('current_password', '')
    new_password = request.data.get('new_password', '')

    if not request.user.check_password(current_password):
        return Response({'current_password': 'Incorrect password.'}, status=status.HTTP_400_BAD_REQUEST)
    if len(new_password) < 8:
        return Response({'new_password': 'Password must be at least 8 characters.'}, status=status.HTTP_400_BAD_REQUEST)

    request.user.set_password(new_password)
    request.user.save()
    return Response({'detail': 'Password updated.'})
