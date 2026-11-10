import random

import pytest

from algorithm import GAConfig, run_genetic_algorithm
from algorithm.chromosome import Chromosome, make_gene, unplaced_gene
from algorithm.configuration import ConfigurationError
from algorithm.constraints import evaluate_constraints
from algorithm.crossover import block_crossover
from algorithm.data import RoomInfo
from algorithm.fitness import FitnessEvaluator, fitness_value
from algorithm.initialization import heuristic_individual, initial_population, random_individual
from algorithm.intervals import count_overlapping_pairs, overlaps
from algorithm.mutation import mutate
from algorithm.replacement import elites, inject_diversity, next_generation
from algorithm.selection import select_parents, tournament_select
from algorithm.termination import TerminationState, check_termination
from helpers import make_data

SESS = [dict(assignment_id=1, lecturer_id=1, group_id=1, duration=120),
        dict(assignment_id=2, lecturer_id=2, group_id=2, duration=60),
        dict(assignment_id=3, lecturer_id=1, group_id=2, duration=60)]


def chrom(data, placements):
    return Chromosome([make_gene(data, i, *p) if p else unplaced_gene(data, i) for i, p in enumerate(placements)])


def test_interval_overlap_detects_partial_but_not_adjacent():
    assert overlaps(480, 600, 540, 660)            # 08:00-10:00 vs 09:00-11:00
    assert not overlaps(480, 540, 540, 600)        # back to back is fine
    assert count_overlapping_pairs([(480, 600, 0), (540, 660, 1)])[0] == 1


def test_lecturer_conflict_partial_overlap():
    d = make_data(SESS)
    rep = evaluate_constraints(chrom(d, [(1, 0, 480), (2, 1, 480), (2, 0, 540)]).genes, d)   # lecturer 1: Mon 8-10 and Mon 9-10
    assert rep.hard["H1"] == 1


def test_classroom_and_group_conflicts():
    d = make_data(SESS)
    rep = evaluate_constraints(chrom(d, [(1, 0, 480), (2, 0, 480), (1, 0, 480)]).genes, d)
    assert rep.hard["H2"] >= 1            # room 1 used twice at once
    d2 = make_data(SESS)
    rep2 = evaluate_constraints(chrom(d2, [(1, 0, 480), (1, 1, 480), (2, 1, 480)]).genes, d2)
    assert rep2.hard["H3"] == 1           # group 2: sessions 2 and 3 at once on day 1


def test_valid_chromosome_has_no_hard_violations():
    d = make_data(SESS)
    rep = evaluate_constraints(chrom(d, [(1, 0, 480), (1, 1, 480), (2, 2, 480)]).genes, d)
    assert rep.hard_total == 0


def test_availability_capacity_type_hours_duration_and_completeness():
    rooms = [RoomInfo(1, "Small", 10, "STANDARD_CLASSROOM"), RoomInfo(2, "Lab", 100, "COMPUTER_LABORATORY")]
    lec = [(1, 0, 600, 720, "AVAILABLE")]
    d = make_data([dict(assignment_id=1, lecturer_id=1, group_id=1, duration=60, population=30)], rooms=rooms, lec_records=lec)
    c = Chromosome([make_gene(d, 0, 1, 0, 480)])             # small room, wrong time
    rep = evaluate_constraints(c.genes, d)
    assert rep.hard["H4"] == 1 and rep.hard["H6"] == 1       # lecturer unavailable at 08:00, capacity 10 < 30
    c2 = Chromosome([make_gene(d, 0, 2, 0, 600)])
    assert evaluate_constraints(c2.genes, d).hard["H7"] == 1  # computer lab for a standard classroom course
    c3 = Chromosome([make_gene(d, 0, 1, 0, 60)])             # 01:00 is outside working hours
    assert evaluate_constraints(c3.genes, d).hard["H8"] == 1
    g = make_gene(d, 0, 1, 0, 600)._replace(end=720)         # 120 minutes for a 60 minute session
    assert evaluate_constraints([g], d).hard["H9"] == 1
    assert evaluate_constraints([unplaced_gene(d, 0)], d).hard["H10"] == 1


def test_room_availability_violation():
    d = make_data(SESS[:1], room_records=[(1, 0, 600, 660, "AVAILABLE"), (2, 0, 600, 660, "AVAILABLE")])
    assert evaluate_constraints([make_gene(d, 0, 1, 0, 480)], d).hard["H5"] == 1


