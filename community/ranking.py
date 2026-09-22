"""How the community feed decides what to show first.

A plain "newest first" feed buries a busy post the moment anything else is
published, and a plain "most liked" feed freezes on last year's news. This is
the usual compromise: engagement decides the order among posts of a similar
age, and age decides it among posts of similar engagement.

    score = log10(1 + engagement) + seconds_since_epoch / DECAY

`log10` is what keeps it stable. Engagement has to grow *ten-fold* to buy a
post another whole point, so one popular item cannot sit at the top forever,
while DECAY sets how much time it takes for a fresh post to earn that same
point on age alone. The `1 +` matters: `log10(max(e, 1))` would score a post
with one like exactly like a post with none, so the first like — the one that
tells you anybody read it at all — would do nothing.

Everything here is deterministic — same inputs, same score — so the ordering a
visitor sees on page 2 is the ordering page 1 was cut from. Callers add the
post's id as a final tiebreak, which is what makes paging safe when two posts
score identically.
"""

import math
from datetime import datetime, timezone as dt_timezone

#: Seconds of age worth one point of score. 45 000 ≈ 12.5 hours, so a post
#: needs roughly a day and a half to fall behind a same-day post with ten times
#: its engagement. Tuned for a club that posts a few times a week, not a
#: firehose.
DECAY_SECONDS = 45_000.0

#: A comment is worth more than a like: it took real effort to leave.
LIKE_WEIGHT = 1.0
COMMENT_WEIGHT = 2.5

_EPOCH = datetime(2024, 1, 1, tzinfo=dt_timezone.utc)


def engagement(likes: int, comments: int) -> float:
    """Weighted interaction total. Never negative — counters can only be
    corrupted downward by a bad migration, and a negative log would explode."""
    return max(0.0, LIKE_WEIGHT * max(likes, 0) + COMMENT_WEIGHT * max(comments, 0))


def rank_score(published_at: datetime, likes: int = 0, comments: int = 0) -> float:
    """The cached ordering key for one post.

    `published_at` may be naive if it came from a fixture; treat it as UTC
    rather than raising, since a bad timestamp must not take the feed down.
    """
    if published_at is None:
        return 0.0
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=dt_timezone.utc)

    age_component = (published_at - _EPOCH).total_seconds() / DECAY_SECONDS
    weight = math.log10(1.0 + engagement(likes, comments))
    return round(weight + age_component, 6)


def order_feed(queryset):
    """Apply the feed ordering to a queryset of posts.

    Pinned first, then score, then id. The id is not decoration: without a
    unique final key, two posts with the same score can swap places between the
    query for page 1 and the query for page 2, so a visitor sees one of them
    twice and never sees the other.
    """
    return queryset.order_by('-pinned', '-rank_score', '-id')
