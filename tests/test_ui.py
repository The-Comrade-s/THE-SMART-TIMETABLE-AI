import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def app_env(db, monkeypatch):
    import streamlit as st
    from config import settings
    monkeypatch.setenv("DATABASE_URL", db)
    settings.get_settings.cache_clear()
    st.cache_data.clear()
    yield db
    settings.get_settings.cache_clear()


def _run():
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()


def _login(at, email, pw="StrongPass123"):
    at.text_input(key="login_email").input(email)
    at.text_input(key="login_password").input(pw)
    at.button[0].click().run() if False else None
    [b for b in at.button if b.label == "Sign in"][0].click().run()
    return at


def test_unauthenticated_shows_login_not_pages(app_env, super_admin):
    at = _run()
    assert not at.exception
    assert any("Sign in" in b.label for b in at.button)
    assert not any(b.key == "nav_DASHBOARD" for b in at.button)


def test_invalid_login_rejected(app_env, super_admin):
    at = _login(_run(), "super@example.test", "WrongPass999")
    assert "user" not in at.session_state
    assert any("Invalid email or password" in m.value for m in at.markdown)


def test_login_and_every_page_for_super_admin(app_env, demo, super_admin):
    at = _login(_run(), "super@example.test")
    assert not at.exception and at.session_state["user"].role == "SUPER_ADMIN"
    for page in ["DASHBOARD", "DEPARTMENTS", "LECTURERS", "COURSES", "CLASSROOMS", "TIMETABLE", "GENERATE TIMETABLE", "SETTINGS"]:
        [b for b in at.button if b.key == f"nav_{page}"][0].click().run()
        assert not at.exception, (page, [e.value for e in at.exception])
        assert at.session_state["page"] == page


def test_viewer_only_sees_permitted_navigation(app_env, viewer, super_admin):
    at = _login(_run(), "viewer@example.test")
    keys = {b.key for b in at.button if b.key and b.key.startswith("nav_")}
    assert keys == {"nav_DASHBOARD", "nav_TIMETABLE", "nav_SETTINGS"}
    assert not at.exception


def test_theme_persists_across_navigation_after_login(app_env, super_admin):
    at = _login(_run(), "super@example.test")
    [b for b in at.button if b.key == "theme_toggle"][0].click().run()
    assert at.session_state["theme"] == "light"
    [b for b in at.button if b.key == "nav_SETTINGS"][0].click().run()
    assert at.session_state["theme"] == "light" and not at.exception


def test_logout_clears_session(app_env, super_admin):
    at = _login(_run(), "super@example.test")
    [b for b in at.button if b.key == "top_signout"][0].click().run()
    assert "user" not in at.session_state and "auth_token" not in at.session_state
    assert any(b.label == "Sign in" for b in at.button)


def test_generation_page_runs_background_job(app_env, demo, super_admin):
    import time
    at = _login(_run(), "super@example.test")
    [b for b in at.button if b.key == "nav_GENERATE TIMETABLE"][0].click().run()
    at.text_input(key="gen_sess").set_value("2025/2026")
    at.number_input(key="gen_gens").set_value(5)
    at.number_input(key="gen_pop").set_value(10)
    at.number_input(key="gen_elite").set_value(1)
    [b for b in at.button if b.key == "gen_go"][0].click().run()
    assert not at.exception, [e.value for e in at.exception]
    from services import job_runner
    job = job_runner.get_job(at.session_state["gen_job"])
    for _ in range(100):
        if job.status != "RUNNING":
            break
        time.sleep(0.1)
    assert job.status == "COMPLETED", job.error
    at.run()
    assert not at.exception


@pytest.fixture()
def with_timetable(app_env, demo, super_admin, admin):
    from algorithm import GAConfig
    from services import generation_service as gs
    out = gs.run_generation(demo, admin, gs.GenerationParams("2025/2026", "FIRST", GAConfig(population_size=8, max_generations=3, seed=1)))
    demo.commit()
    return out.timetable_id


def test_timetable_page_all_view_modes_and_tabs(with_timetable):
    at = _login(_run(), "super@example.test")
    [b for b in at.button if b.key == "nav_TIMETABLE"][0].click().run()
    assert not at.exception, [e.value for e in at.exception]
    for mode in ["Weekly view", "Department view", "Student group view", "Lecturer view", "Classroom view", "Daily view"]:
        at.selectbox(key="tt_mode").set_value(mode).run()
        assert not at.exception, (mode, [e.value for e in at.exception])
        html = " ".join(m.value for m in at.markdown)
        assert "tt-block" in html, mode
    at.selectbox(key="ex_kind").set_value("Lecturer timetable").run()
    assert not at.exception


