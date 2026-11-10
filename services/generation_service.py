"""Timetable generation workflow: validate -> load -> evolve -> independently validate -> persist (atomically)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from algorithm import GAConfig, GAResult, run_genetic_algorithm
from algorithm.chromosome import Chromosome, make_gene, unplaced_gene
from algorithm.configuration import ConfigurationError
from algorithm.loader import load_scheduling_data
from auth.permissions import Permission, require
from database.models import (AlgorithmConfiguration, Department, GenerationHistory, Timetable, TimetableAudit,
                             TimetableEntry)
from services.common import ServiceError, ValidationError, get_or_404
from validation.prechecks import Issue, errors_only, run_prechecks
from validation.rules import from_minutes, to_minutes, validate_academic_session, validate_level, validate_semester
from validation.timetable_validator import Conflict, EntryDraft, summarise, validate_entries

log = logging.getLogger(__name__)


class PrecheckFailed(ServiceError):
    def __init__(self, issues: List[Issue]):
        self.issues = issues
        super().__init__("The scheduling data is incomplete. Resolve the listed problems before generating.")


@dataclass
class GenerationParams:
    academic_session: str
    semester: str
    config: GAConfig
    department_id: Optional[int] = None
    level: Optional[int] = None
    name: str = ""
    parent_id: Optional[int] = None          # re-optimisation of an earlier timetable
    seed_from_parent: bool = True
    configuration_id: Optional[int] = None
    room_ids: Optional[List[int]] = None     # restrict generation to these classrooms (None = all active rooms)


@dataclass
class GenerationOutcome:
    timetable_id: int
    history_id: int
    result: GAResult
    conflicts: List[Conflict]
    is_valid: bool
    status: str
    issues: List[Issue] = field(default_factory=list)


def config_from_row(row: AlgorithmConfiguration) -> GAConfig:
    return GAConfig(population_size=row.population_size, max_generations=row.max_generations,
                    mutation_rate=row.mutation_rate, crossover_rate=row.crossover_rate, elite_size=row.elite_size,
                    tournament_size=row.tournament_size, stagnation_threshold=row.stagnation_threshold,
                    target_fitness=row.target_fitness, stop_on_zero_hard=row.stop_on_zero_hard,
                    hard_factor=row.hard_factor, soft_factor=row.soft_factor,
                    hard_weights=dict(row.hard_weights or {}), soft_weights=dict(row.soft_weights or {}))


def save_configuration(session: Session, actor, name: str, config: GAConfig) -> AlgorithmConfiguration:
    require(actor, Permission.CONFIGURE_ALGORITHM)
    try:
        config.validate()
    except ConfigurationError as exc:
        raise ValidationError(str(exc)) from exc
    return _store_config(session, actor, name, config)


def _store_config(session: Session, actor, name: str, config: GAConfig) -> AlgorithmConfiguration:
    row = AlgorithmConfiguration(
        name=(name or "Generation run")[:120], population_size=config.population_size, max_generations=config.max_generations,
        mutation_rate=config.mutation_rate, crossover_rate=config.crossover_rate, elite_size=config.elite_size,
        tournament_size=config.tournament_size, stagnation_threshold=config.stagnation_threshold,
        target_fitness=config.target_fitness, stop_on_zero_hard=config.stop_on_zero_hard, hard_factor=config.hard_factor,
        soft_factor=config.soft_factor, hard_weights=dict(config.hard_weights), soft_weights=dict(config.soft_weights),
        created_by=getattr(actor, "id", None))
    session.add(row)
    session.flush()
    return row


def list_configurations(session: Session, actor) -> List[AlgorithmConfiguration]:
    require(actor, Permission.GENERATE)
    return list(session.scalars(select(AlgorithmConfiguration).where(AlgorithmConfiguration.name != "Generation run")
                                .order_by(AlgorithmConfiguration.created_at.desc())))


def precheck(session: Session, actor, academic_session: str, semester: str, department_id=None, level=None) -> List[Issue]:
    require(actor, Permission.GENERATE)
    return run_prechecks(session, validate_academic_session(academic_session), validate_semester(semester),
                         department_id, validate_level(level) if level else None)


def _scope_label(session: Session, department_id, level) -> str:
    dep = session.get(Department, department_id) if department_id else None
    return (dep.code if dep else "University-wide") + (f" {level}L" if level else "")


def next_version(session: Session, academic_session, semester, department_id, level) -> int:
    q = select(func.max(Timetable.version)).where(Timetable.academic_session == academic_session, Timetable.semester == semester,
                                                  Timetable.department_id.is_(department_id) if department_id is None else Timetable.department_id == department_id,
                                                  Timetable.level.is_(level) if level is None else Timetable.level == level)
    return (session.scalar(q) or 0) + 1


def entries_to_drafts(entries) -> List[EntryDraft]:
    return [EntryDraft(e.course_assignment_id, e.session_no, e.classroom_id, e.day_of_week, to_minutes(e.start_time),
                       to_minutes(e.end_time), e.id) for e in entries]


def chromosome_to_drafts(chrom: Chromosome) -> List[EntryDraft]:
    return [EntryDraft(g.assignment_id, g.session_no, g.room_id, g.day, g.start, g.end) for g in chrom.genes if g.placed]


def _seed_from_timetable(session: Session, data, timetable_id: int) -> Optional[Chromosome]:
    tt = session.get(Timetable, timetable_id)
    if tt is None:
        return None
    placed = {(e.course_assignment_id, e.session_no): e for e in tt.entries}
    genes = []
    for r in data.sessions:
        e = placed.get((r.assignment_id, r.session_no))
        genes.append(make_gene(data, r.index, e.classroom_id, e.day_of_week, to_minutes(e.start_time)) if e
                     else unplaced_gene(data, r.index))
    return Chromosome(genes)


def run_generation(session: Session, actor, params: GenerationParams,
                   progress: Optional[Callable[[dict], None]] = None,
                   should_stop: Optional[Callable[[], bool]] = None) -> GenerationOutcome:
    """Run the full workflow. Nothing is saved unless the whole result can be stored (single transaction)."""
    require(actor, Permission.GENERATE)
    academic_session = validate_academic_session(params.academic_session)
    semester = validate_semester(params.semester)
    level = validate_level(params.level) if params.level else None
    try:
        params.config.validate()
    except ConfigurationError as exc:
        raise ValidationError(str(exc)) from exc
    if params.department_id:
        get_or_404(session, Department, params.department_id, "Department")

    issues = run_prechecks(session, academic_session, semester, params.department_id, level, params.room_ids)
    if errors_only(issues):
        raise PrecheckFailed(issues)

    data = load_scheduling_data(session, academic_session, semester, params.department_id, level, params.room_ids)
    seeds = []
    if params.parent_id and params.seed_from_parent:
        seed = _seed_from_timetable(session, data, params.parent_id)
        if seed is not None:
            seeds.append(seed)
    cfg_row = (session.get(AlgorithmConfiguration, params.configuration_id) if params.configuration_id
               else _store_config(session, actor, "Generation run", params.config))
    try:
        result = run_genetic_algorithm(data, params.config, seeds, progress, should_stop)
    except Exception as exc:  # noqa: BLE001 - recorded, never reported as success
        log.exception("Genetic Algorithm execution failed")
        session.add(GenerationHistory(configuration_id=cfg_row.id if cfg_row else None, status="FAILED",
                                      error_message="The algorithm stopped because of an internal error.",
                                      executed_by=actor.id, parameters=params.config.to_dict()))
        session.commit()
        raise ServiceError("Timetable generation failed. No timetable was saved.") from exc

    drafts = chromosome_to_drafts(result.best)
    conflicts = validate_entries(session, drafts, academic_session, semester, params.department_id, level)
    summary = summarise(conflicts)
    is_valid = summary["total"] == 0
    if result.evaluation.hard_total == 0 and not result.unplaceable and not is_valid:
        log.warning("Independent validator disagrees with the GA about hard violations (%d)", summary["total"])
    status = "VALIDATED" if is_valid else "GENERATED"
    version = next_version(session, academic_session, semester, params.department_id, level)
    name = params.name.strip() or (f"{academic_session} {semester.title()} Semester - "
                                   f"{_scope_label(session, params.department_id, level)} v{version}")
    try:
        with session.begin_nested():
            tt = Timetable(name=name, academic_session=academic_session, semester=semester, department_id=params.department_id,
                           level=level, version=version, parent_id=params.parent_id, status="DRAFT",
                           fitness_score=result.evaluation.fitness, generation_number=result.best_generation,
                           hard_violations=summary["total"], soft_penalty=result.evaluation.soft_weighted,
                           is_valid=is_valid, created_by=actor.id,
                           validation_summary={"independent": summary, "ga_hard_violations": result.evaluation.hard_total,
                                               "unplaced_sessions": result.unplaceable})
            session.add(tt)
            session.flush()
            for g in result.best.genes:
                if g.placed:
                    session.add(TimetableEntry(timetable_id=tt.id, course_assignment_id=g.assignment_id, session_no=g.session_no,
                                               classroom_id=g.room_id, day_of_week=g.day, start_time=from_minutes(g.start),
                                               end_time=from_minutes(g.end),
                                               generation_metadata={"best_generation": result.best_generation}))
            tt.status = status
            hist = GenerationHistory(
                timetable_id=tt.id, configuration_id=cfg_row.id if cfg_row else None, initial_fitness=result.initial_fitness,
                final_fitness=result.evaluation.fitness, generations=result.generations_run, best_generation=result.best_generation,
                execution_seconds=result.elapsed_seconds, hard_violations=summary["total"],
                soft_penalty=result.evaluation.soft_weighted, status="INTERRUPTED" if result.interrupted else "COMPLETED",
                termination_reason=result.termination_reason, fitness_progress=[
                    {k: round(v, 6) if isinstance(v, float) else v for k, v in row.items()} for row in result.history],
                constraint_breakdown=result.evaluation.breakdown(), parameters=params.config.to_dict(), executed_by=actor.id)
            session.add(hist)
            session.add(TimetableAudit(timetable_id=tt.id, action="GENERATED", actor_id=actor.id,
                                       details=f"Version {version}; independent validation: {summary['total']} hard violations"))
            session.flush()
        session.commit()
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        log.exception("Saving generated timetable failed")
        raise ServiceError("The timetable could not be saved. No partial timetable was stored.") from exc
    return GenerationOutcome(tt.id, hist.id, result, conflicts, is_valid, status, issues)


def list_generation_history(session: Session, actor, limit: int = 50) -> List[GenerationHistory]:
    require(actor, Permission.VIEW_HISTORY)
    return list(session.scalars(select(GenerationHistory).order_by(GenerationHistory.executed_at.desc(),
                                                                   GenerationHistory.id.desc()).limit(limit)))
