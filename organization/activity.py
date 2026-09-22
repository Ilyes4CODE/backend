"""Who did what, and when.

Three levels of people can now approve candidates, mark money as received,
open branches and hand out accounts. When a payment turns out to be wrong, the
first question is "who marked it paid?" — this table answers it.

Each entry carries the club and branch it concerns, so the log is scoped exactly
like everything else: a branch manager reads their branch's history, a club
president reads the whole club's, and the national administrator reads all of
it. Nobody reads upward.

The actor's email is copied onto the row as well as linked: an account can be
deactivated or deleted later, and the history must still say who it was.
"""

from django.conf import settings
from django.db import models


class ActivityLog(models.Model):
    REGISTRATION_STATUS = 'REGISTRATION_STATUS'
    REGISTRATION_PAYMENT = 'REGISTRATION_PAYMENT'
    REGISTRATION_TRANSFER = 'REGISTRATION_TRANSFER'
    BRANCH_CREATED = 'BRANCH_CREATED'
    BRANCH_UPDATED = 'BRANCH_UPDATED'
    BRANCH_DELETED = 'BRANCH_DELETED'
    ACCOUNT_CREATED = 'ACCOUNT_CREATED'
    ACCOUNT_UPDATED = 'ACCOUNT_UPDATED'
    ACCOUNT_DEACTIVATED = 'ACCOUNT_DEACTIVATED'
    ACCOUNT_REACTIVATED = 'ACCOUNT_REACTIVATED'
    PASSWORD_RESET = 'PASSWORD_RESET'
    ACTION_CHOICES = [
        (REGISTRATION_STATUS, 'Registration status changed'),
        (REGISTRATION_PAYMENT, 'Payment status changed'),
        (REGISTRATION_TRANSFER, 'Member moved to another branch'),
        (BRANCH_CREATED, 'Branch created'),
        (BRANCH_UPDATED, 'Branch updated'),
        (BRANCH_DELETED, 'Branch deleted'),
        (ACCOUNT_CREATED, 'Account created'),
        (ACCOUNT_UPDATED, 'Account updated'),
        (ACCOUNT_DEACTIVATED, 'Account deactivated'),
        (ACCOUNT_REACTIVATED, 'Account reactivated'),
        (PASSWORD_RESET, 'Password reset'),
    ]

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='activity',
    )
    actor_label = models.CharField(max_length=254, blank=True)
    club = models.ForeignKey(
        'organization.Club', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='activity',
    )
    center = models.ForeignKey(
        'organization.Center', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='activity',
    )
    action = models.CharField(max_length=24, choices=ACTION_CHOICES)
    # A human label for what was touched — a reference, a branch name, an email.
    # Kept as text so the entry survives the thing it describes being deleted.
    target = models.CharField(max_length=200)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.actor_label or "system"}: {self.get_action_display()} — {self.target}'


def record(actor, action, target, *, club=None, center=None, **detail):
    """Append one entry. Never raises into the caller: losing a log line must
    not roll back the change it was describing."""
    try:
        ActivityLog.objects.create(
            actor=actor if getattr(actor, 'pk', None) else None,
            actor_label=getattr(actor, 'email', '') or getattr(actor, 'username', '') or '',
            club=club,
            center=center,
            action=action,
            target=str(target)[:200],
            detail=detail,
        )
    except Exception:  # pragma: no cover - defensive
        pass
