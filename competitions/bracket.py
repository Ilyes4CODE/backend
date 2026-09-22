"""Single-elimination bracket generation and progression.

Seeding follows the standard tournament pattern (1 v lowest, 2 in the opposite
half, and so on), so when the entry list is not a power of two the resulting
empty slots — the byes — fall to the top seeds, exactly as they do in a
Champions League style knockout draw. A competitor drawn against an empty slot
advances without fighting.
"""

import math

from django.db import transaction
from django.utils import timezone

from .models import Match


def seed_slots(size: int) -> list[int]:
    """Bracket slot order for `size` (a power of two).

    For 8 this yields [1, 8, 4, 5, 2, 7, 3, 6] — pairing consecutive entries
    gives 1v8, 4v5, 2v7, 3v6, which keeps the top two seeds apart until the final.
    """
    slots = [1]
    while len(slots) < size:
        round_size = len(slots) * 2
        expanded = []
        for slot in slots:
            expanded.append(slot)
            expanded.append(round_size + 1 - slot)
        slots = expanded
    return slots


def bracket_size_for(count: int) -> int:
    if count < 2:
        return 2
    return 2 ** math.ceil(math.log2(count))


@transaction.atomic
def generate_bracket(competition) -> list[Match]:
    """(Re)builds the knockout bracket for a combat competition."""
    entrants = list(competition.participants.filter(withdrawn=False))
    if len(entrants) < 2:
        raise ValueError('At least two competitors are needed to draw a bracket.')

    # Seeded competitors first (seed 1, 2, 3 ...), then unseeded in entry order.
    entrants.sort(key=lambda p: (p.seed == 0, p.seed, p.id))

    competition.matches.all().delete()

    size = bracket_size_for(len(entrants))
    total_rounds = int(math.log2(size))
    order = seed_slots(size)

    # Slot number -> competitor, or None where the bracket has a bye.
    by_slot = {slot: (entrants[slot - 1] if slot <= len(entrants) else None) for slot in order}

    matches: dict[tuple[int, int], Match] = {}

    # Build later rounds first so round 1 can point at round 2.
    for round_number in range(total_rounds, 0, -1):
        count_in_round = size // (2 ** round_number)
        for position in range(count_in_round):
            parent = matches.get((round_number + 1, position // 2))
            matches[(round_number, position)] = Match.objects.create(
                competition=competition,
                round_number=round_number,
                position=position,
                next_match=parent,
                next_slot='A' if position % 2 == 0 else 'B',
            )

    # Seat the entrants in round 1.
    for position in range(size // 2):
        match = matches[(1, position)]
        match.participant_a = by_slot[order[position * 2]]
        match.participant_b = by_slot[order[position * 2 + 1]]
        match.save(update_fields=['participant_a', 'participant_b'])

    # Byes exist only in round 1. Because the bracket size is the next power of
    # two above the entry count, every first-round pairing holds at least one
    # competitor, so no later round can have a permanently empty slot — a gap
    # there just means the feeding bout has not been fought yet.
    for position in range(size // 2):
        resolve_bye(matches[(1, position)])

    return sorted(matches.values(), key=lambda m: (m.round_number, m.position))


def resolve_bye(match: Match) -> bool:
    """If a first-round match has only one competitor drawn into it, advance them
    without a fight. Returns True when a bye was applied."""
    match.refresh_from_db()
    if match.round_number != 1 or match.status not in (Match.PENDING, Match.BYE):
        return False
    a, b = match.participant_a, match.participant_b
    if (a is None) == (b is None):  # both drawn, or the slot is genuinely empty
        return False

    match.winner = a or b
    match.status = Match.BYE
    match.finished_at = timezone.now()
    match.save(update_fields=['winner', 'status', 'finished_at'])
    advance_winner(match)
    return True


def advance_winner(match: Match) -> None:
    """Seat the winner in their next bout."""
    if match.winner is None or match.next_match is None:
        return
    parent = match.next_match
    if match.next_slot == 'A':
        parent.participant_a = match.winner
    else:
        parent.participant_b = match.winner
    parent.save(update_fields=['participant_a', 'participant_b'])


def standings(competition) -> list[dict]:
    """Final placings.

    Section VII.1 of the regulations: the two semi-final losers share third
    place, so a combat class awards 1 gold, 1 silver and 2 bronze.
    """
    matches = list(competition.matches.all())
    if not matches:
        return []

    total_rounds = max(m.round_number for m in matches)
    final = next((m for m in matches if m.round_number == total_rounds), None)
    if final is None or final.winner is None:
        return []

    places: list[dict] = [{'place': 1, 'medal': 'GOLD', 'participant': final.winner}]

    runner_up = final.participant_a if final.winner_id == final.participant_b_id else final.participant_b
    if runner_up:
        places.append({'place': 2, 'medal': 'SILVER', 'participant': runner_up})

    if total_rounds >= 2:
        for semi in [m for m in matches if m.round_number == total_rounds - 1]:
            if not semi.winner:
                continue
            loser = semi.participant_a if semi.winner_id == semi.participant_b_id else semi.participant_b
            if loser:
                places.append({'place': 3, 'medal': 'BRONZE', 'participant': loser})

    return places
