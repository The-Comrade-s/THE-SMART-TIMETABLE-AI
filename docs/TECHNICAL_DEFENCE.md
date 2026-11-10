# Technical Document for Project Defence

## 1. System design

### 1.1 Architecture
Presentation (Streamlit pages in `views/`, reusable components in `ui/`) calls the service layer (`services/`, `auth/`, `exports/`). Services hold all business rules, permission checks and database queries. The Genetic Algorithm (`algorithm/`) works on an in-memory snapshot of the data and never touches the database while evolving; the independent validator (`validation/timetable_validator.py`) re-reads the reference data from the database and shares no constraint code with the algorithm.

### 1.2 Use cases
| Actor | Use cases |
|---|---|
| Super admin | Everything below, plus manage users, departments and teaching hours, save algorithm configurations, approve, publish and archive timetables |
| Admin | Manage lecturers, courses, classrooms, student groups, assignments and availability; generate and re-optimise timetables; view history, validate, compare and export |
| Viewer | View and export published timetables only |

### 1.3 Database relationships
- A department has many lecturers, courses and student groups.
- A course assignment links one course, one lecturer and one student group for an academic session and semester (unique on that combination). Team teaching is two assignments.
- A course has one or more weekly sessions (`course_sessions`), each with its own duration.
- Lecturers and classrooms have many availability periods (AVAILABLE, PREFERRED or UNAVAILABLE).
- A timetable (one version of a scope) has many entries; each entry references an assignment, a session number and a classroom. Entries, assignments and classrooms use `ON DELETE RESTRICT`, so records used by a timetable cannot be deleted; they are deactivated instead.
- A timetable has an audit trail and zero or more generation-history rows that reference an algorithm configuration.

### 1.4 Workflow
Define teaching hours and data, then assign courses; run pre-generation checks; generate (background thread, live progress); the best chromosome is validated independently; the timetable is saved in one transaction as VALIDATED (no hard violations) or GENERATED (violations remain, flagged invalid); an authorised admin approves (re-validated at that moment) and then publishes; revisions create a new version; publishing over an existing published version requires an explicit replacement and archives, never deletes, the old one.

## 2. Genetic Algorithm

### 2.1 Chromosome
Each required weekly session of each active course assignment is one gene `(assignment, session no., lecturer, group, room, day, start, end)`. A course needing 3 hours split 2+1 contributes two genes. The chromosome is a fixed-length list indexed by session, so every individual always contains every required session; a session that cannot be placed at all is stored as an unplaced gene and counted as a hard violation (H10), with the reason recorded.

### 2.2 Time model
Active time slots define the teaching days, working hours (H8) and the grid of allowed start times. Lecturer allowed time is (AVAILABLE and PREFERRED periods) minus UNAVAILABLE periods; a lecturer with no positive period cannot be scheduled (blocked by the pre-checks). A room with no positive periods is treated as available during all teaching hours.

### 2.3 Initial population
Every session first gets a domain of feasible `(room, day, start)` options that satisfy H4 to H9 individually. A share of the population (`heuristic_ratio`, default 0.5) is built greedily: sessions are ordered most-constrained first (fewest options, longest, largest group) and each takes a random option that does not clash with sessions already placed. The rest is constrained-random: each gene is drawn from its own domain.

### 2.4 Fitness
`Fitness(T) = 1 / (1 + WH x H + WS x S)` with
`H = sum over i of w_i x h_i` (h_i is the number of violations of hard constraint i) and `S = sum over j of v_j x s_j` (s_j is the raw penalty of soft constraint j, in hours or session counts). The defaults are `WH = 1000`, `WS = 1`, all weights 1, and configuration validation requires `WH >= 10 x WS`.
Because a soft penalty can in principle grow larger than `WH`, comparison between individuals uses the pair (hard-violation count, fitness): fewer hard violations always wins, then higher fitness. An invalid timetable is therefore never equivalent to, or better than, a valid one. Evaluation is deterministic and returns a full breakdown (10 hard counts and 7 soft penalties).

### 2.5 Constraints
Overlaps use half-open intervals, so 08:00-10:00 and 09:00-11:00 conflict while 08:00-09:00 and 09:00-10:00 do not. Soft constraints: S1 sessions outside a lecturer's preferred periods (if any are declared); S2 deviation of daily teaching hours from their mean; S3 idle hours between a group's sessions; S4 lecturer idle time beyond one hour; S5 back-to-back chains longer than four hours; S6 unused seats as a fraction of room capacity; S7 hours above four per lecturer per day or six per group per day.

