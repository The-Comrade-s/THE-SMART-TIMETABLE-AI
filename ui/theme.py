"""Theme system: colour tokens, CSS injection and persistent theme state.

The active theme lives in st.session_state (survives reruns and page switches) and
is mirrored to the `theme` query parameter so it also survives a browser refresh.
"""
from __future__ import annotations

import streamlit as st

from config import get_settings

TOKENS = {
    "dark": {
        "bg": "#0B1220",
        "surface": "#121B2E",
        "surface_alt": "#18233A",
        "border": "#27344F",
        "text": "#E8EEF9",
        "muted": "#9FADC8",
        "accent": "#38BDF8",
        "accent_strong": "#0EA5E9",
        "on_accent": "#04121F",
        "nav_text": "#C9D5EC",
        "nav_hover": "#1B2842",
        "nav_active_bg": "#38BDF8",
        "nav_active_text": "#04121F",
        "success": "#34D399",
        "warning": "#FBBF24",
        "danger": "#F87171",
        "shadow": "0 1px 2px rgba(0,0,0,.35), 0 8px 24px rgba(0,0,0,.25)",
        "chart_grid": "#27344F",
        "chart_a": "#38BDF8",
        "chart_b": "#A78BFA",
    },
    "light": {
        "bg": "#F3F5F9",
        "surface": "#FFFFFF",
        "surface_alt": "#F7F9FC",
        "border": "#D9E0EC",
        "text": "#0F1B33",
        "muted": "#53607A",
        "accent": "#1D4ED8",
        "accent_strong": "#1E40AF",
        "on_accent": "#FFFFFF",
        "nav_text": "#1E2B47",
        "nav_hover": "#E7ECF6",
        "nav_active_bg": "#1D4ED8",
        "nav_active_text": "#FFFFFF",
        "success": "#047857",
        "warning": "#B45309",
        "danger": "#B91C1C",
        "shadow": "0 1px 2px rgba(15,27,51,.06), 0 6px 18px rgba(15,27,51,.06)",
        "chart_grid": "#E3E8F1",
        "chart_a": "#1D4ED8",
        "chart_b": "#7C3AED",
    },
}

FONT_STACK = '"IBM Plex Sans", "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'


def init_theme() -> None:
    """Initialise theme state once per browser session."""
    if "theme" not in st.session_state:
        requested = st.query_params.get("theme")
        st.session_state["theme"] = (
            requested if requested in TOKENS else get_settings().default_theme
        )


def current_theme() -> str:
    return st.session_state.get("theme", "dark")


def tokens() -> dict:
    return TOKENS[current_theme()]


def set_theme(name: str) -> None:
    if name in TOKENS:
        st.session_state["theme"] = name
        st.query_params["theme"] = name


def toggle_theme() -> None:
    set_theme("light" if current_theme() == "dark" else "dark")


def inject_css() -> None:
    t = tokens()
    css = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');
:root {{
  --bg:{t['bg']}; --surface:{t['surface']}; --surface-alt:{t['surface_alt']};
  --border:{t['border']}; --text:{t['text']}; --muted:{t['muted']};
  --accent:{t['accent']}; --accent-strong:{t['accent_strong']}; --on-accent:{t['on_accent']};
  --success:{t['success']}; --warning:{t['warning']}; --danger:{t['danger']};
  --shadow:{t['shadow']};
}}
html, body, .stApp, [class*="css"] {{ font-family:{FONT_STACK}; }}
.stApp {{ background:var(--bg); color:var(--text); }}
[data-testid="stHeader"] {{ background:transparent; }}
.block-container {{ padding:2rem 2.5rem 3rem; max-width:1280px; }}
h1,h2,h3,h4,h5 {{ color:var(--text) !important; font-family:{FONT_STACK}; letter-spacing:-0.01em; }}
h1 {{ font-size:1.75rem !important; font-weight:700 !important; }}
h2 {{ font-size:1.25rem !important; font-weight:600 !important; }}
h3 {{ font-size:1.05rem !important; font-weight:600 !important; }}
p, li, label, span, div {{ color:inherit; }}
.stApp p, .stApp label {{ color:var(--text); }}
a {{ color:var(--accent); }}

