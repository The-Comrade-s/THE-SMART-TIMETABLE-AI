from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from algorithm.configuration import GAConfig


@dataclass
class TerminationState:
    best_key: tuple = (-10 ** 9, 0.0)
    best_generation: int = 0
    stagnant: int = 0

    def update(self, generation: int, key: tuple) -> None:
        if key > self.best_key:
            self.best_key, self.best_generation, self.stagnant = key, generation, 0
        else:
            self.stagnant += 1


def check_termination(config: GAConfig, state: TerminationState, generation: int, hard_total: int,
                      fitness: float) -> Optional[str]:
    if hard_total == 0 and config.stop_on_zero_hard:
        return "Zero hard constraint violations reached"
    if fitness >= config.target_fitness and hard_total == 0:
        return "Target fitness reached"
    if state.stagnant >= config.stagnation_threshold:
        return f"No improvement for {config.stagnation_threshold} generations (stagnation)"
    if generation >= config.max_generations:
        return "Maximum generations reached"
    return None
