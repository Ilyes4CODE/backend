from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from organization.models import profile_for
from organization.permissions import IsClubLevel, can_manage_club

from .bracket import advance_winner, generate_bracket, standings
from .certificates import _award_for, generate_all_certificates, generate_certificate
from .models import Competition, JudgeScore, Match, Participant, Performance, ScoringEvent
from .reference import (
    FEMALE_WEIGHT_CLASSES,
    MALE_WEIGHT_CLASSES,
    PRESCRIBED_QUYEN_FEMALE,
    PRESCRIBED_QUYEN_MALE,
    REQUIRED_PRE_BOUT_TECHNIQUES,
    TECHNIQUE_EVENTS,
)
from .serializers import (
    CompetitionDetailSerializer,
    CompetitionSerializer,
    JudgeScoreSerializer,
    MatchDetailSerializer,
    MatchSerializer,
    ParticipantSerializer,
    PerformanceSerializer,
    ScoringEventSerializer,
)


def _standings_rows(competition) -> list[dict]:
    """Final placings for either competition type, in one shape."""
    if competition.is_combat:
        return [
            {
                'place': row['place'],
                'medal': row['medal'],
                'score': None,
                'participant': {
                    'id': row['participant'].id,
                    'name': row['participant'].name,
                    'club': row['participant'].club,
                },
            }
            for row in standings(competition)
        ]

    scored = [p for p in competition.performances.all() if p.final_score is not None]
    scored.sort(key=lambda p: p.final_score, reverse=True)
    medals = ['GOLD', 'SILVER', 'BRONZE']
    return [
        {
            'place': index + 1,
            'medal': medals[index] if index < len(medals) else None,
            'score': str(performance.final_score),
            'participant': {
                'id': performance.participant.id,
                'name': performance.participant.name,
                'club': performance.participant.club,
            },
        }
        for index, performance in enumerate(scored)
    ]


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def reference_data(request):
    """The catalogue from the championship regulations, for the admin forms."""
    return Response({
        'male_weight_classes': [{'value': v, 'label': l} for v, l in MALE_WEIGHT_CLASSES],
        'female_weight_classes': [{'value': v, 'label': l} for v, l in FEMALE_WEIGHT_CLASSES],
        'technique_events': [{'value': v, 'label': l} for v, l in TECHNIQUE_EVENTS],
        'prescribed_quyen_male': PRESCRIBED_QUYEN_MALE,
        'prescribed_quyen_female': PRESCRIBED_QUYEN_FEMALE,
        'required_pre_bout_techniques': REQUIRED_PRE_BOUT_TECHNIQUES,
    })


def visible_competitions(user):
    """Competitions this account may read: all of them for the national admin;
    their own club's plus the national championships for a president."""
    qs = Competition.objects.all()
    profile = profile_for(user)
    if profile and profile.is_super_admin:
        return qs
    if profile and profile.club_id:
        return qs.filter(Q(club_id=profile.club_id) | Q(club__isnull=True))
    return qs.none()


def competition_of(obj):
    """Walk any competition sub-object back to the competition that owns it."""
    if isinstance(obj, Competition):
        return obj
    if hasattr(obj, 'competition'):
        return obj.competition
    if hasattr(obj, 'performance'):
        return obj.performance.competition
    return None


class CompetitionAccess(IsClubLevel):
    """Read what you can see; change only what you own.

    A national championship (club=None) is the national admin's alone. A club
    event is its president's. Applies to the competition and to every bout,
    competitor, performance and judge's mark inside it — including the POST
    actions (scoring, declaring a winner), since those go through get_object().
    """

    message = 'This competition belongs to someone else.'

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        competition = competition_of(obj)
        return competition is not None and can_manage_club(request.user, competition.club_id)


def _require_owner(user, competition):
    if competition is None or not can_manage_club(user, competition.club_id):
        raise PermissionDenied('This competition belongs to someone else.')


