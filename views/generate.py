from __future__ import annotations

from datetime import date

import streamlit as st
from sqlalchemy import select

from algorithm import GAConfig
from algorithm.configuration import ConfigurationError, HARD_CODES, HARD_LABELS, SOFT_CODES, SOFT_LABELS
from auth.permissions import Permission, has_permission
from database import session_scope
from database.enums import LEVELS, SEMESTERS
from database.models import GenerationHistory, Timetable
from services import department_service as dsvc
from services import generation_service as gsvc
from services import job_runner
from services.common import ServiceError
from ui.charts import progress_chart
from ui.components import empty_state, metric_card, notice, page_header, section_head
from ui.crud import attempt
from ui.navigation import go
from ui.tables import paginated_table
from validation.prechecks import ERROR


def _default_session() -> str:
    y = date.today().year if date.today().month >= 8 else date.today().year - 1
    return f"{y}/{y + 1}"


def render() -> None:
    user = st.session_state["user"]
    page_header("Generate timetable", "Configure and run the Genetic Algorithm. Results are validated independently before they are saved.")
    with session_scope() as s:
        deps = dsvc.list_departments(s, user)
        saved = gsvc.list_configurations(s, user)
        existing = s.scalars(select(Timetable).order_by(Timetable.id.desc()).limit(100)).all()
    parent = st.session_state.pop("reopt_parent", None)
    if parent:
        p = next((t for t in existing if t.id == parent), None)
        if p:
            st.session_state.update(gen_sess=p.academic_session, gen_sem=p.semester, gen_parent=p.id,
                                    gen_dep=(next((f"{d.code} - {d.name}" for d in deps if d.id == p.department_id), "University-wide")),
                                    gen_lvl=p.level or "All")
    job = job_runner.get_job(st.session_state.get("gen_job"))
    running = job is not None and job.status == "RUNNING"

    section_head("Scope")
    a, b, c, d = st.columns(4)
    sess = a.text_input("Academic session", st.session_state.get("gen_sess", _default_session()), key="gen_sess", disabled=running)
    sem = b.selectbox("Semester", SEMESTERS, format_func=str.title, key="gen_sem", disabled=running)
    dep_map = {"University-wide": None, **{f"{x.code} - {x.name}": x.id for x in deps}}
    dep = c.selectbox("Department scope", list(dep_map), key="gen_dep", disabled=running)
    lvl = d.selectbox("Academic level", ["All"] + list(LEVELS), key="gen_lvl", disabled=running)

    section_head("Algorithm parameters")
    cfg_map = {"Custom parameters": None, **{r.name: r for r in saved}}
    chosen = st.selectbox("Saved configuration", list(cfg_map), key="gen_cfg", disabled=running)
    base = gsvc.config_from_row(cfg_map[chosen]) if cfg_map[chosen] else GAConfig()
    ver = st.session_state.get("gen_cfg_applied")
    if ver != chosen:
        for k, v in [("gen_pop", base.population_size), ("gen_gens", base.max_generations), ("gen_mut", base.mutation_rate),
                     ("gen_cross", base.crossover_rate), ("gen_elite", base.elite_size), ("gen_tour", base.tournament_size),
                     ("gen_target", base.target_fitness), ("gen_stag", base.stagnation_threshold), ("gen_stop0", base.stop_on_zero_hard)]:
            st.session_state[k] = v
        st.session_state["gen_cfg_applied"] = chosen
    r1 = st.columns(4)
    pop = r1[0].number_input("Population size", 4, 2000, key="gen_pop", disabled=running)
    gens = r1[1].number_input("Maximum generations", 1, 20000, key="gen_gens", disabled=running)
    mut = r1[2].number_input("Mutation rate", 0.0, 1.0, step=0.005, format="%.3f", key="gen_mut", disabled=running)
    cross = r1[3].number_input("Crossover rate", 0.0, 1.0, step=0.05, format="%.2f", key="gen_cross", disabled=running)
    r2 = st.columns(4)
    elite = r2[0].number_input("Elitism count", 0, 1000, key="gen_elite", disabled=running)
    tour = r2[1].number_input("Tournament size", 2, 1000, key="gen_tour", disabled=running)
    target = r2[2].number_input("Target fitness", 0.0001, 1.0, step=0.01, format="%.4f", key="gen_target", disabled=running)
    stag = r2[3].number_input("Stagnation threshold (generations)", 1, 10000, key="gen_stag", disabled=running)
    stop0 = st.checkbox("Stop as soon as a conflict-free timetable is found", key="gen_stop0", disabled=running,
                        help="When off, the algorithm keeps optimising soft constraints until stagnation or the generation limit.")
    with st.expander("Constraint weights and fitness factors"):
        st.caption("Fitness = 1 / (1 + WH x H + WS x S). Hard weights must be positive; the hard factor must be at least ten times the soft factor.")
        f1, f2 = st.columns(2)
        hf = f1.number_input("Hard factor (WH)", 1.0, 1e7, base.hard_factor, key="gen_hf", disabled=running)
        sf = f2.number_input("Soft factor (WS)", 0.0001, 1e6, base.soft_factor, key="gen_sf", disabled=running)
        hw = {c: st.number_input(f"{c}: {HARD_LABELS[c]}", 0.0, 1e4, float(base.hard_weights[c]), key=f"gen_hw_{c}", disabled=running) for c in HARD_CODES}
        sw = {c: st.number_input(f"{c}: {SOFT_LABELS[c]}", 0.0, 1e4, float(base.soft_weights[c]), key=f"gen_sw_{c}", disabled=running) for c in SOFT_CODES}
    seed_raw = st.text_input("Random seed (optional, for reproducible runs)", key="gen_seed", disabled=running)
    cfg = GAConfig(int(pop), int(gens), float(mut), float(cross), int(elite), int(tour), int(stag), float(target), bool(stop0),
                   float(hf), float(sf), 0.5, hw, sw, int(seed_raw) if seed_raw.strip().isdigit() else None)

    section_head("Re-optimisation")
    parent_map = {"Start from scratch": None, **{f"{t.name} [{t.status.title()}]": t.id for t in existing}}
    pref = st.session_state.pop("gen_parent", None)
    values = list(parent_map.values())
    if pref is not None and pref in values:
        st.session_state["gen_parent_lbl"] = list(parent_map)[values.index(pref)]
    parent_label = st.selectbox("Improve an existing timetable (creates a new version)", list(parent_map), key="gen_parent_lbl", disabled=running)
    parent_id = parent_map[parent_label]

    name = st.text_input("Timetable name (optional)", key="gen_name", disabled=running)
    dep_id, lvl_v = dep_map[dep], None if lvl == "All" else lvl
    b1, b2, b3 = st.columns([1, 1, 1])
    check = b1.button("Check data", key="gen_check", disabled=running, width="stretch")
    go_btn = b2.button("Generate timetable", key="gen_go", type="primary", disabled=running, width="stretch")
    save_cfg = b3.button("Save configuration", key="gen_save", disabled=running or not has_permission(user, Permission.CONFIGURE_ALGORITHM), width="stretch")

    if save_cfg:
        cname = f"Config {pop}x{gens}"
        attempt(lambda s: gsvc.save_configuration(s, user, cname, cfg), f"Configuration '{cname}' saved.")
    if check or go_btn:
        try:
            cfg.validate()
            with session_scope() as s:
                issues = gsvc.precheck(s, user, sess, sem, dep_id, lvl_v)
        except (ConfigurationError, ServiceError) as exc:
            notice("error", str(exc))
            issues = None
        if issues is not None:
            errors = [i for i in issues if i.severity == ERROR]
            for i in issues:
                notice("error" if i.severity == ERROR else "warning", i.message, i.code.replace("_", " ").title())
            if not issues:
                notice("success", "The scheduling data passed all pre-generation checks.", "Ready")
            if go_btn and not errors:
                params = gsvc.GenerationParams(sess, sem, cfg, dep_id, lvl_v, name, parent_id)
                st.session_state["gen_job"] = job_runner.start_job(user, params).id
                st.rerun()
            elif go_btn:
                notice("error", "Generation was not started because the data is incomplete.", "Blocked")

    job = job_runner.get_job(st.session_state.get("gen_job"))
    if job is not None:
        section_head("Generation progress")
        _progress(job.id)


