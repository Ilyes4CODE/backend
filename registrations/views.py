from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView

from organization.models import profile_for
from organization.permissions import IsSuperAdminOrReadOnly, scope_queryset_to_club

from .categorization import categorize
from .models import RequiredDocument, Registration, SiteSettings, UploadedDocument
from .serializers import (
    RegistrationAdminUpdateSerializer,
    RegistrationCreateSerializer,
    RegistrationDetailSerializer,
    RegistrationListSerializer,
    RequiredDocumentAdminSerializer,
    RequiredDocumentPublicSerializer,
    SiteSettingsSerializer,
)


def _clean_multipart(data):
    """Drop empty-string values so optional model fields (dates, etc.) validate cleanly."""
    return {k: v for k, v in data.items() if v != ''}


def _applies_to_filter(is_minor: bool) -> Q:
    return Q(applies_to='ALL') | Q(applies_to='MINOR' if is_minor else 'MAJOR')


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def public_settings(request):
    return Response(SiteSettingsSerializer(SiteSettings.load()).data)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def public_required_documents(request):
    is_minor = request.query_params.get('is_minor') == 'true'
    docs = RequiredDocument.objects.filter(active=True).filter(_applies_to_filter(is_minor))
    return Response(RequiredDocumentPublicSerializer(docs, many=True).data)


class RegistrationCreateView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        if not SiteSettings.load().registrations_open:
            return Response(
                {'detail': 'Registrations are currently closed.', 'code': 'REGISTRATIONS_CLOSED'},
                status=status.HTTP_403_FORBIDDEN,
            )

        payload = _clean_multipart(request.data)
        serializer = RegistrationCreateSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        category, is_minor, age = categorize(data['birth_date'])

        errors = {}
        if is_minor:
            for field in ('parent_name', 'parent_id_type', 'parent_id_number', 'parent_id_issue_date'):
                if not data.get(field):
                    errors[field] = 'This field is required for candidates under 18.'

        required_docs = RequiredDocument.objects.filter(
            active=True, required=True
        ).filter(_applies_to_filter(is_minor))
        missing = [doc.key for doc in required_docs if f'doc_{doc.key}' not in request.FILES]
        if missing:
            errors['documents'] = f'Missing required documents: {", ".join(missing)}'

        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            registration = Registration.objects.create(
                category=category,
                is_minor=is_minor,
                age_at_registration=age,
                season=SiteSettings.load().active_season,
                **data,
            )
            applicable_docs = RequiredDocument.objects.filter(active=True).filter(_applies_to_filter(is_minor))
            for doc in applicable_docs:
                uploaded = request.FILES.get(f'doc_{doc.key}')
                if uploaded:
                    UploadedDocument.objects.create(
                        registration=registration,
                        required_document=doc,
                        file=uploaded,
                        original_name=uploaded.name,
                    )

        return Response(RegistrationDetailSerializer(registration).data, status=status.HTTP_201_CREATED)


