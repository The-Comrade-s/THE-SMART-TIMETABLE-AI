"""Genetic Algorithm driver."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from algorithm.chromosome import Chromosome
from algorithm.configuration import GAConfig
from algorithm.crossover import block_crossover
from algorithm.data import SchedulingData
from algorithm.fitness import Evaluation, FitnessEvaluator
from algorithm.initialization import heuristic_individual, initial_population, unplaceable_report
from algorithm.mutation import mutate
from algorithm.replacement import elites, inject_diversity, next_generation
from algorithm.selection import select_parents
from algorithm.termination import TerminationState, check_termination

ProgressCallback = Callable[[dict], None]


@dataclass
class GAResult:
    best: Chromosome
    history: List[dict]
    initial_fitness: float
    initial_hard: int
    generations_run: int
    best_generation: int
    termination_reason: str
    elapsed_seconds: float
    population_size: int
    unplaceable: List[dict] = field(default_factory=list)
    evaluations: int = 0
    interrupted: bool = False

    @property
    def evaluation(self) -> Evaluation:
        return self.best.evaluation

    @property
    def is_conflict_free(self) -> bool:
        return self.best.evaluation.hard_total == 0 and not self.unplaceable


def run_genetic_algorithm(data: SchedulingData, config: GAConfig, seed_chromosomes: Optional[List[Chromosome]] = None,
                          progress: Optional[ProgressCallback] = None,
                          should_stop: Optional[Callable[[], bool]] = None) -> GAResult:
    config.validate()
    if not data.sessions:
        raise ValueError("There are no sessions to schedule.")
    if not data.domains:
        data.build_domains()
    rng = random.Random(config.seed)
    evaluator = FitnessEvaluator(data, config)
    t0 = time.perf_counter()

    population = initial_population(data, config.population_size, config.heuristic_ratio, rng, seed_chromosomes)
    for c in population:
        evaluator.evaluate(c)
        c.hint = c.hint or c.evaluation.conflict_genes
    best = max(population, key=lambda c: c.rank_key)
    initial_fitness, initial_hard = best.fitness, best.evaluation.hard_total
    state = TerminationState()
    state.update(0, best.rank_key)
    history: List[dict] = []
    reason, generation, interrupted = "", 0, False

    def record(gen: int) -> None:
        b = max(population, key=lambda c: c.rank_key)
        row = {"generation": gen, "best_fitness": b.fitness, "avg_fitness": sum(c.fitness for c in population) / len(population),
               "hard_violations": b.evaluation.hard_total, "soft_penalty": b.evaluation.soft_weighted,
               "elapsed": time.perf_counter() - t0}
        history.append(row)
        if progress:
            progress({**row, "max_generations": config.max_generations, "population_size": len(population)})

    record(0)
    while True:
        best_now = max(population, key=lambda c: c.rank_key)
        if best_now.rank_key > best.rank_key:
            best = best_now
        reason = check_termination(config, state, generation, best.evaluation.hard_total, best.fitness)
        if reason:
            break
        if should_stop and should_stop():
            reason, interrupted = "Stopped by user", True
            break
        generation += 1
        offspring: List[Chromosome] = []
        need = config.population_size - config.elite_size
        while len(offspring) < need:
            pa, pb = select_parents(population, config.tournament_size, rng)
            if rng.random() < config.crossover_rate:
                c1, c2 = block_crossover(pa, pb, data, rng)
            else:
                c1, c2 = pa.copy(), pb.copy()
                c1.hint, c2.hint = pa.evaluation.conflict_genes, pb.evaluation.conflict_genes
            for child in (c1, c2):
                mutate(child, data, config.mutation_rate, rng)
                evaluator.evaluate(child)
                offspring.append(child)
                if len(offspring) >= need:
                    break
        population = next_generation(population, offspring, config.elite_size)
        for c in population:
            if c.evaluation is not None:
                c.hint = c.evaluation.conflict_genes
        cur = max(population, key=lambda c: c.rank_key)
        state.update(generation, cur.rank_key)
        if state.stagnant and state.stagnant == max(1, config.stagnation_threshold // 2):
            n_fresh = max(1, config.population_size // 5)
            fresh = [heuristic_individual(data, rng) for _ in range(n_fresh)]
            for f in fresh:
                evaluator.evaluate(f)
            population = inject_diversity(population, fresh, max(1, config.elite_size))
        record(generation)

    best = max(population + [best], key=lambda c: c.rank_key)
    elapsed = time.perf_counter() - t0
    return GAResult(best=best, history=history, initial_fitness=initial_fitness, initial_hard=initial_hard,
                    generations_run=generation, best_generation=state.best_generation, termination_reason=reason,
                    elapsed_seconds=elapsed, population_size=config.population_size,
                    unplaceable=unplaceable_report(data), evaluations=evaluator.evaluations, interrupted=interrupted)