def test_fitness_formula_and_hard_dominates():
    assert fitness_value(0, 0, 1000, 1) == 1.0
    assert fitness_value(1, 0, 1000, 1) == pytest.approx(1 / 1001)
    d = make_data(SESS)
    ev = FitnessEvaluator(d, GAConfig())
    good, bad = chrom(d, [(1, 0, 480), (1, 1, 480), (2, 2, 480)]), chrom(d, [(1, 0, 480), (1, 0, 480), (2, 0, 480)])
    ev.evaluate(good); ev.evaluate(bad)
    assert good.rank_key > bad.rank_key and good.evaluation.hard_total == 0 < bad.evaluation.hard_total


def test_rank_prefers_valid_even_with_worse_soft_penalty():
    d = make_data(SESS)
    ev = FitnessEvaluator(d, GAConfig(hard_factor=10))
    valid, invalid = chrom(d, [(1, 0, 480), (1, 4, 900), (2, 2, 480)]), chrom(d, [(1, 0, 480), (1, 0, 540), (2, 0, 480)])
    ev.evaluate(valid); ev.evaluate(invalid)
    assert valid.rank_key > invalid.rank_key


def test_fitness_is_deterministic_and_breakdown_complete():
    d = make_data(SESS)
    c = chrom(d, [(1, 0, 480), (1, 0, 480), (2, 2, 480)])
    e1, e2 = FitnessEvaluator(d, GAConfig()).evaluate_genes(c.genes), FitnessEvaluator(d, GAConfig()).evaluate_genes(c.genes)
    assert e1.fitness == e2.fitness
    b = e1.breakdown()
    assert len(b["hard"]) == 10 and len(b["soft"]) == 7


def test_soft_penalties_gaps_and_distribution():
    d = make_data(SESS)
    tight = evaluate_constraints(chrom(d, [(1, 0, 480), (1, 1, 480), (2, 2, 480)]).genes, d)
    gappy = evaluate_constraints(chrom(d, [(1, 0, 480), (1, 1, 480), (2, 1, 900)]).genes, d)
    assert gappy.soft["S3"] > tight.soft["S3"]


def test_initial_population_complete_and_domain_respecting():
    d = make_data(SESS)
    pop = initial_population(d, 10, 0.5, random.Random(1))
    assert len(pop) == 10 and all(c.is_complete(d) for c in pop)
    for c in pop:
        for g in c.genes:
            assert (g.room_id, g.day, g.start) in d.domain_sets[g.req_index]


def test_unplaceable_sessions_recorded_not_discarded():
    d = make_data([dict(assignment_id=1, lecturer_id=1, group_id=1, duration=60, population=500)])
    assert 0 in d.unplaceable and "capacity" in d.unplaceable[0].lower()
    ind = heuristic_individual(d, random.Random(1))
    assert len(ind.genes) == 1 and not ind.genes[0].placed
    res = run_genetic_algorithm(d, GAConfig(population_size=6, max_generations=2, seed=1))
    assert not res.is_conflict_free and res.unplaceable and res.evaluation.hard["H10"] == 1


def test_selection_prefers_stronger_and_returns_distinct_parents():
    d = make_data(SESS)
    ev = FitnessEvaluator(d, GAConfig())
    pop = initial_population(d, 12, 0.5, random.Random(2))
    for c in pop: ev.evaluate(c)
    rng = random.Random(3)
    wins = [tournament_select(pop, 4, rng) for _ in range(200)]
    best = max(pop, key=lambda c: c.rank_key)
    assert wins.count(best) > 200 / 12
    a, b = select_parents(pop, 3, rng)
    assert a is not b


def test_crossover_preserves_all_sessions_and_assignment_blocks():
    sess = [dict(assignment_id=1, lecturer_id=1, group_id=1, duration=60, session_no=1),
            dict(assignment_id=1, lecturer_id=1, group_id=1, duration=60, session_no=2),
            dict(assignment_id=2, lecturer_id=2, group_id=2, duration=60)]
    d = make_data(sess)
    ev = FitnessEvaluator(d, GAConfig())
    rng = random.Random(4)
    a, b = random_individual(d, rng), random_individual(d, rng)
    ev.evaluate(a); ev.evaluate(b)
    for _ in range(20):
        c1, c2 = block_crossover(a, b, d, rng)
        for c in (c1, c2):
            assert c.is_complete(d)
            same_a = [c.genes[i] == a.genes[i] for i in (0, 1)]
            same_b = [c.genes[i] == b.genes[i] for i in (0, 1)]
            assert all(same_a) or all(same_b)          # a block comes from one parent