@st.fragment(run_every=1.0)
def _progress(job_id: str) -> None:
    job = job_runner.get_job(job_id)
    if job is None:
        return
    row = job.latest
    if row:
        cols = st.columns(4)
        vals = [("Generation", f"{row['generation']} of {row['max_generations']}"), ("Best fitness", f"{row['best_fitness']:.6f}"),
                ("Hard violations", str(row["hard_violations"])), ("Soft penalty", f"{row['soft_penalty']:.2f}")]
        for col, (l, v) in zip(cols, vals):
            with col:
                metric_card(l, v)
        cols = st.columns(3)
        for col, (l, v) in zip(cols, [("Population size", str(row["population_size"])), ("Elapsed", f"{row['elapsed']:.1f} s"), ("Status", job.status.title())]):
            with col:
                metric_card(l, v)
        st.progress(min(1.0, row["generation"] / max(1, row["max_generations"])))
        if len(job.history) > 1:
            st.plotly_chart(progress_chart(list(job.history)), width="stretch", config={"displayModeBar": False})
    if job.status == "RUNNING":
        st.caption("The generation is running in the background. This panel refreshes automatically.")
        if st.button("Stop generation", key=f"stop_{job_id}"):
            job.stop.set()
        return
    if st.session_state.get("_job_seen") != (job_id, job.status):
        st.session_state["_job_seen"] = (job_id, job.status)
        st.rerun()
    _finished(job)


