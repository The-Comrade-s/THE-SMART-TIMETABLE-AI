import re
from pathlib import Path

import pytest

from ui.navigation import NAV_ITEMS
from ui.theme import TOKENS

ROOT = Path(__file__).resolve().parent.parent
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B50\u2705\u274C\u2728]")
PY = [p for p in ROOT.rglob("*.py") if ".venv" not in p.parts and "__pycache__" not in p.parts]


def luminance(h):
    h = h.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_navigation_exact_and_uppercase():
    assert NAV_ITEMS == ["DASHBOARD", "DEPARTMENTS", "LECTURERS", "COURSES", "CLASSROOMS", "TIMETABLE", "GENERATE TIMETABLE", "SETTINGS"]
    assert all(i == i.upper() for i in NAV_ITEMS)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_theme_contrast_meets_wcag(theme):
    t = TOKENS[theme]
    assert contrast(t["text"], t["bg"]) >= 7 and contrast(t["text"], t["surface"]) >= 7
    assert contrast(t["muted"], t["surface"]) >= 4.5 and contrast(t["muted"], t["surface_alt"]) >= 4.5
    assert contrast(t["nav_text"], t["surface"]) >= 4.5 and contrast(t["nav_active_text"], t["nav_active_bg"]) >= 4.5
    assert contrast(t["on_accent"], t["accent"]) >= 4.5 and contrast(t["accent"], t["surface"]) >= 3
    for k in ("success", "warning", "danger"):
        assert contrast(t[k], t["surface"]) >= 4.5, k


def test_sidebar_css_is_bold_uppercase_for_both_themes():
    import streamlit as st
    from ui import theme
    captured = []
    orig = st.markdown
    st.markdown = lambda body, **k: captured.append(body)
    try:
        for name in ("dark", "light"):
            st.session_state["theme"] = name
            theme.inject_css()
    finally:
        st.markdown = orig
    for css in captured:
        assert "text-transform:uppercase" in css and "font-weight:700 !important" in css


def test_no_emojis_anywhere():
    for f in PY + [ROOT / "README.md"] + list((ROOT / "docs").glob("*.md")):
        assert not EMOJI.search(f.read_text(encoding="utf-8")), f


def test_no_hardcoded_credentials_or_secrets():
    pattern = re.compile(r"(postgres(ql)?(\+\w+)?://\w+:[^@\s{]+@)|(password\s*=\s*[\"'][^\"']{6,}[\"'])", re.I)
    for f in PY:
        if f.name.startswith("test_") or f.name == "conftest.py":
            continue
        assert not pattern.search(f.read_text(encoding="utf-8")), f
    assert (ROOT / ".env.example").exists() and "PASSWORD@" in (ROOT / ".env.example").read_text()
    assert ".env" in (ROOT / ".gitignore").read_text()
    assert not (ROOT / ".env").exists()


def test_requirements_cover_third_party_imports():
    req = (ROOT / "requirements.txt").read_text().lower()
    for pkg in ("streamlit", "sqlalchemy", "psycopg2", "plotly", "reportlab", "openpyxl", "alembic", "argon2", "python-dotenv", "pdfplumber"):
        assert pkg in req, pkg


def test_every_python_module_imports():
    import importlib
    skip = {"app", "conftest"}
    for f in PY:
        rel = f.relative_to(ROOT).with_suffix("")
        if rel.parts[0] in ("tests", "migrations") or rel.parts[-1] in skip:
            continue
        importlib.import_module(".".join(rel.parts[:-1] if rel.parts[-1] == "__init__" else rel.parts))
