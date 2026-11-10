"""Plotly figures styled from the active theme tokens."""
from __future__ import annotations

import plotly.graph_objects as go

from ui.theme import FONT_STACK, tokens


def _layout(fig: go.Figure, height: int = 340) -> go.Figure:
    t = tokens()
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT_STACK, color=t["text"], size=13),
        legend=dict(orientation="h", y=1.12, x=0, font=dict(color=t["text"])),
        hoverlabel=dict(bgcolor=t["surface_alt"], font=dict(color=t["text"])),
    )
    fig.update_xaxes(gridcolor=t["chart_grid"], zerolinecolor=t["chart_grid"], linecolor=t["border"], tickfont=dict(color=t["muted"]), title_font=dict(color=t["muted"]))
    fig.update_yaxes(gridcolor=t["chart_grid"], zerolinecolor=t["chart_grid"], linecolor=t["border"], tickfont=dict(color=t["muted"]), title_font=dict(color=t["muted"]))
    return fig


def fitness_chart(curve: dict) -> go.Figure:
    t = tokens()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=curve["generation"], y=curve["best"], name="Best fitness", mode="lines", line=dict(color=t["chart_a"], width=3)))
    fig.add_trace(go.Scatter(x=curve["generation"], y=curve["average"], name="Population average", mode="lines", line=dict(color=t["chart_b"], width=2, dash="dot")))
    fig.update_xaxes(title_text="Generation")
    fig.update_yaxes(title_text="Fitness", range=[0, 1])
    return _layout(fig)


def penalty_chart(penalties: dict) -> go.Figure:
    t = tokens()
    fig = go.Figure(go.Bar(x=list(penalties.values()), y=list(penalties.keys()), orientation="h", marker_color=t["chart_a"]))
    fig.update_xaxes(title_text="Penalty points")
    fig.update_yaxes(autorange="reversed")
    return _layout(fig)


def bar_chart(labels, values, x_title: str = "", y_title: str = "") -> go.Figure:
    t = tokens()
    fig = go.Figure(go.Bar(x=list(labels), y=list(values), marker_color=t["chart_a"]))
    fig.update_xaxes(title_text=x_title)
    fig.update_yaxes(title_text=y_title, dtick=1 if values and max(values) < 8 else None)
    return _layout(fig)


def histogram(values, x_title: str = "", y_title: str = "Rooms") -> go.Figure:
    t = tokens()
    fig = go.Figure(go.Histogram(x=list(values), marker_color=t["chart_a"], nbinsx=8))
    fig.update_xaxes(title_text=x_title)
    fig.update_yaxes(title_text=y_title)
    return _layout(fig)


def progress_chart(history: list) -> go.Figure:
    t = tokens()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[h["generation"] for h in history], y=[h["best_fitness"] for h in history], name="Best fitness",
                             mode="lines", line=dict(color=t["chart_a"], width=3)))
    fig.add_trace(go.Scatter(x=[h["generation"] for h in history], y=[h["avg_fitness"] for h in history], name="Population average",
                             mode="lines", line=dict(color=t["chart_b"], width=2, dash="dot")))
    fig.update_xaxes(title_text="Generation")
    fig.update_yaxes(title_text="Fitness", type="log" if history and min(h["best_fitness"] for h in history) < 0.01 else "linear")
    return _layout(fig, 300)


def runs_chart(labels, initial, final) -> go.Figure:
    t = tokens()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=labels, y=initial, name="Initial fitness", marker_color=t["chart_b"]))
    fig.add_trace(go.Bar(x=labels, y=final, name="Final fitness", marker_color=t["chart_a"]))
    fig.update_layout(barmode="group")
    fig.update_xaxes(title_text="Generation run", type="category")
    fig.update_yaxes(title_text="Fitness", type="log")
    return _layout(fig)


def violations_chart(labels, hard) -> go.Figure:
    t = tokens()
    fig = go.Figure(go.Scatter(x=labels, y=hard, mode="lines+markers", line=dict(color=t["chart_a"], width=3)))
    fig.update_xaxes(title_text="Generation run", type="category")
    fig.update_yaxes(title_text="Hard violations (independent validation)", rangemode="tozero", dtick=1 if hard and max(hard) < 8 else None)
    return _layout(fig)
