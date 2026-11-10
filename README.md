# Genetic Algorithm-Based Smart Timetable System

## 1. Project title
Design and Implementation of a Genetic Algorithm-Based Smart Timetable System.

## 2. Overview
A web application (Streamlit + PostgreSQL) that stores institutional data (departments, lecturers, courses, classrooms, student groups, course assignments, availability) and automatically generates university lecture timetables with a Genetic Algorithm. Every generated timetable is checked by an independent validator before it can be approved or published, and can be viewed, compared and exported to PDF and Excel.

## 3. Problem statement
Building a timetable by hand means satisfying many interacting rules at once (no double-booked lecturers, rooms or student groups; rooms must fit the class and the course type; lecturers and rooms have limited availability). Manual scheduling is slow and error-prone, and revisions often break something that was already correct.

## 4. Objectives
1. Model the institution's scheduling data in a normalised relational database.
2. Generate timetables that satisfy all mandatory (hard) constraints and optimise quality (soft) constraints with a Genetic Algorithm.
3. Verify every result with a validator that is independent of the optimiser.
4. Support role-based access, a review and publication workflow with preserved history, and professional PDF and Excel output.

## 5. Technologies
Python 3.12, Streamlit, PostgreSQL, SQLAlchemy 2, Alembic, Argon2 (argon2-cffi), Plotly, ReportLab, OpenPyXL, pytest.
Pandas was listed in the original brief but nothing in the application needs it, so it is not a dependency.

## 6. Architecture
```
app.py                entry point: theme, login gate, sidebar, page routing
config/               environment-based settings
database/             engine, sessions, health check, enums, models/ (18 tables)
migrations/           Alembic environment and version 0001
auth/                 password hashing, sessions, lockout, permissions
services/             business logic and all database queries (pages never query directly)
algorithm/            Genetic Algorithm engine (no database access while evolving)
validation/           field rules, pre-generation checks, independent timetable validator
exports/              PDF (ReportLab) and Excel (OpenPyXL), including the examination dataset
importers/            PDF extraction (NOUN 2026_2 draft examination timetable) and its validation report
data/noun/            the source PDF used for import testing
ui/                   theme, components, tables, charts, timetable grid, navigation
views/                one module per sidebar page
scripts/              create_admin, seed_demo, healthcheck, benchmark
tests/                pytest suite
docs/                 technical document, audit report, measured benchmark results
```
Permissions are enforced inside every service function (`auth.permissions.require`), not only by hiding buttons.

## 7. Database
18 tables: departments, lecturers, courses, course_sessions, classrooms, student_groups, course_assignments, lecturer_availability, room_availability, time_slots, timetables, timetable_entries, timetable_audit, algorithm_configurations, generation_history, users, user_sessions, app_settings.
Integrity: primary and foreign keys, unique constraints (department code, staff ID, email, course code, room name per building, group name per session, assignment identity), CHECK constraints (capacity > 0, start < end, valid levels, statuses and roles, algorithm parameter ranges), `ON DELETE RESTRICT` on everything a timetable references, so history cannot be destroyed. Records are deactivated, not deleted.

## 8. Genetic Algorithm (summary)
- Chromosome: one gene per required weekly session (room, day, start); gene `i` always describes session `i`, so crossover and mutation cannot lose a session.
- Initial population: heuristic placement (most constrained sessions first, clash-free where possible) mixed with constrained-random placement.
- Fitness: `Fitness(T) = 1 / (1 + WH x H + WS x S)`; `H` is the weighted count of hard violations and `S` the weighted soft penalty. Ranking compares hard-violation count first, then fitness, so an invalid timetable can never outrank a valid one.
- Selection: tournament. Crossover: assignment-block uniform crossover. Mutation: move / room change / time shift / conflict repair, boosted on genes inherited as conflicting. Elitism plus diversity injection on stagnation.
- Termination: maximum generations, target fitness, zero hard violations (optional), stagnation, user stop.
Full explanation: `docs/TECHNICAL_DEFENCE.md`.

