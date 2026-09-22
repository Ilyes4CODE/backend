from django.contrib import admin

from .models import Competition, JudgeScore, Match, Participant, Performance, ScoringEvent


class ParticipantInline(admin.TabularInline):
    model = Participant
    extra = 0


@admin.register(Competition)
class CompetitionAdmin(admin.ModelAdmin):
    list_display = ['name', 'type', 'gender', 'weight_class', 'technique_event', 'status', 'created_at']
    list_filter = ['type', 'status', 'gender']
    inlines = [ParticipantInline]


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ['competition', 'round_number', 'position', 'participant_a', 'participant_b', 'status', 'winner']
    list_filter = ['competition', 'status']


@admin.register(Performance)
class PerformanceAdmin(admin.ModelAdmin):
    list_display = ['competition', 'participant', 'order', 'status', 'final_score']
    list_filter = ['competition', 'status']


admin.site.register([Participant, ScoringEvent, JudgeScore])