def test_timetable_page_for_viewer_sees_only_published(with_timetable, viewer, super_admin):
    from database import session_scope
    from services import timetable_service as tts
    with session_scope() as s:
        tts.approve(s, super_admin, with_timetable)
    at = _login(_run(), "viewer@example.test")
    [b for b in at.button if b.key == "nav_TIMETABLE"][0].click().run()
    assert any("No timetables found" in m.value for m in at.markdown)       # approved but not published: invisible
    with session_scope() as s:
        tts.publish(s, super_admin, with_timetable)
    at.run()
    [b for b in at.button if b.key == "nav_TIMETABLE"][0].click().run()
    assert not at.exception and "tt-block" in " ".join(m.value for m in at.markdown)
    assert [t.label for t in at.tabs] == ["VIEW", "EXPORT"]                    # no admin tabs for viewers


def test_settings_tabs_per_role(app_env, super_admin, admin):
    at = _login(_run(), "super@example.test")
    [b for b in at.button if b.key == "nav_SETTINGS"][0].click().run()
    assert not at.exception and {"USERS", "INSTITUTION", "SECURITY"} <= {t.label for t in at.tabs}
    at2 = _login(_run(), "admin@example.test")
    [b for b in at2.button if b.key == "nav_SETTINGS"][0].click().run()
    assert not at2.exception and "USERS" not in {t.label for t in at2.tabs}


def test_dashboard_has_live_metrics_and_empty_states(app_env, super_admin):
    at = _login(_run(), "super@example.test")
    html = " ".join(m.value for m in at.markdown)
    assert "No courses yet" in html and "No generation runs yet" in html       # honest empty states, no fake numbers


def _open_datasets_tab(at):
    [b for b in at.button if b.key == "nav_SETTINGS"][0].click().run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_datasets_tab_visibility_by_role(app_env, super_admin, admin, viewer):
    for email, expected in (("super@example.test", True), ("admin@example.test", True), ("viewer@example.test", False)):
        at = _open_datasets_tab(_login(_run(), email))
        assert ("DATASETS" in {t.label for t in at.tabs}) is expected, email


def test_extraction_preview_runs_on_the_bundled_pdf(app_env, super_admin):
    at = _open_datasets_tab(_login(_run(), "super@example.test"))
    assert any("No datasets yet" in m.value for m in at.markdown)
    [b for b in at.button if b.key == "imp_start"][0].click().run()
    assert not at.exception, [e.value for e in at.exception]
    html = " ".join(m.value for m in at.markdown)
    assert "1063" in html and "Records to review" in html
    assert any("flagged for manual review" in m.value for m in at.markdown)
    assert any(b.key == "imp_confirm" for b in at.button)


def test_dataset_views_render_after_import(app_env, super_admin, result_for_ui):
    from database import session_scope
    from services import dataset_service as dsv
    from services import synthetic_service as syn
    with session_scope() as s:
        out = dsv.import_extraction(s, super_admin, result_for_ui)
        syn_ds = syn.build_synthetic_lecture_dataset(s, super_admin, out.dataset_id)
        exam_id, syn_id = out.dataset_id, syn_ds.id
    at = _open_datasets_tab(_login(_run(), "super@example.test"))
    assert any("NOUN 2026_2 E-EXAM DRAFT TIMETABLE" in m.value and "TEST DATASET" in m.value for m in at.markdown)
    at.selectbox(key="ds_pick").set_value(exam_id).run()
    [b for b in at.button if b.key == "ds_view"][0].click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert {"COURSES", "TIMETABLE", "PARALLEL AND CONFLICTS", "VALIDATION", "LECTURE TEST", "EXPORT"} <= {t.label for t in at.tabs}
    at.text_input(key="ex_text").input("CIT237").run()
    assert not at.exception and any("1 course entries match" in c.value for c in at.caption)
    at.selectbox(key="ex_batch").set_value("A").run()
    assert not at.exception
    [b for b in at.button if b.key == "ds_reval"][0].click().run()
    assert not at.exception
    at.selectbox(key="ds_pick").set_value(syn_id).run()                      # the synthetic dataset view also renders
    [b for b in at.button if b.key == "ds_view"][0].click().run()
    assert not at.exception and any("SYNTHETIC TEST DATA" in m.value for m in at.markdown)


@pytest.fixture(scope="session")
def result_for_ui():
    from importers import noun_exam_pdf as nx
    return nx.extract_noun_exam_pdf(str(ROOT / "data" / "noun" / "2026_2_E-Exam_Draft_Timetable_57.pdf"))