class CompetitionViewSet(viewsets.ModelViewSet):
    permission_classes = [CompetitionAccess]
    queryset = Competition.objects.all()
    pagination_class = None

    def get_serializer_class(self):
        return CompetitionDetailSerializer if self.action == 'retrieve' else CompetitionSerializer

    def get_queryset(self):
        # Presidents see their club's events plus the national championships.
        qs = visible_competitions(self.request.user)
        if type_ := self.request.query_params.get('type'):
            qs = qs.filter(type=type_)
        if status_ := self.request.query_params.get('status'):
            qs = qs.filter(status=status_)
        return qs

    def perform_create(self, serializer):
        # A club owner's events belong to their club by default.
        profile = profile_for(self.request.user)
        if profile and not profile.is_super_admin and profile.club_id:
            serializer.save(club_id=profile.club_id)
        else:
            serializer.save()

    @action(detail=True, methods=['get'], url_path='certificates')
    def all_certificates(self, request, pk=None):
        """Every competitor's certificate in one PDF, ready for the printer."""
        competition = self.get_object()
        buffer = generate_all_certificates(competition)
        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="certificates-{competition.id}.pdf"'
        return response

    @action(detail=True, methods=['get'], url_path=r'certificates/(?P<participant_id>\d+)')
    def certificate(self, request, pk=None, participant_id=None):
        """One competitor's certificate — diploma if they placed, otherwise participation."""
        competition = self.get_object()
        participant = get_object_or_404(competition.participants, pk=participant_id)
        buffer = generate_certificate(competition, participant)
        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="certificate-{participant.id}.pdf"'
        return response

    @action(detail=True, methods=['get'], url_path='awards')
    def awards(self, request, pk=None):
        """What each competitor will receive — drives the certificates tab."""
        competition = self.get_object()
        rows = []
        for participant in competition.participants.filter(withdrawn=False):
            award, place = _award_for(competition, participant)
            rows.append({
                'participant': {'id': participant.id, 'name': participant.name, 'club': participant.club},
                'award': award,
                'place': place,
            })
        order = {'GOLD': 0, 'SILVER': 1, 'BRONZE': 2, 'PARTICIPATION': 3}
        rows.sort(key=lambda r: (order[r['award']], r['participant']['name']))
        return Response(rows)

    @action(detail=True, methods=['post'])
    def participants(self, request, pk=None):
        """Add one competitor, or a batch of names pasted in at once."""
        competition = self.get_object()
        names = request.data.get('names')
        if isinstance(names, list):
            created = [
                Participant.objects.create(competition=competition, name=str(n).strip())
                for n in names if str(n).strip()
            ]
            return Response(ParticipantSerializer(created, many=True).data, status=status.HTTP_201_CREATED)

        serializer = ParticipantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(competition=competition)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='generate-bracket')
    def generate_bracket_action(self, request, pk=None):
        competition = self.get_object()
        if not competition.is_combat:
            return Response({'detail': 'Only combat competitions have a bracket.'}, status=400)
        try:
            generate_bracket(competition)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)
        competition.status = 'READY'
        competition.save(update_fields=['status'])
        return Response(CompetitionDetailSerializer(competition).data)

    @action(detail=True, methods=['post'], url_path='generate-running-order')
    def generate_running_order(self, request, pk=None):
        """Creates a Performance row per competitor, in entry order."""
        competition = self.get_object()
        if competition.is_combat:
            return Response({'detail': 'Only technique competitions have a running order.'}, status=400)
        with transaction.atomic():
            competition.performances.all().delete()
            for index, participant in enumerate(competition.participants.filter(withdrawn=False), start=1):
                Performance.objects.create(
                    competition=competition,
                    participant=participant,
                    order=index,
                    form_name=competition.prescribed_form,
                )
            competition.status = 'READY'
            competition.save(update_fields=['status'])
        return Response(CompetitionDetailSerializer(competition).data)

    @action(detail=True, methods=['get'])
    def standings(self, request, pk=None):
        return Response(_standings_rows(self.get_object()))


class ParticipantViewSet(viewsets.ModelViewSet):
    permission_classes = [CompetitionAccess]
    serializer_class = ParticipantSerializer
    pagination_class = None

    def get_queryset(self):
        return Participant.objects.filter(
            competition__in=visible_competitions(self.request.user))

    def perform_create(self, serializer):
        _require_owner(self.request.user, serializer.validated_data.get('competition'))
        serializer.save()


class MatchViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [CompetitionAccess]
    pagination_class = None

    def get_queryset(self):
        return Match.objects.filter(
            competition__in=visible_competitions(self.request.user))

    def get_serializer_class(self):
        return MatchDetailSerializer if self.action == 'retrieve' else MatchSerializer

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        match = self.get_object()
        if match.status == Match.COMPLETED:
            return Response({'detail': 'This bout is already finished.'}, status=400)
        if not (match.participant_a and match.participant_b):
            return Response({'detail': 'Both competitors must be known before the bout starts.'}, status=400)
        match.status = Match.LIVE
        match.started_at = match.started_at or timezone.now()
        match.save(update_fields=['status', 'started_at'])
        match.competition.status = 'IN_PROGRESS'
        match.competition.save(update_fields=['status'])
        return Response(MatchDetailSerializer(match).data)

    @action(detail=True, methods=['post'], url_path='score')
    def add_score(self, request, pk=None):
        """Judges award points live during the bout."""
        match = self.get_object()
        if match.status not in (Match.LIVE, Match.PENDING):
            return Response({'detail': 'Scoring is closed for this bout.'}, status=400)

        participant_id = request.data.get('participant')
        if participant_id not in (
            getattr(match.participant_a, 'id', None), getattr(match.participant_b, 'id', None)
        ):
            return Response({'detail': 'That competitor is not in this bout.'}, status=400)

        event = ScoringEvent.objects.create(
            match=match,
            participant_id=participant_id,
            kind=request.data.get('kind', ScoringEvent.POINT),
            points=int(request.data.get('points', 1)),
            technique=request.data.get('technique', ''),
            round_number=int(request.data.get('round_number', match.current_round)),
            judge=request.user if request.user.is_authenticated else None,
        )
        return Response(
            {'event': ScoringEventSerializer(event).data, 'match': MatchDetailSerializer(match).data},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'], url_path='undo-score')
    def undo_score(self, request, pk=None):
        """Removes the most recent scoring entry — mis-clicks happen mid-bout."""
        match = self.get_object()
        last = match.scoring_events.order_by('-created_at', '-id').first()
        if not last:
            return Response({'detail': 'Nothing to undo.'}, status=400)
        last.delete()
        return Response(MatchDetailSerializer(match).data)

    @action(detail=True, methods=['post'], url_path='set-round')
    def set_round(self, request, pk=None):
        match = self.get_object()
        match.current_round = max(1, min(int(request.data.get('round', 1)), match.competition.rounds_per_match))
        match.save(update_fields=['current_round'])
        return Response(MatchDetailSerializer(match).data)

    @action(detail=True, methods=['post'], url_path='declare-winner')
    def declare_winner(self, request, pk=None):
        """Judges close the bout and name the winner, who moves up the bracket."""
        match = self.get_object()
        winner_id = request.data.get('winner')
        valid_ids = [getattr(match.participant_a, 'id', None), getattr(match.participant_b, 'id', None)]
        if winner_id not in valid_ids:
            return Response({'detail': 'The winner must be one of the two competitors.'}, status=400)

        with transaction.atomic():
            match.winner_id = winner_id
            match.status = Match.COMPLETED
            match.finished_at = timezone.now()
            match.save(update_fields=['winner', 'status', 'finished_at'])
            advance_winner(match)

            competition = match.competition
            if competition.matches.exclude(status__in=[Match.COMPLETED, Match.BYE]).count() == 0:
                competition.status = 'COMPLETED'
                competition.save(update_fields=['status'])

        return Response(MatchDetailSerializer(match).data)

    @action(detail=True, methods=['post'], url_path='reopen')
    def reopen(self, request, pk=None):
        """Undo a result — clears the winner here and wherever they were seated next."""
        match = self.get_object()
        with transaction.atomic():
            parent = match.next_match
            if parent and match.winner_id:
                if parent.participant_a_id == match.winner_id:
                    parent.participant_a = None
                elif parent.participant_b_id == match.winner_id:
                    parent.participant_b = None
                parent.save(update_fields=['participant_a', 'participant_b'])
            match.winner = None
            match.status = Match.LIVE
            match.finished_at = None
            match.save(update_fields=['winner', 'status', 'finished_at'])
            competition = match.competition
            if competition.status == 'COMPLETED':
                competition.status = 'IN_PROGRESS'
                competition.save(update_fields=['status'])
        return Response(MatchDetailSerializer(match).data)


class PerformanceViewSet(viewsets.ModelViewSet):
    permission_classes = [CompetitionAccess]
    serializer_class = PerformanceSerializer
    pagination_class = None

    def get_queryset(self):
        return Performance.objects.filter(
            competition__in=visible_competitions(self.request.user))

    def perform_create(self, serializer):
        _require_owner(self.request.user, serializer.validated_data.get('competition'))
        serializer.save()

    @action(detail=True, methods=['post'], url_path='score')
    def set_judge_score(self, request, pk=None):
        """Records (or updates) one judge's mark and recomputes the final score."""
        performance = self.get_object()
        judge_name = str(request.data.get('judge_name', '')).strip()
        if not judge_name:
            return Response({'judge_name': 'Required.'}, status=400)
        try:
            score = float(request.data.get('score'))
        except (TypeError, ValueError):
            return Response({'score': 'A number is required.'}, status=400)
        if not 0 <= score <= float(performance.competition.max_score):
            return Response({'score': f'Must be between 0 and {performance.competition.max_score}.'}, status=400)

        JudgeScore.objects.update_or_create(
            performance=performance,
            judge_name=judge_name,
            defaults={
                'score': score,
                'notes': request.data.get('notes', ''),
                'judge_user': request.user if request.user.is_authenticated else None,
            },
        )
        performance.refresh_final_score()
        return Response(PerformanceSerializer(performance).data)

    @action(detail=True, methods=['post'])
    def finalize(self, request, pk=None):
        performance = self.get_object()
        performance.penalty = request.data.get('penalty', performance.penalty)
        performance.status = Performance.COMPLETED
        performance.save(update_fields=['penalty', 'status'])
        performance.refresh_final_score()
        competition = performance.competition
        if competition.performances.exclude(status=Performance.COMPLETED).count() == 0:
            competition.status = 'COMPLETED'
        else:
            competition.status = 'IN_PROGRESS'
        competition.save(update_fields=['status'])
        return Response(PerformanceSerializer(performance).data)


class JudgeScoreViewSet(viewsets.ModelViewSet):
    permission_classes = [CompetitionAccess]
    serializer_class = JudgeScoreSerializer
    pagination_class = None

    def get_queryset(self):
        return JudgeScore.objects.filter(
            performance__competition__in=visible_competitions(self.request.user))

    def perform_create(self, serializer):
        performance = serializer.validated_data.get('performance')
        _require_owner(self.request.user, performance.competition if performance else None)
        serializer.save()


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def display_state(request, pk):
    """Read-only snapshot for the hall projector — polled by the display screen.

    Public on purpose: the projector machine should not need to hold a login,
    and this exposes only what is already on show in the room.
    """
    competition = get_object_or_404(Competition, pk=pk)
    payload = {
        'competition': CompetitionSerializer(competition).data,
        'standings': None,
        'live_match': None,
        'live_performance': None,
        'matches': None,
        'performances': None,
    }

    if competition.is_combat:
        live = competition.matches.filter(status=Match.LIVE).order_by('round_number', 'position').first()
        payload['live_match'] = MatchDetailSerializer(live).data if live else None
        payload['matches'] = MatchSerializer(competition.matches.all(), many=True).data
    else:
        live = competition.performances.filter(status=Performance.LIVE).order_by('order').first()
        payload['live_performance'] = PerformanceSerializer(live).data if live else None
        payload['performances'] = PerformanceSerializer(competition.performances.all(), many=True).data

    # Always computed: the operator can pin the results screen at any point, and
    # it is simply empty until there is something to show.
    payload['standings'] = _standings_rows(competition)

    return Response(payload)
