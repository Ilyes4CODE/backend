from rest_framework import serializers

from .models import Competition, JudgeScore, Match, Participant, Performance, ScoringEvent


class ParticipantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Participant
        fields = ['id', 'competition', 'registration', 'name', 'club', 'seed', 'withdrawn']
        read_only_fields = ['competition']


class ParticipantBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Participant
        fields = ['id', 'name', 'club', 'seed']


class ScoringEventSerializer(serializers.ModelSerializer):
    judge_username = serializers.CharField(source='judge.username', read_only=True)

    class Meta:
        model = ScoringEvent
        fields = [
            'id', 'match', 'participant', 'kind', 'points', 'technique',
            'round_number', 'judge_username', 'created_at',
        ]
        read_only_fields = ['match']


class MatchSerializer(serializers.ModelSerializer):
    participant_a = ParticipantBriefSerializer(read_only=True)
    participant_b = ParticipantBriefSerializer(read_only=True)
    winner = ParticipantBriefSerializer(read_only=True)
    score_a = serializers.IntegerField(read_only=True)
    score_b = serializers.IntegerField(read_only=True)

    class Meta:
        model = Match
        fields = [
            'id', 'round_number', 'position', 'participant_a', 'participant_b',
            'winner', 'status', 'current_round', 'score_a', 'score_b',
            'next_match', 'next_slot', 'started_at', 'finished_at',
        ]


class MatchDetailSerializer(MatchSerializer):
    scoring_events = ScoringEventSerializer(many=True, read_only=True)
    competition_id = serializers.IntegerField(source='competition.id', read_only=True)
    competition_name = serializers.CharField(source='competition.name', read_only=True)
    rounds_per_match = serializers.IntegerField(source='competition.rounds_per_match', read_only=True)

    class Meta(MatchSerializer.Meta):
        fields = MatchSerializer.Meta.fields + [
            'scoring_events', 'competition_id', 'competition_name', 'rounds_per_match',
        ]


class JudgeScoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = JudgeScore
        fields = ['id', 'performance', 'judge_name', 'score', 'notes', 'updated_at']
        read_only_fields = ['performance']


class PerformanceSerializer(serializers.ModelSerializer):
    participant = ParticipantBriefSerializer(read_only=True)
    participant_id = serializers.PrimaryKeyRelatedField(
        source='participant', queryset=Participant.objects.all(), write_only=True
    )
    judge_scores = JudgeScoreSerializer(many=True, read_only=True)

    class Meta:
        model = Performance
        fields = [
            'id', 'competition', 'participant', 'participant_id', 'order', 'form_name',
            'status', 'final_score', 'penalty', 'notes', 'judge_scores',
        ]
        read_only_fields = ['competition', 'final_score']


class CompetitionSerializer(serializers.ModelSerializer):
    participant_count = serializers.IntegerField(source='participants.count', read_only=True)
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    weight_class_display = serializers.CharField(source='get_weight_class_display', read_only=True)
    technique_event_display = serializers.CharField(source='get_technique_event_display', read_only=True)

    club_name = serializers.CharField(source='club.name_en', read_only=True, default='')

    class Meta:
        model = Competition
        fields = [
            'id', 'name', 'type', 'type_display', 'season', 'gender', 'status', 'club', 'club_name',
            'weight_class', 'weight_class_display', 'rounds_per_match',
            'technique_event', 'technique_event_display', 'prescribed_form',
            'judge_count', 'scoring_mode', 'max_score',
            'participant_count', 'created_at',
        ]


class CompetitionDetailSerializer(CompetitionSerializer):
    participants = ParticipantSerializer(many=True, read_only=True)
    matches = MatchSerializer(many=True, read_only=True)
    performances = PerformanceSerializer(many=True, read_only=True)

    class Meta(CompetitionSerializer.Meta):
        fields = CompetitionSerializer.Meta.fields + ['participants', 'matches', 'performances']