/* Sidebar */
section[data-testid="stSidebar"] {{
  background:var(--surface); border-right:1px solid var(--border);
}}
section[data-testid="stSidebar"] > div {{ padding-top:0.5rem; }}
.brand {{ padding:0.75rem 0.25rem 1.25rem; border-bottom:1px solid var(--border); margin-bottom:1rem; }}
.brand-name {{ font-weight:700; font-size:1.05rem; color:var(--text); line-height:1.25; }}
.brand-sub {{ font-size:0.78rem; color:var(--muted); margin-top:2px; }}
section[data-testid="stSidebar"] .stButton {{ margin-bottom:2px; }}
section[data-testid="stSidebar"] button[data-testid^="stBaseButton"] {{
  width:100%; justify-content:flex-start; text-align:left;
  background:transparent; border:1px solid transparent; border-radius:8px;
  padding:0.6rem 0.9rem; min-height:2.6rem; box-shadow:none;
}}
section[data-testid="stSidebar"] button[data-testid^="stBaseButton"] p,
section[data-testid="stSidebar"] button[data-testid^="stBaseButton"] div {{
  color:{t['nav_text']} !important; font-weight:700 !important;
  text-transform:uppercase; letter-spacing:0.06em; font-size:0.82rem !important;
}}
section[data-testid="stSidebar"] button[data-testid^="stBaseButton"]:hover {{
  background:{t['nav_hover']}; border-color:var(--border);
}}
section[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] {{
  background:{t['nav_active_bg']}; border-color:{t['nav_active_bg']};
}}
section[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] p,
section[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] div {{
  color:{t['nav_active_text']} !important;
}}
section[data-testid="stSidebar"] button:focus-visible {{ outline:2px solid var(--accent); outline-offset:2px; }}

/* Main-area buttons */
.main .stButton > button, [data-testid="stMain"] .stButton > button {{
  background:var(--surface); color:var(--text); border:1px solid var(--border);
  border-radius:8px; font-weight:600; padding:0.5rem 1rem;
}}
[data-testid="stMain"] .stButton > button:hover {{ border-color:var(--accent); color:var(--accent); }}
[data-testid="stMain"] .stButton > button p {{ color:inherit !important; }}
[data-testid="stMain"] button[data-testid="stBaseButton-primary"] {{
  background:var(--accent); color:var(--on-accent); border-color:var(--accent);
}}

/* Inputs */
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] {{
  background:var(--surface) !important; border-color:var(--border) !important; border-radius:8px !important;
}}
[data-baseweb="input"] input, [data-baseweb="textarea"] textarea {{ color:var(--text) !important; -webkit-text-fill-color:var(--text) !important; }}
[data-baseweb="select"] * {{ color:var(--text) !important; }}
[data-baseweb="popover"] ul, [data-baseweb="menu"] {{ background:var(--surface) !important; }}
[data-baseweb="popover"] li {{ color:var(--text) !important; }}

/* Components */
.page-title {{ margin:0; }}
.page-sub {{ color:var(--muted); margin:0.25rem 0 0; font-size:0.95rem; }}
.card {{
  background:var(--surface); border:1px solid var(--border); border-radius:12px;
  padding:1.1rem 1.25rem; box-shadow:var(--shadow);
}}
.metric-label {{ font-size:0.8rem; font-weight:600; color:var(--muted); }}
.metric-value {{ font-size:1.9rem; font-weight:700; color:var(--text); line-height:1.2; margin-top:0.25rem; }}
.metric-note {{ font-size:0.78rem; color:var(--muted); margin-top:0.25rem; }}
.badge {{
  display:inline-block; font-size:0.72rem; font-weight:700; padding:2px 8px;
  border-radius:999px; border:1px solid var(--border); background:var(--surface-alt); color:var(--muted);
}}
.badge-sample {{ color:var(--warning); border-color:var(--warning); background:transparent; }}
.badge-ok {{ color:var(--success); border-color:var(--success); background:transparent; }}
.badge-error {{ color:var(--danger); border-color:var(--danger); background:transparent; }}
.badge-muted {{ color:var(--muted); }}
.notice {{
  border:1px solid var(--border); border-left-width:4px; border-radius:8px;
  padding:0.75rem 1rem; background:var(--surface); margin:0.5rem 0; font-size:0.92rem;
}}
.notice strong {{ margin-right:0.35rem; }}
.notice-success {{ border-left-color:var(--success); }}
.notice-error {{ border-left-color:var(--danger); }}
.notice-warning {{ border-left-color:var(--warning); }}
.notice-info {{ border-left-color:var(--accent); }}
.empty {{
  text-align:center; padding:3rem 1.5rem; background:var(--surface);
  border:1px dashed var(--border); border-radius:12px;
}}
.empty-title {{ font-weight:700; font-size:1.1rem; color:var(--text); }}
.empty-body {{ color:var(--muted); margin-top:0.4rem; max-width:48ch; margin-left:auto; margin-right:auto; }}
.section-head {{ display:flex; align-items:center; gap:0.6rem; margin:1.75rem 0 0.75rem; }}
.section-head h2 {{ margin:0 !important; }}
table.data {{ width:100%; border-collapse:collapse; background:var(--surface); border:1px solid var(--border); border-radius:12px; overflow:hidden; }}
table.data th {{ text-align:left; font-size:0.78rem; font-weight:700; color:var(--muted); padding:0.65rem 0.9rem; background:var(--surface-alt); border-bottom:1px solid var(--border); }}
table.data td {{ padding:0.65rem 0.9rem; border-bottom:1px solid var(--border); color:var(--text); font-size:0.9rem; }}
table.data tr:last-child td {{ border-bottom:none; }}
.table-wrap {{ overflow-x:auto; }}


