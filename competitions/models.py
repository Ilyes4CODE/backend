from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import models

from registrations.models import Registration

from .reference import TECHNIQUE_EVENTS, WEIGHT_CLASSES


class Competition(models.Model):
    """One event within a championship: a single weight class of منازلات, or a
    single judged تقني event. Combat runs as a knockout bracket; technique runs
    as a scored running order."""

    COMBAT = 'COMBAT'
    TECHNIQUE = 'TECHNIQUE'
    TYPE_CHOICES = [
        (COMBAT, 'منازلة - Combat'),
        (TECHNIQUE, 'تقني - Technique'),
    ]

    GENDER_CHOICES = [('MALE', 'Male'), ('FEMALE', 'Female'), ('MIXED', 'Mixed')]

    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),            # entering participants
        ('READY', 'Ready'),            # bracket / running order generated
        ('IN_PROGRESS', 'In progress'),
        ('COMPLETED', 'Completed'),
    ]

    SCORING_TRIMMED = 'TRIMMED'
    SCORING_AVERAGE = 'AVERAGE'
    SCORING_CHOICES = [
        (SCORING_TRIMMED, 'Drop highest and lowest, average the rest'),
        (SCORING_AVERAGE, 'Average of all judges'),
    ]

    name = models.CharField(max_length=200)
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    season = models.CharField(max_length=20, blank=True)
    # Which club is running this event. Null means a platform-wide championship.
    club = models.ForeignKey(
        'organization.Club', null=True, blank=True,
        on_delete=models.CASCADE, related_name='competitions',
    )
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, default='MALE')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='DRAFT')

    # Combat only — the weight class from section V.1 of the regulations.
    weight_class = models.CharField(max_length=20, choices=WEIGHT_CLASSES, blank=True)
    rounds_per_match = models.PositiveSmallIntegerField(default=3)

    # Technique only — the judged event from sections V.2-V.6.
    technique_event = models.CharField(max_length=30, choices=TECHNIQUE_EVENTS, blank=True)
    prescribed_form = models.CharField(max_length=100, blank=True)
    judge_count = models.PositiveSmallIntegerField(default=3)
    scoring_mode = models.CharField(max_length=10, choices=SCORING_CHOICES, default=SCORING_TRIMMED)
    max_score = models.DecimalField(max_digits=4, decimal_places=2, default=10)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.get_type_display()})'

    @property
    def is_combat(self) -> bool:
        return self.type == self.COMBAT


class Participant(models.Model):
    """A competitor entered into one competition. Either linked to a club
    registration or typed in by hand — the admin enters names directly."""

    competition = models.ForeignKey(Competition, related_name='participants', on_delete=models.CASCADE)
    registration = models.ForeignKey(
        Registration, null=True, blank=True, on_delete=models.SET_NULL, related_name='competition_entries'
    )
    name = models.CharField(max_length=200)
    club = models.CharField(max_length=200, blank=True)
    seed = models.PositiveSmallIntegerField(default=0, help_text='1 = top seed; 0 = unseeded')
    withdrawn = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['seed', 'id']

    def __str__(self):
        return self.name


class Match(models.Model):
    """One bout in the knockout bracket. round_number 1 is the first round;
    the highest round number is the final."""

    PENDING = 'PENDING'
    LIVE = 'LIVE'
    COMPLETED = 'COMPLETED'
    BYE = 'BYE'
    STATUS_CHOICES = [
        (PENDING, 'Pending'),
        (LIVE, 'Live'),
        (COMPLETED, 'Completed'),
        (BYE, 'Bye — advanced without fighting'),
    ]

    competition = models.ForeignKey(Competition, related_name='matches', on_delete=models.CASCADE)
    round_number = models.PositiveSmallIntegerField()
    position = models.PositiveSmallIntegerField(help_text='Index of this match within its round')

    participant_a = models.ForeignKey(
        Participant, null=True, blank=True, on_delete=models.SET_NULL, related_name='matches_as_a'
    )
    participant_b = models.ForeignKey(
        Participant, null=True, blank=True, on_delete=models.SET_NULL, related_name='matches_as_b'
    )
    winner = models.ForeignKey(
        Participant, null=True, blank=True, on_delete=models.SET_NULL, related_name='matches_won'
    )

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    current_round = models.PositiveSmallIntegerField(default=1)

    # Where the winner goes next. Null on the final.
    next_match = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL, related_name='previous_matches'
    )
    next_slot = models.CharField(max_length=1, blank=True, choices=[('A', 'A'), ('B', 'B')])

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['round_number', 'position']
        unique_together = ('competition', 'round_number', 'position')

    def __str__(self):
        return f'R{self.round_number}#{self.position}: {self.participant_a} vs {self.participant_b}'

    def score_for(self, participant) -> int:
        if participant is None:
            return 0
        return sum(e.points for e in self.scoring_events.all() if e.participant_id == participant.id)

    @property
    def score_a(self) -> int:
        return self.score_for(self.participant_a)

    @property
    def score_b(self) -> int:
        return self.score_for(self.participant_b)

    @property
    def is_final(self) -> bool:
        return self.next_match_id is None and self.round_number == self.competition.matches.aggregate(
            m=models.Max('round_number')
        )['m']