class RegistrationPublicDetailView(generics.RetrieveAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = RegistrationDetailSerializer
    lookup_field = 'reference'
    queryset = Registration.objects.all()


class RequiredDocumentAdminViewSet(viewsets.ModelViewSet):
    # The required-document list applies platform-wide, so only the admin edits it.
    permission_classes = [IsSuperAdminOrReadOnly]
    serializer_class = RequiredDocumentAdminSerializer
    queryset = RequiredDocument.objects.all()
    pagination_class = None


class RegistrationAdminViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = Registration.objects.all()

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return RegistrationDetailSerializer
        return RegistrationListSerializer

    def get_queryset(self):
        # A president sees their club's candidates; a branch manager only their
        # branch's. Anything else is a 404, not a 403: we do not confirm that a
        # candidate exists somewhere they cannot see.
        qs = scope_queryset_to_club(
            super().get_queryset(), self.request.user, center_field='center')
        params = self.request.query_params
        if club := params.get('club'):
            qs = qs.filter(club_id=club)
        if center := params.get('center'):
            qs = qs.filter(center_id=center)
        if gender := params.get('gender'):
            qs = qs.filter(gender=gender)
        if category := params.get('category'):
            qs = qs.filter(category=category)
        if is_minor := params.get('is_minor'):
            qs = qs.filter(is_minor=is_minor == 'true')
        if status_ := params.get('status'):
            qs = qs.filter(status=status_)
        if payment_status := params.get('payment_status'):
            qs = qs.filter(payment_status=payment_status)
        if season := params.get('season'):
            qs = qs.filter(season=season)
        if group := params.get('group'):
            qs = qs.filter(training_groups__id=group)
        if search := params.get('search'):
            qs = qs.filter(
                Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(latin_full_name__icontains=search)
                | Q(reference__icontains=search)
                | Q(phone__icontains=search)
            )
        return qs

    def partial_update(self, request, *args, **kwargs):
        from organization.activity import ActivityLog, record

        instance = self.get_object()
        before = {
            'status': instance.status,
            'payment_status': instance.payment_status,
            'center': instance.center,
        }
        serializer = RegistrationAdminUpdateSerializer(
            instance, data=request.data, partial=True, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # One log line per thing that actually changed.
        if instance.status != before['status']:
            record(request.user, ActivityLog.REGISTRATION_STATUS, instance.reference,
                   club=instance.club, center=instance.center,
                   **{'from': before['status'], 'to': instance.status})
        if instance.payment_status != before['payment_status']:
            record(request.user, ActivityLog.REGISTRATION_PAYMENT, instance.reference,
                   club=instance.club, center=instance.center,
                   **{'from': before['payment_status'], 'to': instance.payment_status})
        if instance.center != before['center']:
            record(request.user, ActivityLog.REGISTRATION_TRANSFER, instance.reference,
                   club=instance.club, center=instance.center,
                   **{'from': before['center'].name_en if before['center'] else None,
                      'to': instance.center.name_en if instance.center else None})
        return Response(RegistrationDetailSerializer(instance).data)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def admin_stats(request):
    from django.db.models import Count

    from organization.models import profile_for

    qs = scope_queryset_to_club(Registration.objects.all(), request.user, center_field='center')
    by_category = {c: qs.filter(category=c).count() for c, _ in Registration._meta.get_field('category').choices}

    # Per-center numbers, so a club owner can see how Khafji is doing next to
    # Lassilis. A super admin gets the breakdown per club instead.
    profile = profile_for(request.user)
    if profile and profile.is_super_admin:
        grouping, label_field = 'club', 'club__name_en'
    else:
        grouping, label_field = 'center', 'center__name_en'

    rows = (
        qs.values(grouping, label_field)
        .annotate(
            total=Count('id'),
            paid=Count('id', filter=Q(payment_status='PAID')),
        )
        .order_by('-total')
    )
    breakdown = [
        {
            'id': row[grouping],
            'name': row[label_field] or '—',
            'total': row['total'],
            'paid': row['paid'],
        }
        for row in rows
    ]

    return Response({
        'total': qs.count(),
        'minors': qs.filter(is_minor=True).count(),
        'majors': qs.filter(is_minor=False).count(),
        'pending': qs.filter(status='PENDING').count(),
        'approved': qs.filter(status='APPROVED').count(),
        'rejected': qs.filter(status='REJECTED').count(),
        'paid': qs.filter(payment_status='PAID').count(),
        'unpaid': qs.filter(payment_status='UNPAID').count(),
        'by_category': by_category,
        'breakdown_by': 'club' if (profile and profile.is_super_admin) else 'center',
        'breakdown': breakdown,
    })


class AdminSettingsView(generics.RetrieveUpdateAPIView):
    # Site-wide settings (season, registration window) belong to the platform admin.
    permission_classes = [IsSuperAdminOrReadOnly]
    serializer_class = SiteSettingsSerializer

    def get_object(self):
        return SiteSettings.load()


class DocumentDownloadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        # Scoped first, so a club owner cannot fetch another club's documents by id.
        visible = scope_queryset_to_club(
            UploadedDocument.objects.all(), request.user,
            field='registration__club', center_field='registration__center',
        )
        doc = get_object_or_404(visible, pk=pk)
        if not doc.file:
            raise Http404
        # ?inline=1 lets the admin preview the file in the browser instead of
        # downloading it; anything else keeps the save-to-disk behaviour.
        as_attachment = request.query_params.get('inline') != '1'
        return FileResponse(doc.file.open('rb'), as_attachment=as_attachment, filename=doc.original_name)


class RosterPrintView(APIView):
    """The candidate list as a printable PDF, honouring the dashboard's filters.

    Reuses the list view's own filtering so the printout always matches what the
    admin is looking at on screen.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from django.http import HttpResponse

        from organization.models import Club

        from .rosters import generate_roster

        view = RegistrationAdminViewSet()
        view.request = request
        view.kwargs = {}
        rows = list(view.get_queryset().select_related('club', 'center'))

        title = 'Candidates'
        if club_id := request.query_params.get('club'):
            club = Club.objects.filter(pk=club_id).first()
            if club:
                title = club.name_en
        else:
            profile = profile_for(request.user)
            if profile and profile.is_branch_manager and profile.center:
                title = f'{profile.club.name_en} — {profile.center.name_en}'
            elif profile and profile.club:
                title = profile.club.name_en

        # Portrait by default; landscape is there for anyone who needs the
        # phone column too.
        orientation = request.query_params.get('orientation', 'portrait')
        buffer = generate_roster(rows, title=title, orientation=orientation)
        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="candidates.pdf"'
        return response


class BadgeView(APIView):
    """A member badge, issued only once the membership has been paid."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        from django.http import HttpResponse

        from .badges import generate_badge

        visible = scope_queryset_to_club(
            Registration.objects.all(), request.user, center_field='center')
        registration = get_object_or_404(visible, pk=pk)
        if registration.payment_status != 'PAID':
            return Response(
                {'detail': 'A badge is issued once the membership is paid.', 'code': 'NOT_PAID'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        buffer = generate_badge(registration)
        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="badge-{registration.reference}.pdf"'
        return response


class BadgeSheetView(APIView):
    """Badges on printable sheets — 8 per page, fronts then backs.

    GET  prints every paid member the caller can see.
    POST prints just the ones selected in the dashboard (`ids`).
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        paid = self._paid_queryset(request)
        if club := request.query_params.get('club'):
            paid = paid.filter(club_id=club)
        return self._render(list(paid), self._mirror(request))

    def post(self, request):
        ids = request.data.get('ids') or []
        if not isinstance(ids, list) or not ids:
            return Response({'detail': 'Select at least one member.', 'code': 'NO_SELECTION'}, status=400)

        selected = self._paid_queryset(request).filter(pk__in=ids)
        # Keep the dashboard's order so the printed stack matches the screen.
        by_id = {registration.pk: registration for registration in selected}
        ordered = [by_id[int(pk)] for pk in ids if int(pk) in by_id]
        return self._render(ordered, self._mirror(request))

    @staticmethod
    def _mirror(request) -> bool:
        """`?duplex=1` mirrors the backs for an automatic double-sided printer.
        Off by default: the backs line up with the fronts."""
        raw = request.query_params.get('duplex') or (
            request.data.get('duplex') if hasattr(request, 'data') and isinstance(request.data, dict) else None
        )
        return str(raw).lower() in {'1', 'true', 'yes'}

    def _paid_queryset(self, request):
        return (
            scope_queryset_to_club(
                Registration.objects.filter(payment_status='PAID'), request.user,
                center_field='center')
            .select_related('club', 'center')
            .prefetch_related('documents__required_document')
        )

    def _render(self, registrations, mirror_backs=False):
        from django.http import HttpResponse

        from .badges import generate_badge_sheet

        if not registrations:
            return Response(
                {'detail': 'None of the selected members have paid yet.', 'code': 'NO_PAID_MEMBERS'},
                status=400,
            )
        buffer = generate_badge_sheet(registrations, mirror_backs=mirror_backs)
        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="badges.pdf"'
        return response


class RegistrationPdfView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, reference):
        from django.http import HttpResponse

        from .pdf import generate_registration_pdf

        registration = get_object_or_404(Registration, reference=reference)
        buffer = generate_registration_pdf(registration)
        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{registration.reference}.pdf"'
        return response