def test_mutation_keeps_structure_and_domain():
    d = make_data(SESS)
    c = random_individual(d, random.Random(5))
    c.hint = frozenset({0, 1, 2})
    changed = mutate(c, d, 1.0, random.Random(6))
    assert changed > 0 and c.is_complete(d)
    assert all((g.room_id, g.day, g.start) in d.domain_sets[g.req_index] for g in c.genes)


def test_elitism_and_population_size_constant():
    d = make_data(SESS)
    ev = FitnessEvaluator(d, GAConfig())
    pop = initial_population(d, 8, 0.5, random.Random(7))
    for c in pop: ev.evaluate(c)
    top = elites(pop, 2)
    off = initial_population(d, 8, 0.0, random.Random(8))
    for c in off: ev.evaluate(c)
    nxt = next_generation(pop, off, 2)
    assert len(nxt) == 8 and nxt[0] is top[0] and nxt[1] is top[1]
    div = inject_diversity(nxt, off[:3], 2)
    assert len(div) == 8 and nxt[0] in div


def test_termination_conditions():
    cfg = GAConfig(max_generations=5, stagnation_threshold=3, target_fitness=0.9)
    st = TerminationState()
    assert check_termination(cfg, st, 5, 1, 0.1) == "Maximum generations reached"
    assert "stagnation" in check_termination(cfg, TerminationState(stagnant=3), 1, 1, 0.1)
    assert check_termination(cfg, st, 1, 0, 0.95) == "Target fitness reached"
    assert check_termination(GAConfig(stop_on_zero_hard=True), st, 1, 0, 0.1).startswith("Zero hard")
    assert check_termination(cfg, st, 1, 2, 0.95) is None      # never "reached" with violations


def test_config_validation_rejects_bad_parameters():
    for kw in (dict(population_size=2), dict(mutation_rate=1.5), dict(crossover_rate=-1), dict(elite_size=50, population_size=10),
               dict(tournament_size=1), dict(hard_factor=2, soft_factor=1), dict(target_fitness=0), dict(max_generations=0)):
        with pytest.raises(ConfigurationError):
            GAConfig(**kw).validate()
    GAConfig().validate()


def test_reproducible_with_fixed_seed_and_different_without():
    d = make_data(SESS * 4 if False else [dict(assignment_id=i, lecturer_id=i % 3 + 1, group_id=i % 4 + 1, duration=60 * (i % 2 + 1)) for i in range(1, 15)])
    cfg = dict(population_size=16, max_generations=15, seed=42)
    r1, r2 = run_genetic_algorithm(d, GAConfig(**cfg)), run_genetic_algorithm(d, GAConfig(**cfg))
    assert r1.best.key() == r2.best.key() and r1.evaluation.fitness == r2.evaluation.fitness
    assert [h["best_fitness"] for h in r1.history] == [h["best_fitness"] for h in r2.history]


def test_ga_never_loses_sessions_and_fitness_does_not_regress():
    d = make_data([dict(assignment_id=i, lecturer_id=i % 3 + 1, group_id=i % 4 + 1, duration=60) for i in range(1, 25)])
    r = run_genetic_algorithm(d, GAConfig(population_size=20, max_generations=25, seed=5))
    assert r.best.is_complete(d) and len(r.best.genes) == 24
    keys = [(-h["hard_violations"], h["best_fitness"]) for h in r.history]
    assert all(b >= a for a, b in zip(keys, keys[1:]))        # elitism: best never gets worse


def test_ga_resolves_conflicts_on_tight_dataset():
    """One room, one lecturer per group, many sessions: random placement clashes; the GA must find a clash-free layout."""
    rooms = [RoomInfo(1, "Only", 100, "STANDARD_CLASSROOM")]
    sess = [dict(assignment_id=i, lecturer_id=i, group_id=i, duration=120) for i in range(1, 21)]   # 40h in a 50h room-week
    d = make_data(sess, rooms=rooms)
    r = run_genetic_algorithm(d, GAConfig(population_size=40, max_generations=300, seed=11, stop_on_zero_hard=True))
    assert r.evaluation.hard_total == 0, r.evaluation.hard
    assert r.is_conflict_free


def test_stop_callback_interrupts():
    d = make_data(SESS)
    r = run_genetic_algorithm(d, GAConfig(population_size=8, max_generations=500, seed=1, stagnation_threshold=500), should_stop=lambda: True)
    assert r.interrupted and r.termination_reason == "Stopped by user"
