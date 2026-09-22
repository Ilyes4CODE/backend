"""Training groups (أفواج) and the weekly timetable each club runs.

A group belongs to one club — optionally to one of its centers — holds a set of
members drawn from that club's registrations, and repeats on a weekly schedule
("Monday 17:30–19:00"). Club owners manage their own groups; the super admin
sees them all.
"""

from django.db import models


class TrainingGroup(models.Model):
    """A فوج: a squad that trains together on a fixed weekly timetable."""

    club = models.ForeignKey('organization.Club', related_name='groups', on_delete=models.CASCADE)
    center = models.ForeignKey(
        'organization.Center', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='groups',
    )
    name_ar = models.CharField(max_length=120)
    name_en = models.CharField(max_length=120)
    coach = models.CharField(max_length=150, blank=True)
    capacity = models.PositiveSmallIntegerField(default=0, help_text='0 means no limit')
    members = models.ManyToManyField(
        'registrations.Registration', related_name='training_groups', blank=True,
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['club__name_en', 'name_en']
        unique_together = ('club', 'name_en')

    def __str__(self):
        return f'{self.name_en} — {self.club.name_en}'

    @property
    def member_count(self) -> int:
        return self.members.count()

    @property
    def is_full(self) -> bool:
        return bool(self.capacity) and self.member_count >= self.capacity


class WeeklySession(models.Model):
    """One recurring slot in a group's week."""

    MONDAY = 0
    WEEKDAY_CHOICES = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday'),
    ]

    group = models.ForeignKey(TrainingGroup, related_name='sessions', on_delete=models.CASCADE)
    weekday = models.PositiveSmallIntegerField(choices=WEEKDAY_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    note = models.CharField(max_length=150, blank=True)

    class Meta:
        ordering = ['weekday', 'start_time']
        unique_together = ('group', 'weekday', 'start_time')

    def __str__(self):
        return f'{self.get_weekday_display()} {self.start_time:%H:%M}-{self.end_time:%H:%M}'

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValidationError({'end_time': 'The session must end after it starts.'})