/* Login */
.login-brand {{ text-align:center; margin:3rem 0 1.5rem; }}
.login-brand h1 {{ margin-bottom:0.25rem; }}

/* Timetable grid */
.tt-wrap {{ overflow-x:auto; border:1px solid var(--border); border-radius:12px; background:var(--surface); }}
.tt-grid {{ display:flex; min-width:760px; }}
.tt-axis {{ width:64px; flex:none; border-right:1px solid var(--border); }}
.tt-col {{ flex:1; min-width:0; border-right:1px solid var(--border); }}
.tt-col:last-child {{ border-right:none; }}
.tt-dayhead {{ height:36px; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:0.82rem;
  background:var(--surface-alt); border-bottom:1px solid var(--border); color:var(--text); }}
.tt-day {{ position:relative; background-image:repeating-linear-gradient(to bottom, transparent 0, transparent 68px, var(--border) 68px, var(--border) 69px); }}
.tt-hour {{ position:absolute; left:0; right:0; font-size:0.72rem; color:var(--muted); padding:2px 6px; }}
.tt-block {{ position:absolute; box-sizing:border-box; overflow:hidden; background:var(--surface-alt); color:var(--text);
  border:1px solid var(--border); border-left:5px solid var(--accent); border-radius:6px; padding:3px 6px; font-size:0.68rem; line-height:1.25;
  display:flex; flex-direction:column; }}
.tt-block b {{ font-size:0.74rem; }}
.tt-block span {{ color:var(--muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.tt-bad {{ border:2px solid var(--danger); border-left:5px solid var(--danger); }}
.tt-conflict {{ color:var(--danger) !important; font-weight:700; letter-spacing:.05em; font-size:0.64rem; }}

/* Print: hide navigation, controls and dark backgrounds */
@media print {{
  section[data-testid="stSidebar"], [data-testid="stHeader"], [data-testid="stToolbar"], .stButton, [data-baseweb="tab-list"],
  [data-testid="stSelectbox"], [data-testid="stNumberInput"], iframe {{ display:none !important; }}
  .stApp, .block-container {{ background:#fff !important; color:#000 !important; padding:0 !important; max-width:100% !important; }}
  .tt-wrap, .card, table.data {{ box-shadow:none !important; background:#fff !important; border-color:#888 !important; }}
  .tt-block {{ background:#fff !important; color:#000 !important; border-color:#555 !important; print-color-adjust:exact; }}
  .tt-block span, .tt-hour, .tt-dayhead, .metric-label, .metric-note, .page-sub {{ color:#000 !important; background:#fff !important; }}
  .tt-bad {{ border:2px solid #000 !important; }}
  h1, h2, h3, p, td, th {{ color:#000 !important; }}
  @page {{ size: landscape; margin: 10mm; }}
}}

@media (max-width: 768px) {{
  .block-container {{ padding:1.25rem 1rem 2rem; }}
  .metric-value {{ font-size:1.5rem; }}
}}
</style>
"""
    st.markdown(css, unsafe_allow_html=True)