class ScoringEvent(models.Model):
    """A point, penalty or warning awarded during a bout. Bout scores are the
    sum of these rather than a stored total, so any entry can be undone and the
    scoring stays auditable."""

    POINT = 'POINT'
    PENALTY = 'PENALTY'
    WARNING = 'WARNING'
    KIND_CHOICES = [
        (POINT, 'Point'),
        (PENALTY, 'Penalty'),
        (WARNING, 'Warning'),
    ]

    match = models.ForeignKey(Match, related_name='scoring_events', on_delete=models.CASCADE)
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name='scoring_events')
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=POINT)
    points = models.SmallIntegerField(default=1, help_text='Negative for penalties against this competitor')
    technique = models.CharField(max_length=100, blank=True)
    round_number = models.PositiveSmallIntegerField(default=1)
    judge = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.participant} {self.points:+d} ({self.kind})'


class Performance(models.Model):
    """One judged technique routine — a competitor (or team) performing a form."""

    PENDING = 'PENDING'
    LIVE = 'LIVE'
    COMPLETED = 'COMPLETED'
    STATUS_CHOICES = [
        (PENDING, 'Pending'),
        (LIVE, 'Live'),
        (COMPLETED, 'Completed'),
    ]

    competition = models.ForeignKey(Competition, related_name='performances', on_delete=models.CASCADE)
    participant = models.ForeignKey(Participant, related_name='performances', on_delete=models.CASCADE)
    order = models.PositiveSmallIntegerField(default=0, help_text='Running order')
    form_name = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    final_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    penalty = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'id']
        unique_together = ('competition', 'participant')

    def __str__(self):
        return f'{self.participant} — {self.form_name or self.competition.name}'

    def compute_final_score(self):
        """Trimmed mean (drop highest and lowest) once at least three judges have
        scored, otherwise a plain average. Any penalty is then deducted.

        The regulations point to the WFVV 2016 rules for the judging formula
        without restating it, so the mode is configurable per competition.
        """
        scores = sorted(Decimal(str(s.score)) for s in self.judge_scores.all())
        if not scores:
            return None
        if self.competition.scoring_mode == Competition.SCORING_TRIMMED and len(scores) >= 3:
            scores = scores[1:-1]
        average = sum(scores) / len(scores)
        # penalty may arrive as a float or string from the API before it is saved
        penalty = Decimal(str(self.penalty or 0))
        return (average - penalty).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    def refresh_final_score(self, commit=True):
        self.final_score = self.compute_final_score()
        if commit:
            self.save(update_fields=['final_score'])
        return self.final_score


class JudgeScore(models.Model):
    """One judge's mark for one performance. `judge_name` lets a single operator
    enter the panel's marks at a club event; `judge_user` records who typed it."""

    performance = models.ForeignKey(Performance, related_name='judge_scores', on_delete=models.CASCADE)
    judge_name = models.CharField(max_length=100)
    judge_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    score = models.DecimalField(max_digits=4, decimal_places=2)
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['judge_name', 'id']
        unique_together = ('performance', 'judge_name')

    def __str__(self):
        return f'{self.judge_name}: {self.score}'