def _finished(job) -> None:
    user = st.session_state["user"]
    if job.status == "FAILED":
        notice("error", job.error or "Generation failed. No timetable was saved.", "Generation failed")
        for i in job.issues:
            notice("error" if i.severity == ERROR else "warning", i.message, i.code.replace("_", " ").title())
        return
    with session_scope() as s:
        tt = s.get(Timetable, job.timetable_id)
        h = s.scalar(select(GenerationHistory).where(GenerationHistory.timetable_id == job.timetable_id).order_by(GenerationHistory.id.desc()))
        scope = tt.department.name if tt.department else "University-wide"
    if tt.is_valid:
        notice("success", "Independent validation confirms that all mandatory constraints are satisfied.", "Valid timetable")
    else:
        notice("warning", f"The best timetable found still has {tt.hard_violations} hard constraint violation(s). It is saved for review but "
                          "cannot be approved or published. Adjust the parameters or the data and run again.", "Invalid timetable")
    section_head("Generation summary")
    imp = ((h.final_fitness - h.initial_fitness) / h.initial_fitness * 100) if h.initial_fitness else 0
    paginated_table("gen_sum", ["Item", "Value"], [
        ["Timetable", tt.name], ["Academic session", tt.academic_session], ["Semester", tt.semester.title()], ["Department scope", scope],
        ["Generated", tt.generated_at.strftime("%Y-%m-%d %H:%M")], ["Execution time", f"{h.execution_seconds:.2f} s"],
        ["Generations executed", h.generations], ["Final fitness", f"{h.final_fitness:.6f}"],
        ["Initial fitness", f"{h.initial_fitness:.6f}"], ["Improvement", f"{imp:.1f}%"], ["Best generation", h.best_generation],
        ["Termination reason", h.termination_reason], ["Hard violations (independent)", tt.hard_violations],
        ["Soft penalty", f"{tt.soft_penalty:.2f}"], ["Status", tt.status.title()]], page_size=20)
    unplaced = (tt.validation_summary or {}).get("unplaced_sessions") or []
    if unplaced:
        section_head("Sessions that could not be placed")
        paginated_table("gen_unp", ["Course", "Session", "Reason"], [[u["course"], u["session_no"], u["reason"]] for u in unplaced], page_size=8)
    if st.button("Open this timetable", key=f"open_{job.id}", type="primary"):
        st.session_state["open_timetable"] = tt.id
        go("TIMETABLE")
        st.rerun()