### 2.6 Selection, crossover, mutation, elitism
- Tournament selection (configurable size) on the ranking above; the second parent is redrawn if it duplicates the first.
- Crossover groups genes by course assignment; for each assignment the child takes all its sessions from one parent. Required sessions and assignment relationships are preserved by construction, so no repair is needed.
- Mutation changes only a gene's placement, always to another option from that session's feasible domain: move, room change, time shift, or conflict repair (re-place at a clash-free option). Genes inherited as conflicting mutate with 4 times the base probability (targeted mutation).
- Elitism keeps the best `elite_size` individuals unchanged; offspring fill the rest so the population size is constant. If the search stagnates for half the stagnation threshold, the worst unprotected individuals are replaced by fresh heuristic ones (diversity injection).

### 2.7 Termination
Maximum generations; target fitness (only counted when there are no hard violations); optional stop at the first conflict-free timetable; stagnation threshold; user stop. If no valid timetable is found, the best one is returned with its violations and is never labelled conflict-free.

### 2.8 Why these operators suit timetabling
Timetables are highly structured: swapping arbitrary genes would destroy per-course structure. Block crossover keeps each course's sessions together, domain-restricted mutation keeps static constraints satisfied so the search budget is spent on the interaction constraints (clashes), and targeted mutation focuses on the genes that are actually in conflict. Elitism guarantees the best solution never regresses (checked by a test).

## 3. System evaluation

### 3.1 Methodology
`python -m scripts.benchmark` creates a temporary database, applies the migrations, loads one of the DEMONSTRATION datasets from `services/demo_data.py`, and runs the real algorithm for seeds 1 to 5 under different parameters. The report below is the unmodified output of that script. Test datasets are synthetic; they are not real institutional data, and no claim is made about real timetables.

### 3.2 Measured results (actual execution)
# Genetic Algorithm benchmark results

Generated by `python -m scripts.benchmark` on 2026-11-09 (Python 3.12.3, Linux x86_64). All figures are measured; datasets are the DEMONSTRATION data from `services/demo_data.py`, not real institutional data. Each row aggregates 5 seeds (1 to 5). Hard violations are counted by the Genetic Algorithm's own evaluator; the application additionally validates every saved timetable with an independent validator.

## 1. Effect of dataset size

Population 40, up to 150 generations, mutation 0.02, crossover 0.85, elitism 2, stagnation 50.

| Dataset | Sessions | Runs conflict-free | Initial best hard violations (mean) | Final hard violations (mean) | Initial soft penalty (mean) | Final soft penalty (mean) | Generations (mean) | Time s (mean) |
|---|---|---|---|---|---|---|---|---|
| small | 12 | 5/5 | 0.0 (sd 0.0) | 0.0 (sd 0.0) | 23.7 (sd 2.9) | 16.6 (sd 1.0) | 91 (sd 21) | 0.12 (sd 0.03) |
| medium | 52 | 5/5 | 0.0 (sd 0.0) | 0.0 (sd 0.0) | 104.2 (sd 3.8) | 55.3 (sd 1.5) | 150 (sd 0) | 1.51 (sd 0.04) |
| large | 151 | 5/5 | 0.0 (sd 0.0) | 0.0 (sd 0.0) | 326.8 (sd 7.8) | 263.0 (sd 3.1) | 150 (sd 0) | 4.73 (sd 0.14) |
| tight | 110 | 5/5 | 0.0 (sd 0.0) | 0.0 (sd 0.0) | 314.0 (sd 6.6) | 301.1 (sd 8.7) | 99 (sd 42) | 2.20 (sd 0.92) |

## 2. Parameter sensitivity (medium dataset)

One parameter varied at a time from: population 40, 100 generations, mutation 0.02, crossover 0.85, elitism 2.