## 9. Constraints
Hard: H1 lecturer clash, H2 classroom clash, H3 student-group clash (all interval based, partial overlaps detected), H4 lecturer availability, H5 classroom availability, H6 room capacity, H7 room type, H8 working hours (active time slots), H9 session duration, H10 session completeness.
Soft: S1 lecturer preferred periods, S2 weekly distribution, S3 student gaps, S4 lecturer gaps, S5 consecutive-lecture limit, S6 classroom utilisation, S7 daily workload balance. All weights are configurable.

## 10. Installation
```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # add requirements-dev.txt for the full test suite
```

## 11. Environment configuration
```
cp .env.example .env        # then edit; .env is git-ignored
```
Set `DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@HOST:5432/DATABASE`, and `INSTITUTION_NAME`. Never commit `.env`.

## 12. Database setup
```
createdb timetable                      # or use your hosting provider's console
alembic upgrade head                    # apply migrations
alembic current                         # show the applied revision
alembic revision --autogenerate -m "describe change"   # create a new migration after model changes
python -m scripts.healthcheck           # verifies connectivity and that migrations were applied
```
The application never creates tables on startup.

## 13. Running
```
streamlit run app.py
```

## 14. Administrator setup
No public registration exists. Create the first super admin from the command line (works only while none exists):
```
python -m scripts.create_admin          # prompts for name, email and password (hidden input)
```
For non-interactive deployments set `ADMIN_NAME`, `ADMIN_EMAIL`, `ADMIN_PASSWORD` for that single command and then remove them. Further users are created by the super admin in SETTINGS, USERS. Define teaching hours in SETTINGS, INSTITUTION before generating.
Optional demonstration data (clearly marked DEMO, refused when `APP_ENV=production`):
```
python -m scripts.seed_demo --confirm --size small      # small | medium | large | tight
```

## 15. Testing
```
pip install -r requirements-dev.txt
python -m pytest -q                      # SQLite (default, isolated database per test)
TEST_DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@localhost:5432/tt_test python -m pytest -q   # real PostgreSQL (the test schema is dropped and recreated)
python -m pytest -q --cov=.              # coverage
python -m scripts.benchmark              # regenerates docs/benchmark_results.md from real runs
```

## 16. Deployment
Any host that runs Python and offers PostgreSQL works (for example Render, Railway or a VPS).
1. Provision PostgreSQL and set `DATABASE_URL`, `APP_ENV=production`, `INSTITUTION_NAME` as environment variables (never in source).
2. Build command: `pip install -r requirements.txt`. Pre-start command: `alembic upgrade head`.
3. Start command: `streamlit run app.py --server.port $PORT --server.address 0.0.0.0`.
4. Create the first admin once with `python -m scripts.create_admin`.
5. Health checks: `/_stcore/health` (web process) and `python -m scripts.healthcheck` (database and migrations).
6. Serve behind HTTPS. A `Dockerfile` is included but was not built or tested.
Generation runs in a background thread inside the Streamlit process; use a single application instance, and note that a restart interrupts a run in progress.

## Dataset import: NOUN 2026_2 E-EXAM draft timetable (test dataset)
The real NOUN draft examination timetable PDF is bundled in `data/noun/`. As a super admin or admin open SETTINGS, DATASETS:
1. Under "Import the examination timetable PDF" pick the bundled file (or upload a PDF) and press "Start extraction". The page shows progress, statistics, the records flagged for manual review and a preview.
2. Press "Confirm import". Re-importing the same PDF adds nothing (the file's SHA-256 identifies it).
3. Select the dataset and "View dataset" for the COURSES, TIMETABLE, PARALLEL AND CONFLICTS, VALIDATION, LECTURE TEST and EXPORT tabs. "Revalidate dataset" re-checks the stored records. Only a super admin can "Remove test dataset".
The examination records live in their own tables (`datasets`, `exam_days`, `exam_sessions`, `exam_entries`, `dataset_members`; migration 0002). Nothing in the PDF describes lecturers, rooms, student groups or lecture requirements, so the LECTURE TEST tab builds a clearly marked SYNTHETIC lecture dataset from the PDF's computing course codes and runs the real Genetic Algorithm on it (using only the synthetic rooms). The examination schedule is never modified.
Command-line equivalent that also regenerates the measured report: `python -m scripts.noun_report` (writes `docs/NOUN_IMPORT_REPORT.md`).

## Known limitations
See `docs/AUDIT_REPORT.md` for the full, current list.
