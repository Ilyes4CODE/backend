from django.test import TestCase

from .bracket import bracket_size_for, generate_bracket, seed_slots, standings
from .models import Competition, Match, Participant


def make_competition(n, **kwargs):
    competition = Competition.objects.create(
        name=f'Test {n}', type=Competition.COMBAT, weight_class='M60_65', **kwargs
    )
    for i in range(1, n + 1):
        Participant.objects.create(competition=competition, name=f'P{i}', seed=i)
    return competition


def win(match, participant):
    """Close a bout the way the API does."""
    from .bracket import advance_winner
    match.winner = participant
    match.status = Match.COMPLETED
    match.save()
    advance_winner(match)


class SeedingTests(TestCase):
    def test_seed_slots_keeps_top_seeds_apart(self):
        self.assertEqual(seed_slots(2), [1, 2])
        self.assertEqual(seed_slots(4), [1, 4, 2, 3])
        self.assertEqual(seed_slots(8), [1, 8, 4, 5, 2, 7, 3, 6])

    def test_bracket_size_rounds_up_to_power_of_two(self):
        self.assertEqual(bracket_size_for(2), 2)
        self.assertEqual(bracket_size_for(3), 4)
        self.assertEqual(bracket_size_for(5), 8)
        self.assertEqual(bracket_size_for(8), 8)
        self.assertEqual(bracket_size_for(9), 16)


class BracketTests(TestCase):
    def test_power_of_two_has_no_byes(self):
        competition = make_competition(8)
        generate_bracket(competition)
        self.assertEqual(competition.matches.count(), 7)  # 4 + 2 + 1
        self.assertEqual(competition.matches.filter(status=Match.BYE).count(), 0)

    def test_odd_entry_gives_the_top_seed_a_bye(self):
        """Three entrants: the top seed passes without fighting."""
        competition = make_competition(3)
        generate_bracket(competition)

        byes = competition.matches.filter(status=Match.BYE)
        self.assertEqual(byes.count(), 1)
        self.assertEqual(byes.first().winner.name, 'P1')

        # ...and is already seated in the final.
        final = competition.matches.get(round_number=2)
        self.assertEqual(final.participant_a.name, 'P1')
        self.assertIsNone(final.participant_b)

    def test_five_entrants_give_three_byes_to_the_top_seeds(self):
        competition = make_competition(5)
        generate_bracket(competition)
        byes = competition.matches.filter(status=Match.BYE)
        self.assertEqual(byes.count(), 3)
        self.assertEqual(
            sorted(b.winner.name for b in byes), ['P1', 'P2', 'P3']
        )

    def test_every_first_round_match_has_at_least_one_competitor(self):
        for n in range(2, 17):
            competition = make_competition(n)
            generate_bracket(competition)
            for match in competition.matches.filter(round_number=1):
                self.assertTrue(
                    match.participant_a or match.participant_b,
                    f'empty first-round match with {n} entrants',
                )

    def test_a_pending_opponent_does_not_trigger_a_false_bye(self):
        """A later-round slot that is merely waiting on a bout must not be
        treated as a bye."""
        competition = make_competition(3)
        generate_bracket(competition)
        final = competition.matches.get(round_number=2)
        self.assertEqual(final.status, Match.PENDING)
        self.assertIsNone(final.winner)

    def test_winner_advances_to_the_next_round(self):
        competition = make_competition(4)
        generate_bracket(competition)
        first = competition.matches.get(round_number=1, position=0)
        win(first, first.participant_a)
        final = competition.matches.get(round_number=2)
        self.assertEqual(final.participant_a, first.participant_a)


class StandingsTests(TestCase):
    def test_both_semi_final_losers_take_third_place(self):
        """Section VII.1 of the regulations — 1 gold, 1 silver, 2 bronze."""
        competition = make_competition(4)
        generate_bracket(competition)

        semis = list(competition.matches.filter(round_number=1))
        for semi in semis:
            win(semi, semi.participant_a)

        final = competition.matches.get(round_number=2)
        final.refresh_from_db()
        win(final, final.participant_a)

        rows = standings(competition)
        self.assertEqual([r['medal'] for r in rows], ['GOLD', 'SILVER', 'BRONZE', 'BRONZE'])
        self.assertEqual([r['place'] for r in rows], [1, 2, 3, 3])

        bronze = {r['participant'].name for r in rows if r['medal'] == 'BRONZE'}
        self.assertEqual(bronze, {s.participant_b.name for s in semis})

    def test_no_standings_until_the_final_is_decided(self):
        competition = make_competition(4)
        generate_bracket(competition)
        self.assertEqual(standings(competition), [])


class TechniqueScoringTests(TestCase):
    def setUp(self):
        self.competition = Competition.objects.create(
            name='Quyen', type=Competition.TYPE_CHOICES[1][0],
            technique_event='QUYEN_PRESCRIBED', judge_count=5,
        )
        self.participant = Participant.objects.create(competition=self.competition, name='A')

    def _performance(self, scores, penalty=0):
        from .models import JudgeScore, Performance
        performance = Performance.objects.create(
            competition=self.competition, participant=self.participant, penalty=penalty
        )
        for i, score in enumerate(scores):
            JudgeScore.objects.create(performance=performance, judge_name=f'J{i}', score=score)
        return performance

    def test_trimmed_mean_drops_highest_and_lowest(self):
        # 8.0 and 9.5 dropped; mean of 8.5, 9.0, 9.0
        performance = self._performance([8.0, 8.5, 9.0, 9.0, 9.5])
        self.assertEqual(float(performance.refresh_final_score()), 8.83)

    def test_plain_average_when_fewer_than_three_judges(self):
        performance = self._performance([8.0, 9.0])
        self.assertEqual(float(performance.refresh_final_score()), 8.5)

    def test_penalty_is_deducted(self):
        performance = self._performance([9.0, 9.0, 9.0], penalty=0.5)
        self.assertEqual(float(performance.refresh_final_score()), 8.5)

    def test_average_mode_keeps_every_mark(self):
        self.competition.scoring_mode = Competition.SCORING_AVERAGE
        self.competition.save()
        performance = self._performance([8.0, 9.0, 10.0])
        self.assertEqual(float(performance.refresh_final_score()), 9.0)