| Parameter | Value | Runs conflict-free | Final hard (mean) | Final soft penalty (mean) | Time s (mean) |
|---|---|---|---|---|---|
| population_size | 10 | 5/5 | 0.0 (sd 0.0) | 77.2 (sd 6.1) | 0.19 (sd 0.01) |
| population_size | 20 | 5/5 | 0.0 (sd 0.0) | 66.3 (sd 3.3) | 0.46 (sd 0.02) |
| population_size | 40 | 5/5 | 0.0 (sd 0.0) | 58.8 (sd 3.5) | 1.03 (sd 0.03) |
| population_size | 80 | 5/5 | 0.0 (sd 0.0) | 54.6 (sd 1.9) | 2.18 (sd 0.05) |
| mutation_rate | 0.0 | 5/5 | 0.0 (sd 0.0) | 98.6 (sd 6.2) | 0.24 (sd 0.02) |
| mutation_rate | 0.005 | 5/5 | 0.0 (sd 0.0) | 66.3 (sd 4.4) | 0.60 (sd 0.03) |
| mutation_rate | 0.02 | 5/5 | 0.0 (sd 0.0) | 58.8 (sd 3.5) | 1.02 (sd 0.03) |
| mutation_rate | 0.05 | 5/5 | 0.0 (sd 0.0) | 62.2 (sd 3.0) | 1.17 (sd 0.05) |
| mutation_rate | 0.1 | 5/5 | 0.0 (sd 0.0) | 76.6 (sd 7.9) | 1.38 (sd 0.05) |
| crossover_rate | 0.0 | 5/5 | 0.0 (sd 0.0) | 60.5 (sd 4.3) | 0.71 (sd 0.02) |
| crossover_rate | 0.5 | 5/5 | 0.0 (sd 0.0) | 60.1 (sd 2.5) | 0.86 (sd 0.02) |
| crossover_rate | 0.85 | 5/5 | 0.0 (sd 0.0) | 58.8 (sd 3.5) | 1.01 (sd 0.02) |
| crossover_rate | 1.0 | 5/5 | 0.0 (sd 0.0) | 58.9 (sd 6.0) | 1.04 (sd 0.02) |
| elite_size | 0 | 5/5 | 0.0 (sd 0.0) | 64.2 (sd 4.4) | 1.12 (sd 0.07) |
| elite_size | 2 | 5/5 | 0.0 (sd 0.0) | 58.8 (sd 3.5) | 1.10 (sd 0.06) |
| elite_size | 8 | 5/5 | 0.0 (sd 0.0) | 58.7 (sd 2.6) | 0.82 (sd 0.03) |
| max_generations | 10 | 5/5 | 0.0 (sd 0.0) | 97.5 (sd 8.6) | 0.14 (sd 0.01) |
| max_generations | 50 | 5/5 | 0.0 (sd 0.0) | 68.4 (sd 5.0) | 0.55 (sd 0.04) |
| max_generations | 100 | 5/5 | 0.0 (sd 0.0) | 58.8 (sd 3.5) | 1.03 (sd 0.01) |
| max_generations | 200 | 5/5 | 0.0 (sd 0.0) | 52.9 (sd 2.4) | 1.96 (sd 0.08) |

## 3. Conflict resolution from a purely random initial population

The heuristic initialiser alone already produces conflict-free timetables on these demonstration datasets, so section 1 mostly measures soft-constraint optimisation. To measure the evolutionary search itself, the heuristic share of the initial population is set to 0 (constrained-random placement only). Population 60, up to 300 generations, stagnation 300.

| Dataset | Sessions | Initial best hard violations (mean) | Final hard violations (mean) | Runs conflict-free | Generations to first conflict-free (mean, conflict-free runs) | Time s (mean) |
|---|---|---|---|---|---|---|
| medium | 52 | 10.6 (sd 1.2) | 0.0 (sd 0.0) | 5/5 | 10.4 (sd 2.2) | 0.21 (sd 0.04) |
| large | 151 | 63.0 (sd 3.2) | 0.0 (sd 0.0) | 5/5 | 44.0 (sd 4.1) | 2.51 (sd 0.18) |
| tight | 110 | 91.2 (sd 3.2) | 0.0 (sd 0.0) | 5/5 | 127.4 (sd 37.7) | 4.79 (sd 1.34) |

## 4. Reproducibility

Two runs with seed 99 produced identical best chromosomes: **True** (fitness 0.01617142 and 0.01617142).


### 3.3 Reading the results honestly
- On these demonstration datasets the heuristic initialiser alone already yields conflict-free timetables (section 1: initial hard violations 0), so the gains in section 1 are in soft-constraint penalties (for example the medium dataset falls from about 104 to about 55).
- Section 3 removes the heuristic start. From a random start the algorithm eliminated all hard violations in every run on all three datasets, which is the measurement that shows the evolutionary search resolving conflicts itself.
- All 5 seeds were conflict-free on every dataset; this shows the demo data is feasible, not that every real dataset will be. Real data with tight resources may produce timetables with remaining violations; the application reports those transparently.
- Timings are for a single machine and a single run configuration and will differ elsewhere. The independent validator uses pairwise comparison, which was measured only up to 151 sessions (about 0.04 s).
- Statistical claims are limited to 5 seeds per row.

### 3.4 Automated test evidence
See `docs/AUDIT_REPORT.md` for the test counts and coverage that were measured when this document was produced.
