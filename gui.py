"""
gui.py — Accedo Strategic Lead Scout
=====================================
Two tracks:
  🔍 Discovery — Gemini + Exa find companies, Grok researches them
  📋 Account Intelligence — research tracked accounts from Sheets

Both tracks respect the BU selector (NAM / E&L / APAC).
"""

import base64
import logging
import random
import os
from datetime import datetime
from io import StringIO

import requests as _requests

import pandas as pd
import streamlit as st
import streamlit.components.v1 as _components

import config
import main
from utils.helpers import setup_logging
from utils.usage_tracker import load_usage_history
from core.enrichment_runner import (
    parse_company_input, estimate_enrichment_cost,
    run_bulk_enrichment, run_company_enrichment,
)
setup_logging(level=logging.INFO)

# Accedo logo — encoded once at startup, reused in topnav
_LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "accedo-logo.png")
try:
    with open(_LOGO_PATH, "rb") as _f:
        _ACCEDO_LOGO_SRC = f"data:image/png;base64,{base64.b64encode(_f.read()).decode()}"
except Exception:
    _ACCEDO_LOGO_SRC = None

# ---------------------------------------------------------------------------
# Shared SheetsClient — one instance per session, reused everywhere
# Prevents hitting the Sheets API quota from multiple instantiations
# ---------------------------------------------------------------------------

if "sheets_client" not in st.session_state:
    try:
        from core.sheets import SheetsClient as _SheetsClient
        st.session_state["sheets_client"] = _SheetsClient()
    except Exception:
        st.session_state["sheets_client"] = None

def _get_sc():
    """Return the shared SheetsClient, creating a new one if needed."""
    if not st.session_state.get("sheets_client"):
        try:
            from core.sheets import SheetsClient as _SheetsClient
            st.session_state["sheets_client"] = _SheetsClient()
        except Exception:
            return None
    return st.session_state["sheets_client"]


def _get_sheet_url() -> str:
    """Return the Google Sheets URL for the active spreadsheet, or empty string."""
    try:
        sc = _get_sc()
        if sc and hasattr(sc, "_ss") and sc._ss:
            return f"https://docs.google.com/spreadsheets/d/{sc._ss.id}"
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Suggested prompts loader
# ---------------------------------------------------------------------------

def _load_suggested_prompts() -> list:
    try:
        with open("suggested_prompts.txt", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        return ["Regional sports broadcaster migrating from ViewLift 2026"]


# ---------------------------------------------------------------------------
# In-memory log capture
# ---------------------------------------------------------------------------

if "log_stream" not in st.session_state:
    st.session_state["log_stream"] = StringIO()
    _stream_handler = logging.StreamHandler(st.session_state["log_stream"])
    _stream_handler.setFormatter(
        logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s  —  %(message)s")
    )
    logging.getLogger("ott_lead_gen").addHandler(_stream_handler)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Accedo Lead Scout",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Accedo brand CSS — Outfit font, pill buttons, brand colours
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&display=swap');

    /* Accedo brand tokens */
    :root {
        --accedo-black:  #0B0B0B;
        --accedo-blue:   #0064FF;
        --accedo-white:  #FDFDFD;
        --accedo-yellow: #FFB71E;
        --accedo-red:    #FF2B62;
        --font-outfit:   'Outfit', Arial, sans-serif;
    }

    html, body {
        font-family: var(--font-outfit) !important;
    }

    /* Apply Outfit to text-bearing elements — span excluded to preserve icon fonts */
    p, div, section, article, aside, header, footer, main, nav,
    h1, h2, h3, h4, h5, h6,
    button, input, textarea, select, option, label,
    td, th, li, a, caption, blockquote, pre,
    .stMarkdown, .stAlert, .stCaption, .stCode,
    [data-testid="stSidebar"], [data-testid="stMetricLabel"],
    [data-testid="stMetricValue"], [data-testid="stExpander"] {
        font-family: var(--font-outfit) !important;
    }

    /* Outfit Medium for headings (brand spec) */
    h1, h2, h3, h4, h5, h6,
    [data-testid="stHeading"],
    [data-testid="stSidebar"] h2 {
        font-weight: 500 !important;
    }

    /* Primary / form submit buttons — Accedo blue pill */
    .stFormSubmitButton > button,
    [data-testid="stBaseButton-primary"] {
        background-color: #0064FF !important;
        border-color: #0064FF !important;
        color: #FDFDFD !important;
        border-radius: 50px !important;
        font-weight: 600 !important;
        letter-spacing: 0.3px !important;
        transition: background-color 0.15s ease, border-color 0.15s ease !important;
    }
    .stFormSubmitButton > button:hover,
    [data-testid="stBaseButton-primary"]:hover {
        background-color: #0050CB !important;
        border-color: #0050CB !important;
    }
    .stFormSubmitButton > button:disabled,
    [data-testid="stBaseButton-primary"]:disabled {
        background-color: rgba(0,100,255,0.35) !important;
        border-color: transparent !important;
        color: rgba(253,253,253,0.5) !important;
    }

    /* Secondary buttons — ghost style (sign-out, back, list items) */
    [data-testid="stBaseButton-secondary"] {
        background-color: transparent !important;
        border-color: transparent !important;
        color: #606060 !important;
        border-radius: 6px !important;
        font-size: 0.75rem !important;
        font-weight: 400 !important;
        letter-spacing: 0 !important;
        padding: 2px 6px !important;
        min-height: unset !important;
        transition: background-color 0.15s ease, color 0.15s ease !important;
    }
    [data-testid="stBaseButton-secondary"]:hover {
        background-color: rgba(255,255,255,0.06) !important;
        border-color: transparent !important;
        color: #a0a0a0 !important;
    }

    /* Sidebar top label */
    [data-testid="stSidebar"] h2 {
        color: #0064FF !important;
        font-weight: 700 !important;
    }

    /* Tab active indicator — Accedo blue */
    .stTabs [aria-selected="true"] {
        color: #0064FF !important;
        border-bottom-color: #0064FF !important;
    }

    /* Metric value */
    [data-testid="stMetricValue"] {
        color: #0064FF !important;
        font-weight: 700 !important;
    }

    /* ── SERGIO-aligned surface styles ── */

    /* Cards / expanders — dark surface + subtle border */
    [data-testid="stExpander"],
    [data-testid="stExpanderDetails"] {
        background-color: #111111 !important;
        border: 1px solid #2a2a2a !important;
        border-radius: 16px !important;
    }

    /* Expander header row */
    [data-testid="stExpander"] summary,
    [data-testid="stExpanderToggleIcon"] {
        background-color: #111111 !important;
        border-radius: 16px !important;
    }

    /* Input fields */
    [data-testid="stTextInput"] input,
    [data-testid="stTextArea"] textarea,
    [data-testid="stSelectbox"] div[data-baseweb],
    [data-testid="stNumberInput"] input {
        background-color: #1a1a1a !important;
        border: 1px solid #2a2a2a !important;
        border-radius: 8px !important;
        color: #FDFDFD !important;
    }
    [data-testid="stTextInput"] input:focus,
    [data-testid="stTextArea"] textarea:focus {
        border-color: #0064FF !important;
        box-shadow: 0 0 0 2px rgba(0,100,255,0.25) !important;
        outline: none !important;
    }

    /* Sidebar — slightly elevated from page bg */
    [data-testid="stSidebar"] {
        background-color: #111111 !important;
        border-right: 1px solid #2a2a2a !important;
    }

    /* Dividers */
    hr {
        border-color: #2a2a2a !important;
    }

    /* Secondary / caption text */
    [data-testid="stCaptionContainer"],
    .stCaption {
        color: #a0a0a0 !important;
    }

    /* Info alert — blue opacity (SERGIO style) */
    [data-testid="stAlert"][kind="info"],
    div[data-baseweb="notification"][kind="info"] {
        background-color: rgba(0,100,255,0.10) !important;
        border: 1px solid rgba(0,100,255,0.30) !important;
        border-radius: 8px !important;
        color: #FDFDFD !important;
    }

    /* Success alert — green opacity */
    [data-testid="stAlert"][kind="success"],
    div[data-baseweb="notification"][kind="positive"] {
        background-color: rgba(34,197,94,0.10) !important;
        border: 1px solid rgba(34,197,94,0.30) !important;
        border-radius: 8px !important;
        color: #FDFDFD !important;
    }

    /* Warning alert — amber opacity */
    [data-testid="stAlert"][kind="warning"],
    div[data-baseweb="notification"][kind="warning"] {
        background-color: rgba(255,183,30,0.10) !important;
        border: 1px solid rgba(255,183,30,0.30) !important;
        border-radius: 8px !important;
        color: #FDFDFD !important;
    }

    /* Error alert — pink/red opacity */
    [data-testid="stAlert"][kind="error"],
    div[data-baseweb="notification"][kind="negative"] {
        background-color: rgba(255,43,98,0.10) !important;
        border: 1px solid rgba(255,43,98,0.30) !important;
        border-radius: 8px !important;
        color: #FDFDFD !important;
    }

    /* Dataframe / table */
    [data-testid="stDataFrame"] {
        border: 1px solid #2a2a2a !important;
        border-radius: 12px !important;
        overflow: hidden !important;
    }

    /* Metric cards */
    [data-testid="stMetric"] {
        background-color: #111111 !important;
        border: 1px solid #2a2a2a !important;
        border-radius: 12px !important;
        padding: 12px 16px !important;
    }

    /* ── Hide Streamlit sidebar ── */
    [data-testid="stSidebar"],
    [data-testid="stSidebarNav"],
    section[data-testid="stSidebarContent"] {
        display: none !important;
    }

    /* ── Top navigation — SERGIO-style pill radio ── */
    div[data-testid="stRadio"] > div[role="radiogroup"] {
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        gap: 2px !important;
        background: transparent !important;
        border: none !important;
        padding: 0 !important;
    }
    /* Hide the radio circle / BaseWeb mark */
    div[data-testid="stRadio"] [data-baseweb="radio"] > div:first-child,
    div[data-testid="stRadio"] label > div:first-child {
        display: none !important;
    }
    div[data-testid="stRadio"] label {
        padding: 5px 12px !important;
        border-radius: 8px !important;
        cursor: pointer !important;
        font-size: 15px !important;
        font-weight: 500 !important;
        color: #808080 !important;
        white-space: nowrap !important;
        transition: background 0.15s ease, color 0.15s ease !important;
    }
    div[data-testid="stRadio"] label:has(input:checked),
    div[data-testid="stRadio"] label[aria-checked="true"] {
        background-color: #0064FF !important;
        color: #FDFDFD !important;
    }
    div[data-testid="stRadio"] label:hover {
        color: #FDFDFD !important;
        background-color: #1e1e1e !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Browser notification helpers
# ---------------------------------------------------------------------------

def _request_notification_permission() -> None:
    """Ask the browser for notification permission once per session."""
    if st.session_state.get("_notif_permission_requested"):
        return
    _components.html(
        "<script>"
        "var N=window.parent&&window.parent.Notification;"
        "if(N&&N.permission==='default'){N.requestPermission();}"
        "</script>",
        height=0,
    )
    st.session_state["_notif_permission_requested"] = True


def _browser_notify(title: str, body: str = "") -> None:
    """Fire a browser notification if enabled and permission has been granted."""
    if not st.session_state.get("notifications_enabled", True):
        return
    t = title.replace("\\", "\\\\").replace("'", "\\'")
    b = body.replace("\\", "\\\\").replace("'", "\\'")
    _components.html(
        f"<script>"
        f"(function(){{"
        f"var N=window.parent&&window.parent.Notification;"
        f"if(N&&N.permission==='granted'){{new N('{t}',{{body:'{b}'}});}}"
        f"}})();"
        f"</script>",
        height=0,
    )


# ---------------------------------------------------------------------------
# Email gate — must authenticate before accessing the tool
# ---------------------------------------------------------------------------
from utils.auth import get_current_user, render_budget_bar, render_email_gate

if not render_email_gate(logo_src=_ACCEDO_LOGO_SRC):
    st.stop()

# Initialise discovery engine session state from config default on first load
if "_discovery_engine_saved" not in st.session_state:
    st.session_state["_discovery_engine_saved"] = config.DISCOVERY_ENGINE

_request_notification_permission()

# ---------------------------------------------------------------------------
# Session state helpers
# ---------------------------------------------------------------------------

def _get_history() -> list:
    if "run_history" not in st.session_state:
        st.session_state["run_history"] = []
    return st.session_state["run_history"]


def _append_to_history(record: dict) -> None:
    history = _get_history()
    history.insert(0, record)
    st.session_state["run_history"] = history[:50]


# ---------------------------------------------------------------------------
# Visual helpers
# ---------------------------------------------------------------------------

def _verdict_color(verdict: str) -> str:
    return {"HOT": "#28a745", "WARM": "#e6a817", "COLD": "#dc3545"}.get(verdict or "", "#6c757d")


def _score_bar_html(score) -> str:
    if score is None:
        return ""
    pct = min(int(score), 100)
    color = "#28a745" if pct >= 70 else "#e6a817" if pct >= 50 else "#dc3545"
    return (
        f'<div style="background:#e9ecef;border-radius:6px;height:10px;width:100%;margin-bottom:4px">'
        f'<div style="background:{color};width:{pct}%;height:10px;border-radius:6px"></div></div>'
        f'<span style="font-size:0.85em;color:#555">{pct}/100</span>'
    )


def _verdict_chip(verdict: str) -> str:
    color = _verdict_color(verdict)
    return (
        f'<span style="background:{color};color:white;padding:3px 12px;'
        f'border-radius:12px;font-weight:700;font-size:0.82em">{verdict or "?"}</span>'
    )


# ---------------------------------------------------------------------------
# Cost / usage panel
# ---------------------------------------------------------------------------

def render_usage_panel(usage_summary: dict) -> None:
    if not usage_summary:
        return
    total = usage_summary.get("total_cost_usd", 0)
    per_p = usage_summary.get("cost_per_prospect", 0)
    n     = usage_summary.get("prospects", 0)

    with st.expander(
        f"Run Cost: ${total:.4f} total  ·  ${per_p:.4f}/prospect  ·  {n} prospect(s)",
        expanded=False,
    ):
        g    = usage_summary.get("grok", {})
        g_ai = usage_summary.get("gemini", {})
        s    = usage_summary.get("sonnet", {})
        o    = usage_summary.get("opus", {})
        e    = usage_summary.get("exa", {})
        a    = usage_summary.get("apollo", {})

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Token Usage**")
            st.markdown(
                f"| Tool | Input | Output | Est. Cost |\n"
                f"|------|-------|--------|-----------|\n"
                f"| Grok grok-4-1 | {g.get('input_tokens',0):,} | {g.get('output_tokens',0):,} | ${g.get('cost_usd',0):.4f} |\n"
                f"| Gemini Flash | {g_ai.get('input_tokens',0):,} | {g_ai.get('output_tokens',0):,} | ${g_ai.get('cost_usd',0):.4f} |\n"
                f"| Claude Sonnet | {s.get('input_tokens',0):,} | {s.get('output_tokens',0):,} | ${s.get('cost_usd',0):.4f} |\n"
                f"| Claude Opus | {o.get('input_tokens',0):,} | {o.get('output_tokens',0):,} | ${o.get('cost_usd',0):.4f} |"
            )
        with col2:
            st.markdown("**API Credits**")
            st.markdown(
                f"| Tool | Usage | Est. Cost |\n"
                f"|------|-------|-----------|\n"
                f"| Exa | {e.get('credits',0)} credits | ${e.get('cost_usd',0):.4f} |\n"
                f"| Apollo Enrich | {a.get('enrich_credits',0)} credits | ${a.get('cost_usd',0):.4f} |\n"
                f"| Apollo Search | {a.get('search_calls',0)} calls | $0.00 (free) |"
            )

        st.divider()
        st.markdown(f"**Total: ${total:.4f}** across {n} prospect(s)  ·  ${per_p:.4f} per prospect")

        per_p_list = usage_summary.get("per_prospect", [])
        if per_p_list:
            st.markdown("**Per-prospect breakdown**")
            rows = []
            for p in per_p_list:
                if p.get("company") == "_grok_research":
                    rows.append({
                        "Company": "Discovery + Grok (shared)",
                        "Grok in": p.get("grok_input_tokens", 0),
                        "Grok out": p.get("grok_output_tokens", 0),
                        "Gemini": f"{p.get('gemini_input_tokens',0)}in/{p.get('gemini_output_tokens',0)}out",
                        "Sonnet": "—", "Opus": "—",
                        "Exa": p.get("exa_credits_total", 0),
                        "Apollo": "—",
                        "Cost $": f"{p.get('cost_usd', 0):.4f}",
                    })
                    continue
                rows.append({
                    "Company": p.get("company", ""),
                    "Grok in": p.get("grok_input_tokens", 0),
                    "Grok out": p.get("grok_output_tokens", 0),
                    "Gemini": f"{p.get('gemini_input_tokens',0)}in/{p.get('gemini_output_tokens',0)}out",
                    "Sonnet": f"{p.get('sonnet_input_tokens',0)}in/{p.get('sonnet_output_tokens',0)}out",
                    "Opus": f"{p.get('opus_input_tokens',0)}in/{p.get('opus_output_tokens',0)}out",
                    "Exa": p.get("exa_credits_total", 0),
                    "Apollo": p.get("apollo_enrich_credits", 0),
                    "Cost $": f"{p.get('cost_usd', 0):.4f}",
                })
            st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)


# ---------------------------------------------------------------------------
# Result card (live run)
# ---------------------------------------------------------------------------

def render_result_card(r: dict, card_idx: int) -> None:
    company  = r.get("company", "Unknown")
    verdict  = r.get("verdict", "?")
    score    = r.get("refined_score")
    grok_sc  = r.get("grok_score")
    is_cold  = verdict == "COLD"
    error    = r.get("error")
    prospect = r.get("prospect", {})
    analyst  = r.get("analyst", {})
    emails   = r.get("emails", {})
    bu       = r.get("bu", "")

    label = f"{company}   ·   {score}/100   ·   {verdict}   ·   {bu}"

    with st.expander(label, expanded=(card_idx == 0 and not is_cold)):
        if error:
            st.error(f"Pipeline error: {error}")
            return

        h1, h2, h3, h4, h5 = st.columns([2, 1.5, 1.5, 1.5, 3])
        with h1:
            st.markdown("**Opportunity Score**")
            st.markdown(_score_bar_html(score), unsafe_allow_html=True)
            if grok_sc and grok_sc != score:
                st.caption(f"Grok raw: {grok_sc} → Analyst adjusted: {score}")
        with h2:
            st.markdown("**Verdict**")
            st.markdown(_verdict_chip(verdict), unsafe_allow_html=True)
        with h3:
            st.markdown("**Sheet Tab**")
            st.markdown("Cold Leads" if is_cold else "Hot Leads")
        with h4:
            st.markdown("**BU**")
            st.markdown(f"`{bu}`" if bu else "—")
        with h5:
            gap = prospect.get("transition_gap_timer", "")
            if gap:
                st.markdown("**Transition Gap**")
                st.info(gap)

        st.divider()
        t_intel, t_emails, t_obj = st.tabs([
            "Intelligence", "Outreach Emails", "Objection Counters"
        ])

        with t_intel:
            ic1, ic2 = st.columns(2)
            with ic1:
                inflection = prospect.get("causal_inflection", "")
                if inflection:
                    st.markdown("**Causal Inflection**")
                    st.write(inflection)
                entry = analyst.get("top_entry_point", "")
                if entry:
                    st.markdown("**Accedo Entry Point**")
                    st.success(entry)
                risk = analyst.get("key_risk_if_no_action", "")
                if risk:
                    st.markdown("**Risk if Accedo Waits 90 Days**")
                    st.warning(risk)
                reasoning = analyst.get("score_delta_reasoning", "")
                if reasoning:
                    st.markdown("**Analyst Reasoning**")
                    st.caption(reasoning)
            with ic2:
                pm  = prospect.get("power_map", {})
                vis = pm.get("the_visionary", {})
                ops = pm.get("the_operator", {})
                st.markdown("**Visionary**")
                if vis.get("name"):
                    li = vis.get("linkedin", "")
                    nm = f"[{vis['name']}]({li})" if li else vis["name"]
                    st.markdown(f"{nm} — *{vis.get('title', '')}*")
                    if vis.get("public_quote"):
                        st.caption(f'"{vis["public_quote"][:220]}"')
                    if vis.get("angle"):
                        st.info(f"Hook: {vis['angle']}")
                else:
                    st.caption("Not identified in this run")
                st.markdown("**Operator**")
                if ops.get("name"):
                    li = ops.get("linkedin", "")
                    nm = f"[{ops['name']}]({li})" if li else ops["name"]
                    st.markdown(f"{nm} — *{ops.get('title', '')}*")
                    if ops.get("public_quote"):
                        st.caption(f'"{ops["public_quote"][:220]}"')
                    if ops.get("angle"):
                        st.info(f"Hook: {ops['angle']}")
                else:
                    st.caption("Not identified in this run")

            signals = prospect.get("signals", [])
            if signals:
                st.markdown("---")
                st.markdown("**Research Signals**")
                for sig in signals[:4]:
                    conf = sig.get("confidence", "")
                    icon = {"high": "High", "medium": "Med", "low": "Low"}.get(conf, "")
                    stype = sig.get("signal_type", "")
                    ev = sig.get("evidence", "")[:250]
                    src = sig.get("source_url") or sig.get("source_type", "")
                    src_md = f" · [source]({src})" if src and src.startswith("http") else (f" · {src}" if src else "")
                    st.markdown(f"{icon} **{stype}** — {ev}{src_md}")

        with t_emails:
            vis_email = emails.get("visionary_email", {})
            ops_email = emails.get("operator_email", {})
            ec1, ec2 = st.columns(2)
            with ec1:
                vis_name = vis.get("name", "Visionary")
                subj = vis_email.get("subject_line", "")
                body = vis_email.get("body", "")
                st.markdown(f"**To: {vis_name}**")
                if subj:
                    st.markdown(
                        f'<div style="background:#f0f4ff;border-left:3px solid #4a6fa5;'
                        f'padding:6px 10px;border-radius:4px;margin-bottom:8px;font-size:0.9em">'
                        f'<strong>Subject:</strong> {subj}</div>',
                        unsafe_allow_html=True,
                    )
                if body and "refused" not in body and "failed" not in body:
                    st.text_area("vis_body", value=body, height=230,
                                 key=f"vis_{card_idx}", label_visibility="collapsed")
                else:
                    st.caption(body or "No draft generated.")
            with ec2:
                ops_name = ops.get("name", "Operator")
                subj = ops_email.get("subject_line", "")
                body = ops_email.get("body", "")
                st.markdown(f"**To: {ops_name}**")
                if subj:
                    st.markdown(
                        f'<div style="background:#f0fff4;border-left:3px solid #28a745;'
                        f'padding:6px 10px;border-radius:4px;margin-bottom:8px;font-size:0.9em">'
                        f'<strong>Subject:</strong> {subj}</div>',
                        unsafe_allow_html=True,
                    )
                if body and "refused" not in body and "failed" not in body:
                    st.text_area("ops_body", value=body, height=230,
                                 key=f"ops_{card_idx}", label_visibility="collapsed")
                else:
                    st.caption(body or "No draft generated.")

        with t_obj:
            outreach = prospect.get("outreach", {})
            obj_stack = outreach.get("objection_stack", [])
            if obj_stack:
                for obj in obj_stack:
                    objection = obj.get("objection", "")
                    counter   = obj.get("counter", "")
                    evidence  = obj.get("counter_evidence_source", "")
                    if objection:
                        st.markdown(f"**{objection}**")
                        if counter:
                            st.success(f"**Counter:** {counter}")
                        if evidence:
                            st.caption(f"Evidence: {evidence}")
                        st.divider()
            note = outreach.get("salesforce_note", "")
            if note:
                st.markdown("**Salesforce Note**")
                st.code(note, language=None)


# ---------------------------------------------------------------------------
# History card (from Sheets row)
# ---------------------------------------------------------------------------

def render_history_card(row: dict) -> None:
    with st.expander("🔍 Debug: raw row values", expanded=False):
        st.json({k: repr(v) for k, v in row.items()})
    company  = row.get("Company", "Unknown")
    score    = str(row.get("Opportunity Score", "")).replace("/100", "")
    verdict  = row.get("Priority", "")
    tab      = row.get("_tab", "")
    domain   = row.get("Domain", "")
    ts       = row.get("Timestamp", "")
    bu       = row.get("BU", "")
    is_cold  = tab == "Cold Leads"

    vis_name  = row.get("Visionary Name", "")
    vis_title = row.get("Visionary Title", "")
    vis_li    = row.get("Visionary LinkedIn", "")
    vis_hook  = row.get("Visionary Hook", "")
    ops_name  = row.get("Operator Name", "")
    ops_title = row.get("Operator Title", "")
    ops_li    = row.get("Operator LinkedIn", "")
    ops_hook  = row.get("Operator Hook", "")

    st.markdown(f"### {company}")
    st.caption(f"{domain} · {ts} · {tab} · BU: {bu or '—'}")

    h1, h2, h3 = st.columns([2, 2, 2])
    with h1:
        st.markdown("**Opportunity Score**")
        try:
            st.markdown(_score_bar_html(int(score)), unsafe_allow_html=True)
        except Exception:
            st.caption(score or "—")
    with h2:
        st.markdown("**Verdict**")
        verdict_map = {"Critical": "HOT", "High": "HOT", "Med": "WARM", "Low": "COLD"}
        v = verdict_map.get(verdict, verdict)
        st.markdown(_verdict_chip(v), unsafe_allow_html=True)
    with h3:
        st.markdown("**Tab**")
        st.markdown("Cold Leads" if is_cold else "Hot Leads")

    st.divider()
    t_intel, t_emails, t_obj = st.tabs([
        "Intelligence", "Outreach Emails", "Objection Counters"
    ])

    with t_intel:
        ic1, ic2 = st.columns(2)
        with ic1:
            for field, label in [
                ("Causal Inflection", "**Causal Inflection**"),
                ("Transition Gap", "**Transition Gap**"),
                ("Opportunity Type", "**Opportunity Type**"),
            ]:
                val = str(row.get(field, "") or "")
                if val:
                    st.markdown(label)
                    st.write(val) if field != "Opportunity Type" else st.caption(val)
            signal = str(row.get("Top Signal", "") or "")
            if signal:
                st.markdown("**Top Signal**")
                conf = row.get("Signal Confidence", "")
                icon = {"high": "High", "medium": "Med", "low": "Low"}.get(conf, "")
                src = str(row.get("Signal Source", "") or "")
                src_md = f" · [source]({src})" if src.startswith("http") else ""
                st.markdown(f"{icon} {signal[:250]}{src_md}")
        with ic2:
            st.markdown("**Visionary**")
            if vis_name:
                nm = f"[{vis_name}]({vis_li})" if vis_li else vis_name
                st.markdown(f"{nm} — *{vis_title}*")
                if vis_hook:
                    st.info(f"Hook: {vis_hook}")
            else:
                st.caption("Not identified")

            st.markdown("**Operator**")
            if ops_name:
                nm = f"[{ops_name}]({ops_li})" if ops_li else ops_name
                st.markdown(f"{nm} — *{ops_title}*")
                if ops_hook:
                    st.info(f"Hook: {ops_hook}")
            else:
                st.caption("Not identified")

            apollo_name  = row.get("Apollo Contact Name", "")
            apollo_title = row.get("Apollo Contact Title", "")
            apollo_email = row.get("Apollo Email", "")
            apollo_li    = row.get("Apollo LinkedIn", "")
            if apollo_name:
                st.markdown("**Apollo Contact**")
                st.markdown(f"{apollo_name} — *{apollo_title}*")
                if apollo_email:
                    st.caption(apollo_email)
                if apollo_li:
                    st.caption(f"[LinkedIn]({apollo_li})")

    with t_emails:
        ec1, ec2 = st.columns(2)
        with ec1:
            st.markdown(f"**To: {vis_name or 'Visionary'}**")
            vis_subj = row.get("Visionary Subject Line", "")
            vis_body = row.get("Visionary Email", "")
            if vis_subj:
                st.markdown(
                    f'<div style="background:#f0f4ff;border-left:3px solid #4a6fa5;'
                    f'padding:6px 10px;border-radius:4px;margin-bottom:8px;font-size:0.9em">'
                    f'<strong>Subject:</strong> {vis_subj}</div>',
                    unsafe_allow_html=True,
                )
            if vis_body:
                st.text_area("vis_hist_body", value=vis_body, height=230,
                             key=f"hist_vis_{company}", label_visibility="collapsed")
            else:
                st.caption("No draft available.")
        with ec2:
            st.markdown(f"**To: {ops_name or 'Operator'}**")
            ops_subj = row.get("Operator Subject Line", "")
            ops_body = row.get("Operator Email", "")
            if ops_subj:
                st.markdown(
                    f'<div style="background:#f0fff4;border-left:3px solid #28a745;'
                    f'padding:6px 10px;border-radius:4px;margin-bottom:8px;font-size:0.9em">'
                    f'<strong>Subject:</strong> {ops_subj}</div>',
                    unsafe_allow_html=True,
                )
            if ops_body:
                st.text_area("ops_hist_body", value=ops_body, height=230,
                             key=f"hist_ops_{company}", label_visibility="collapsed")
            else:
                st.caption("No draft available.")

    with t_obj:
        for objection, col in [
            ("We're building this in-house", "Objection: In-House"),
            ("We already have a vendor", "Objection: Incumbent"),
            ("Budget / timing isn't right", "Objection: Budget"),
        ]:
            counter = row.get(col, "")
            if counter:
                st.markdown(f"**{objection}**")
                st.success(f"**Counter:** {counter}")
                st.divider()
        note = row.get("Salesforce Note", "")
        if note:
            st.markdown("**Salesforce Note**")
            st.code(note, language=None)


# ---------------------------------------------------------------------------
# History sidebar
# ---------------------------------------------------------------------------

def render_history_sidebar(bu_filter: str = None) -> None:
    cache_key    = "recent_leads_cache"
    cache_ts_key = "recent_leads_cache_ts"
    cache_bu_key = "recent_leads_cache_bu"
    now = datetime.now().timestamp()
    cache_age = now - st.session_state.get(cache_ts_key, 0)
    cached_bu = st.session_state.get(cache_bu_key, None)

    # Invalidate cache if BU changed or older than 5 minutes
    if (cache_key not in st.session_state
            or cache_age > 900
            or cached_bu != bu_filter):
        try:
            sc = _get_sc()
            if sc:
                st.session_state[cache_key]    = sc.get_recent_leads(max_rows=10, bu_filter=bu_filter)
                st.session_state[cache_ts_key] = now
                st.session_state[cache_bu_key] = bu_filter
        except Exception as exc:
            st.caption(f"Could not load history: {exc}")
            return

    recent = st.session_state.get(cache_key, [])
    if not recent:
        st.caption(f"No leads for BU={bu_filter} yet.")
        return

    for row in recent:
        company = row.get("Company", "Unknown")
        score   = str(row.get("Opportunity Score", "")).replace("/100", "")
        tab     = row.get("_tab", "")
        ts      = row.get("Timestamp", "")[:10]
        is_cold = tab == "Cold Leads"
        icon    = "❄️" if is_cold else "🔥"
        label   = f"{icon} {company[:22]}  ·  {score}  ·  {ts}"
        if st.button(label, key=f"hist_{company}_{ts}", use_container_width=True):
            st.session_state["history_view"] = row
            st.session_state["view_mode"]    = "history"
            st.session_state["active_page"]  = "history"
            st.rerun()


# ---------------------------------------------------------------------------
# Shared results display
# ---------------------------------------------------------------------------

def _display_results(results: list, dry: bool, query_str: str, bu: str) -> None:
    """Render summary table + result cards shared by both tracks."""
    hot     = sum(1 for r in results if r.get("verdict") == "HOT")
    warm    = sum(1 for r in results if r.get("verdict") == "WARM")
    cold    = sum(1 for r in results if r.get("verdict") == "COLD")
    written = sum(r.get("rows_written", 0) for r in results)

    st.divider()
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Prospects Found", len(results))
    m2.metric("HOT", hot)
    m3.metric("WARM", warm)
    m4.metric("COLD", cold)
    m5.metric("Written to Sheets", "—" if dry else written)
    m6.metric("BU", bu)

    usage_summary = results[0].get("usage_summary", {}) if results else {}
    if usage_summary:
        render_usage_panel(usage_summary)

    # Discovery panel (only shown for discovery track)
    first = results[0] if results else {}
    discovery_meta = first.get("discovery_meta", {})
    if discovery_meta.get("discovery_ran"):
        with st.expander(
            f"Discovery: Exa found {len(discovery_meta.get('all_found', []))} companies "
            f"· Gemini selected {len(discovery_meta.get('selected', []))}",
            expanded=True,
        ):
            if discovery_meta.get("selected"):
                st.markdown("**Selected for deep research**")
                for c in discovery_meta["selected"]:
                    li   = c.get("linkedin_url", "")
                    name = f"[{c['name']}]({li})" if li else c["name"]
                    st.markdown(
                        f"**{name}** — *{c.get('signal_type', '')}*  \n"
                        f"{c.get('reasoning', '')}"
                    )
            if discovery_meta.get("rejected"):
                st.markdown("**Filtered out by Gemini**")
                for r in discovery_meta["rejected"]:
                    st.caption(f"**{r.get('name')}** — {r.get('reason', '')}")

    if not dry:
        if written > 0:
            st.success(f"{written} lead(s) written to **{config.GOOGLE_SHEET_NAME}** · BU={bu}")
        else:
            st.error(
                "No rows written to Sheets. Possible causes:\n"
                "- Dry Run Mode is still ON\n"
                "- Column count mismatch\n"
                "- All leads were duplicate domains\n"
                "- Google Sheets credentials issue\n\n"
                "Check the Pipeline Log expander below."
            )

    st.divider()
    st.subheader("Summary")

    rows = []
    for r in results:
        p = r.get("prospect", {})
        rows.append({
            "Company":  r.get("company", ""),
            "Domain":   r.get("domain", ""),
            "BU":       r.get("bu", ""),
            "Grok":     r.get("grok_score", "?"),
            "Score":    r.get("refined_score", "?"),
            "Verdict":  r.get("verdict", "?"),
            "Tab":      "Cold" if r.get("verdict") == "COLD" else "Hot",
            "Exa":      "✓" if r.get("exa_enriched") == "found" else ("~" if r.get("exa_enriched") == "ran" else "—"),
            "Apollo":   "✓" if r.get("apollo_active") and config.APOLLO_ENABLED else "—",
            "Written":  "Yes" if r.get("rows_written", 0) > 0 else ("Preview" if dry else "—"),
            "Type":     p.get("opportunity_type", ""),
        })

    df = pd.DataFrame(rows)

    def _color_row(val):
        c = {"HOT": "#d4f0dc", "WARM": "#fff7d6", "COLD": "#fde8e8"}
        return f"background-color: {c.get(val, '')}"

    st.dataframe(
        df.style.map(_color_row, subset=["Verdict"]),
        width='stretch', hide_index=True,
    )

    st.divider()
    st.subheader("Lead Intelligence & Outreach")
    st.caption("Click any card to expand the full intelligence report, emails, and objection counters.")

    sort_order = {"HOT": 0, "WARM": 1, "COLD": 2}
    for i, r in enumerate(sorted(results, key=lambda x: sort_order.get(x.get("verdict", "COLD"), 2))):
        render_result_card(r, i)

    st.divider()
    with st.expander("Pipeline Log (last run)", expanded=False):
        log_stream = st.session_state.get("log_stream")
        if log_stream:
            log_contents = log_stream.getvalue()
            if log_contents:
                st.code(log_contents, language=None)
            else:
                st.caption("No log output captured for this run.")
        else:
            st.caption("Log stream not initialised — refresh the page and try again.")

    st.session_state.pop("recent_leads_cache", None)
    st.session_state.pop("recent_leads_cache_ts", None)

    _append_to_history({
        "timestamp":      datetime.now().strftime("%Y-%m-%d %H:%M"),
        "query":          query_str,
        "prospect_count": len(results),
        "hot_count":      hot,
        "warm_count":     warm,
        "cold_count":     cold,
        "rows_written":   written,
        "dry_run":        dry,
        "bu":             bu,
        "companies": [
            {"Company": r.get("company", ""), "Score": r.get("refined_score", ""), "Verdict": r.get("verdict", ""), "BU": r.get("bu", "")}
            for r in results
        ],
    })


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Model selector widget — module-level so Settings page can call it
# ---------------------------------------------------------------------------

def _model_selectbox(role: str, label: str) -> str:
    options = config.MODEL_OPTIONS[role]
    labels  = [o["label"] for o in options]
    key     = f"model_sel_{role}"
    if key not in st.session_state:
        st.session_state[key] = 0
    idx = st.selectbox(
        label,
        options=range(len(labels)),
        format_func=lambda i, _l=labels: _l[i],
        index=st.session_state[key],
        key=f"{key}_widget",
    )
    st.session_state[key] = idx
    chosen = options[idx]
    st.caption(
        f"💬 {chosen['note']}  \n"
        f"💰 ${chosen['input_cost']}/M in · ${chosen['output_cost']}/M out"
    )
    return chosen["model"]


def _api_status(attr: str, label: str) -> None:
    val = getattr(config, attr, "")
    icon = "🟢" if val else "🔴"
    st.caption(f"{icon} {label}")


# ---------------------------------------------------------------------------
# Avatar helper — fetches profile picture and caches as base64 data URL.
# Streamlit's default CSP blocks external img-src, so we proxy it server-side.
# ---------------------------------------------------------------------------

def _get_avatar_data_url(url: str) -> str | None:
    cache_key = f"_avatar_b64_{url}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]
    try:
        r = _requests.get(url, timeout=4)
        if r.ok:
            ct = r.headers.get("content-type", "image/jpeg").split(";")[0]
            data_url = f"data:{ct};base64,{base64.b64encode(r.content).decode()}"
            st.session_state[cache_key] = data_url
            return data_url
    except Exception:
        pass
    st.session_state[cache_key] = None
    return None


# ---------------------------------------------------------------------------
# Top navigation bar
# ---------------------------------------------------------------------------

def render_topnav() -> str:
    """Render horizontal nav bar. Returns active page key."""
    from utils.auth import get_current_user, get_month_spend

    _NAV_LABELS = ["Find Companies", "Enrich Companies", "Account Intelligence", "History", "Help", "Settings"]
    _NAV_KEYS   = ["find", "enrich", "accounts", "history", "help", "settings"]

    col_logo, col_nav, col_gap, col_user = st.columns([2, 6, 0.4, 3])

    with col_logo:
        if _ACCEDO_LOGO_SRC:
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:8px;padding-top:6px;">'
                f'<img src="{_ACCEDO_LOGO_SRC}" style="height:28px;width:auto;" />'
                f'<span style="font-size:18pt;font-weight:600;color:#FDFDFD;'
                f'letter-spacing:0.5px;white-space:nowrap;">Lead Scout</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown("### Lead Scout")

    with col_nav:
        current = st.session_state.get("active_page", "find")
        if current not in _NAV_KEYS:
            current = "find"
        selected = st.radio(
            "nav",
            options=_NAV_LABELS,
            index=_NAV_KEYS.index(current),
            horizontal=True,
            label_visibility="collapsed",
            key="topnav_radio",
        )
        active_page = _NAV_KEYS[_NAV_LABELS.index(selected)]
        st.session_state["active_page"] = active_page

    with col_user:
        current_user = get_current_user()
        if current_user:
            _user_obj    = getattr(st, "user", None)
            picture_url  = getattr(_user_obj, "picture", None)
            display_name = getattr(_user_obj, "name", None) or current_user.split("@")[0]

            # Build avatar HTML
            avatar_src = _get_avatar_data_url(picture_url) if picture_url else None
            if avatar_src:
                pic_html = (
                    f'<img src="{avatar_src}" '
                    f'style="width:26px;height:26px;border-radius:50%;'
                    f'object-fit:cover;flex-shrink:0;" />'
                )
            else:
                initials = (display_name[0].upper() if display_name else "?")
                pic_html = (
                    f'<div style="width:26px;height:26px;border-radius:50%;'
                    f'background:rgba(0,100,255,0.2);display:flex;align-items:center;'
                    f'justify-content:center;font-size:11px;font-weight:600;'
                    f'color:#0064FF;flex-shrink:0;">{initials}</div>'
                )

            # Budget bar values
            budget_html = ""
            try:
                spent  = get_month_spend(current_user, _get_sc())
                budget = config.DIRECTOR_BUDGET_USD
                pct    = min(spent / budget, 1.0) if budget > 0 else 0
                bar_color = (
                    "#22c55e" if pct < 0.6 else
                    "#FFB71E" if pct < 0.85 else
                    "#FF2B62"
                )
                budget_html = (
                    f'<div style="font-size:10px;color:#606060;margin-top:2px;">'
                    f'${spent:.2f} / ${budget:.2f}</div>'
                    f'<div style="height:3px;background:#2a2a2a;border-radius:2px;margin-top:2px;">'
                    f'<div style="width:{pct*100:.1f}%;height:100%;'
                    f'background:{bar_color};border-radius:2px;"></div></div>'
                )
            except Exception:
                pass

            # Info stack (avatar + name + budget) beside the sign-out button
            col_info, col_logout = st.columns([5, 1])
            with col_info:
                st.markdown(
                    f'<div style="display:flex;align-items:center;justify-content:flex-end;gap:8px;padding-top:4px;">'
                    f'{pic_html}'
                    f'<div style="min-width:0;">'
                    f'<div style="font-size:0.9rem;color:#FDFDFD;font-weight:500;'
                    f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
                    f'{display_name}</div>'
                    f'{budget_html}'
                    f'</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with col_logout:
                if st.button("→", key="topnav_signout", help="Sign out"):
                    st.session_state.pop("selected_director", None)
                    st.logout()

    st.divider()
    return active_page


# ---------------------------------------------------------------------------
# Settings page
# ---------------------------------------------------------------------------

def render_settings_page() -> None:
    from utils.auth import get_current_user, render_budget_bar

    st.subheader("Settings")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("#### Your Account")
        current_user = get_current_user()
        if current_user:
            st.caption(f"Signed in as **{current_user}**")
            st.caption("Role: Director of Strategic Accounts · Accedo")
            st.divider()
            st.markdown("**Monthly Budget**")
            try:
                render_budget_bar(current_user, _get_sc())
            except Exception:
                st.caption("Budget data unavailable")

    with col_b:
        st.markdown("#### Region")
        selected_bu = st.selectbox(
            "Your Region",
            options=config.BU_OPTIONS,
            index=config.BU_OPTIONS.index(st.session_state.get("selected_bu", config.BU_DEFAULT)),
            help="NAM = North America (US, Canada, Mexico) · E&L = Europe & Latin America · APAC = Asia Pacific",
        )
        st.session_state["selected_bu"] = selected_bu

    st.divider()
    st.markdown("#### Notifications")
    st.checkbox(
        "Browser Notifications",
        value=True,
        key="notifications_enabled",
        help="Show a desktop notification when a long-running step finishes. Useful when you switch to another tab while waiting.",
    )

    st.divider()
    st.markdown("#### Discovery Engine")
    st.caption("Choose which AI runs the Find Companies search. Claude uses web search and produces more detailed, higher quality results. Grok is faster.")

    # Use a persistent key separate from the widget key so it survives navigation
    _saved_engine = st.session_state.get("_discovery_engine_saved", "grok")

    def _save_engine():
        st.session_state["_discovery_engine_saved"] = st.session_state["_discovery_engine_widget"]

    st.radio(
        "Discovery Engine",
        options=["grok", "claude", "openai"],
        index=["grok", "claude", "openai"].index(_saved_engine) if _saved_engine in ["grok", "claude", "openai"] else 0,
        format_func=lambda x: {
            "grok":   "Grok — fast, broad sweep (~60s/vertical)",
            "claude": "Claude + Web Search — high quality (requires Tier 2+)",
            "openai": "GPT-4o + Web Search — recommended for quality",
        }[x],
        key="_discovery_engine_widget",
        label_visibility="collapsed",
        on_change=_save_engine,
    )

    st.divider()
    st.markdown("#### AI Model Configuration")
    st.caption("Choose which AI model powers each stage. The defaults are recommended for most runs.")
    with st.expander("Customize AI Models", expanded=False):
        _model_selectbox("grok",       "Grok — Research")
        st.divider()
        _model_selectbox("gemini",     "Gemini — Discovery")
        st.divider()
        _model_selectbox("analyst",    "Claude — Analyst")
        st.divider()
        _model_selectbox("copywriter", "Claude — Copywriter")
        st.divider()
        st.markdown("**Exa — LinkedIn Intel**")
        st.caption("Fixed — no model selection  \n~$0.005 per exec search")
        st.divider()
        st.markdown("**Apollo — Contact Enrichment**")
        st.caption("Fixed — no model selection  \n$0.49/credit (bulk enrich)")

    st.divider()
    st.markdown("#### Google Sheet")
    _sheet_url = _get_sheet_url()
    if _sheet_url:
        st.markdown(f"**[Open Google Sheet ↗]({_sheet_url})**")
    else:
        st.markdown(f"**Sheet:** `{config.GOOGLE_SHEET_NAME}`")
    st.caption(f"Hot leads tab: *{config.GOOGLE_WORKSHEET_NAME}*")
    st.caption(f"Cold leads tab: *{config.GOOGLE_COLD_WORKSHEET_NAME}*")

    st.divider()
    st.markdown("#### System Status")
    st.caption("Green = connected and ready. Red = key missing — contact your administrator.")
    with st.expander("API Status", expanded=True):
        _api_status("XAI_API_KEY",           "Grok (web research)")
        _api_status("ANTHROPIC_API_KEY",     "Claude (scoring & outreach)")
        _api_status("OPENAI_API_KEY",        "OpenAI GPT-4o (discovery)")
        _api_status("EXA_API_KEY",           "Exa (LinkedIn intel)")
        _api_status("APOLLO_MASTER_API_KEY", "Apollo (contact search)")
        _api_status("APOLLO_API_KEY",        "Apollo (contact enrichment)")
        _api_status("GEMINI_API_KEY",        "Gemini (discovery)")


# ---------------------------------------------------------------------------
# History page
# ---------------------------------------------------------------------------

def render_history_page() -> None:
    st.subheader("History")
    bu = st.session_state.get("selected_bu", config.BU_DEFAULT)
    tab_runs, tab_usage = st.tabs(["Run History", "Usage Cost Log"])

    with tab_runs:
        st.caption(f"Recent runs · BU={bu}")
        render_history_sidebar(bu_filter=bu)

    with tab_usage:
        try:
            history = load_usage_history(max_runs=20)
            if history:
                rows = [
                    {
                        "Date":       h.get("timestamp", "")[:16],
                        "Query":      h.get("query", "")[:40],
                        "Prospects":  h.get("prospects", 0),
                        "Total $":    f"{h.get('total_cost_usd', 0):.4f}",
                        "$/prospect": f"{h.get('cost_per_prospect', 0):.4f}",
                    }
                    for h in history
                ]
                st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
            else:
                st.caption("No usage history yet.")
        except Exception as exc:
            st.caption(f"Could not load usage history: {exc}")


# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Model override helper — patches config at run time, no permanent changes
# ---------------------------------------------------------------------------

def _apply_model_overrides() -> None:
    for role, attr in [
        ("grok",       "GROK_SCOUT_MODEL"),
        ("gemini",     "GEMINI_DISCOVERY_MODEL"),
        ("analyst",    "CLAUDE_ANALYST_MODEL"),
        ("copywriter", "CLAUDE_COPYWRITER_MODEL"),
    ]:
        idx = st.session_state.get(f"model_sel_{role}", 0)
        options = config.MODEL_OPTIONS.get(role, [])
        if options and idx < len(options):
            setattr(config, attr, options[idx]["model"])

    # Discovery engine — check all possible sources in priority order
    engine = (
        st.session_state.get("_discovery_engine_saved") or
        st.session_state.get("_discovery_engine_widget") or
        config.DISCOVERY_ENGINE
    )
    config.DISCOVERY_ENGINE = engine


def _render_help() -> None:
    st.markdown(
        """
        <style>
        [data-testid="stMarkdownContainer"] p,
        [data-testid="stMarkdownContainer"] li {
            font-weight: 300 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.subheader("Help & Reference")
    st.caption("Everything you need to know to get the most out of Lead Scout.")

    help_how, help_glossary, help_faq = st.tabs([
        "How to Use", "Glossary", "FAQ"
    ])

    # ---- HOW TO USE ----
    with help_how:
        st.markdown("## How Lead Scout Works")
        st.markdown(
            "Lead Scout has three tools. Use the tabs at the top of the page to switch between them. "
            "Pick the one that matches what you're trying to do:"
        )

        with st.expander("**Find Companies** — I want to discover new prospects I haven't targeted yet", expanded=True):
            st.markdown("""
**Use this when:** You want to find companies in the market for Accedo's OTT platform services that you haven't identified yet.

**Step 1 — Tell Lead Scout what you're looking for**
- Tick one or more company types (verticals) — e.g. Sports, News, Faith
- Select the buying signals you want to target — e.g. "Platform migration", "Funding round"
- Optionally add any extra context in the text field — e.g. "currently on 24i", "just hired a new CTO"
- Click **Build My Search**

**Step 2 — Review your search brief**
Lead Scout builds a research brief from your selections. You can read and edit it before running the search. When you're happy, click **Find Companies**.

*This step takes 1–2 minutes per vertical selected.*

**Step 3 — Pick which companies to research**
Lead Scout returns a list of companies matching your brief. Each one has a reason why it was included. Select up to 5 and click **Research Selected Companies**.

*Deep research takes 2–4 minutes per company.*

**Step 4 — Choose which prospects to qualify**
After research, each company gets an Opportunity Score (0–100) and a verdict (HOT, WARM, or COLD). HOT and WARM prospects are pre-checked.

Qualifying a prospect:
- Finds key decision makers via Apollo (contact database)
- Enriches with LinkedIn intelligence via Exa
- Runs a final scoring pass with Claude

Prospects you don't select are archived to your Cold Leads tab without contact lookup.

**Step 5 — Choose who gets a personalised email draft**
For each qualified prospect, Lead Scout drafts two personalised outreach emails:
- One for the **Visionary** (strategic decision maker — CEO, Chief Digital Officer)
- One for the **Operator** (technical owner — VP Engineering, Head of Product)

Select the prospects you want email drafts for and click **Draft Outreach with Opus**.

**Results are automatically saved to your Google Sheet** (unless Preview Mode is on).
            """)

        with st.expander("**Enrich Companies** — I already know who I want to target", expanded=False):
            st.markdown("""
**Use this when:** You have a list of specific companies and want to find decision makers and buying signals without going through the full discovery flow.

**Step 1 — Enter company names**
Type company names separated by commas, or paste one per line. You can also upload a CSV with a Company column.

**Step 2 — Estimate cost (optional)**
Click **Estimate Cost** to see how many companies are already in the cache (free) vs how many need a fresh lookup (costs credits).

**Step 3 — Run enrichment**
Click **Enrich Companies**. For each company, Lead Scout returns:
- Key decision makers (name, title, email, LinkedIn)
- Recent OTT buying signals
- Intent topics (what they're currently researching)

Results are cached for 90 days. If you look up the same company again within that window, it's instant and free.

**Tip:** Use **Preview** mode first to see what's already cached before spending credits.
            """)

        with st.expander("**Account Intelligence** — I want to re-research my tracked accounts", expanded=False):
            st.markdown("""
**Use this when:** You have accounts already saved in your Accounts list and want fresh intelligence on them — without going through the search step.

**Step 1 — Import accounts (first time only)**
If you haven't added accounts yet, expand the **Import Accounts from CSV** section and upload a spreadsheet. Required columns: Company, Domain.

**Step 2 — Load and review your accounts**
Click **Load Accounts** to see your tracked accounts for the current region. Accounts highlighted in red haven't been researched yet. Yellow means the last run was over 30 days ago.

**Step 3 — Run intelligence**
Click **Run Account Intelligence**. Lead Scout researches each account directly (no search step) and returns scored results, which are saved to your Google Sheet.
            """)

    # ---- GLOSSARY ----
    with help_glossary:
        st.markdown("## Glossary of Terms")

        col_a, col_b = st.columns(2)

        with col_a:
            st.markdown("#### Scoring & Verdicts")
            st.markdown("""
**Opportunity Score (0–100)**
How likely a company is to be in the market for Accedo's services right now, based on publicly available signals. Higher = stronger buying intent.
- 🔥 **HOT (70+)** — Strong, time-sensitive buying signals. Prioritise for immediate outreach.
- 🌡️ **WARM (50–69)** — Relevant signals but less urgent. Worth pursuing — keep on your radar.
- ❄️ **COLD (below 50)** — Weak or no signals right now. Archived to your Cold Leads tab but not deleted.

**Causal Inflection**
The specific event creating buying urgency right now — e.g. *"Just migrated off Brightcove, contract ends Q1 2026"* or *"New CTO hired from Netflix in September."*

**Transition Gap / Timer**
A window of time when the company is most likely making a platform decision — e.g. *"6–18 months post-acquisition."*

**Opportunity Type**
The category of opportunity — e.g. new build, platform migration, redesign, DTC pivot.
            """)

            st.markdown("#### Tools & AI")
            st.markdown("""
**Grok**
The AI (built by xAI, the team behind X/Twitter) that reads the web to research each company. It finds recent news, job postings, press releases, and earnings calls to assess buying intent.

**Claude (Sonnet / Opus)**
Anthropic's AI. Sonnet scores and qualifies prospects. Opus drafts personalised outreach emails.

**Gemini**
Google's AI. Used in the brief enrichment step to sharpen your research brief before searching.

**Apollo**
A B2B contact database with millions of verified contacts. Lead Scout uses it to find decision makers and their email addresses.

**Exa**
A search tool that finds LinkedIn intelligence and executive profiles to supplement Apollo results.

**Cached / Cache**
A saved result from a previous enrichment run. If a company was enriched within the last 90 days, Lead Scout uses the saved result instantly at no cost, rather than re-running the lookup.
            """)

        with col_b:
            st.markdown("#### People")
            st.markdown("""
**Visionary**
The executive who sets strategic direction — typically a CEO, Chief Digital Officer, or SVP Strategy. Cares about growth, market position, and competitive differentiation.

**Operator**
The person who owns the day-to-day platform — typically a VP Engineering, Head of Product, or CTO. Cares about solving technical problems and delivery timelines.

**Apollo Contact**
A contact found in the Apollo database — usually a senior leader with confirmed email and LinkedIn profile.
            """)

            st.markdown("#### Settings & Modes")
            st.markdown("""
**Business Unit (BU / Region)**
The Accedo region this lead is assigned to:
- **NAM** — North America (US, Canada, Mexico)
- **E&L** — Europe & Latin America
- **APAC** — Asia Pacific

All results from a session are tagged with the active region.

**Preview Mode**
Runs all research and scoring but does not save anything to your Google Sheet. Use this to preview results before committing to a full run. Note: AI research still runs (and uses credits) in Preview Mode.

**Objection Counters**
Pre-written responses to the most common sales pushbacks — *"We're building in-house"*, *"We already have a vendor"*, *"Budget isn't there right now."*

**Salesforce Note**
A pre-formatted note you can copy and paste directly into Salesforce after your initial outreach call.

**Run History**
The last 50 runs for your region, shown in the sidebar. Click any entry to view its full results without re-running.
            """)

    # ---- FAQ ----
    with help_faq:
        st.markdown("## Frequently Asked Questions")

        with st.expander("Why is a company scored COLD if I know they're a good fit?"):
            st.markdown("""
Scores are based on **publicly available signals only**. If a company is privately negotiating, in a quiet period, or hasn't made public announcements yet, the score may be lower than your intuition suggests.

You can still select and fully research COLD companies — the score is a starting point for prioritisation, not a veto. Simply check them when choosing prospects to qualify.
            """)

        with st.expander("How long does each step take?"):
            st.markdown("""
| Step | Typical time |
|---|---|
| Building your search brief | < 30 seconds |
| Finding companies (per vertical selected) | 1–2 minutes |
| Deep research per company (Grok) | 2–4 minutes |
| Qualifying a prospect (Apollo + Exa + Claude) | 1–2 minutes per company |
| Drafting outreach emails (Opus) | 1–2 minutes per company |

For 3 companies across 2 verticals, expect roughly **15–25 minutes** for the full pipeline.
            """)

        with st.expander("Does Preview Mode charge credits?"):
            st.markdown("""
**Yes, partially.** Preview Mode still runs AI research (Grok, Claude, Gemini) — so it does consume API credits. What it **doesn't** do is write results to your Google Sheet.

The exception is **Company Enrichment Preview** — that only checks the cache and makes no API calls at all, so it's completely free.
            """)

        with st.expander("Why did no companies appear after I searched?"):
            st.markdown("""
This can happen for a few reasons:

1. **Signals too specific** — try selecting more signals or broadening your verticals
2. **Region too narrow** — check that your region (BU) is set correctly in the sidebar
3. **Brief too restrictive** — read the generated brief in Step 2 and simplify it before searching
4. **API issue** — check the System Status panel in the sidebar (all lights should be green)

You can also edit the research brief directly before clicking Find Companies to make it broader or more targeted.
            """)

        with st.expander("What's the difference between Find Companies and Enrich Companies?"):
            st.markdown("""
- **Find Companies** starts from scratch — Lead Scout searches the web for companies that match your criteria. Use this for prospecting.
- **Enrich Companies** starts from a list you already have — you provide the company names, and Lead Scout looks up contacts and signals. Use this when you know who you want to target.
            """)

        with st.expander("What happens to companies I don't select for qualification?"):
            st.markdown("""
If you skip a company during the qualification step (Step 4), it's automatically archived to your **Cold Leads** tab in Google Sheets — without any contact lookup or email draft. It won't be lost, and you can still find it later if circumstances change.
            """)

        with st.expander("What does 'cached' mean in Company Enrichment?"):
            st.markdown("""
When Lead Scout enriches a company, it saves the results for **90 days**. If you or a colleague looks up the same company again within that window, Lead Scout uses the saved result instantly — no API calls, no cost.

You can see which companies are cached before running enrichment by using the **Preview** checkbox.
            """)

        with st.expander("Can I edit the outreach emails before using them?"):
            st.markdown("""
Yes. Once drafts are generated, they appear in editable text boxes inside each company's result card. You can edit directly in the browser. However, changes are not saved back to Sheets — copy the edited text before closing the tab.
            """)


# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Main routing — top nav
# ---------------------------------------------------------------------------

active_page = render_topnav()
bu = st.session_state.get("selected_bu", config.BU_DEFAULT)

if active_page == "help":
    _render_help()

elif active_page == "history":
    if st.session_state.get("view_mode") == "history":
        row = st.session_state.get("history_view", {})
        if row:
            col1, col2 = st.columns([1, 5])
            with col1:
                if st.button("← Back"):
                    st.session_state["view_mode"] = "run"
                    st.rerun()
            with col2:
                st.caption(
                    f"Viewing historical record: **{row.get('Company', '')}** "
                    f"· {row.get('Timestamp', '')} · BU={row.get('BU', '—')}"
                )
            st.divider()
            render_history_card(row)
    else:
        render_history_page()

elif active_page == "settings":
    render_settings_page()

elif active_page == "find":
    col_mode, col_engine = st.columns(2)
    with col_mode:
        _run_mode = st.selectbox(
            "Run Mode",
            options=["Live — save results to Google Sheet", "Preview — research only, no save"],
            index=1 if st.session_state.get("is_dry_run", False) else 0,
            key="dry_run_select_find",
            help="Live mode saves all results. Preview runs all AI research but skips the save step (still uses credits).",
        )
        is_dry_run = _run_mode.startswith("Preview")
        st.session_state["is_dry_run"] = is_dry_run
        if is_dry_run:
            st.warning("Preview Mode — results will not be saved to your Google Sheet")
    with col_engine:
        _engine = st.selectbox(
            "Discovery Engine",
            options=["grok", "openai", "claude"],
            index=["grok", "openai", "claude"].index(
                st.session_state.get("discovery_engine_find", config.DISCOVERY_ENGINE)
            ),
            format_func=lambda x: {
                "grok":   "Grok — fast (~60s/vertical)",
                "openai": "GPT-4o + Web Search — recommended",
                "claude": "Claude + Web Search",
            }[x],
            key="discovery_engine_find",
        )
        config.DISCOVERY_ENGINE = _engine


    from prompts.gemini_scorer import RANDOM_CONFIGS

    VERTICALS = [
        "Sports", "News", "Entertainment", "Faith", "Fitness",
        "Education", "Audio", "In-Vehicle", "Pay TV", "Multi-Vertical", "Micro-drama", "FAST", "Other",
    ]

    SIGNALS = {
        "Platform & Technology": [
            "First CTV build",
            "CTV ambition",
            "Smart TV app launch",
            "Mobile-only",
            "Youtube transition to OTT",
            "Web apps looking for native",
            "Platform migration",
            "Stranded vendor customer",
            "Video player overhaul",
            "App store complaints",
            "SSAI/DRM change",
        ],
        "Product & Design": [
            "App redesign",
            "Platform consolidation",
            "New product/UX leadership",
            "Rebrand with digital implications",
        ],
        "Hiring": [
            "Hiring: OTT/CTV engineers",
            "Hiring: Front-end engineers",
            "Hiring: QA automation",
            "Hiring: UX/UI designers",
            "Hiring: Product managers",
            "Hiring: TPMs / delivery leads",
        ],
        "Commercial & Growth": [
            "Rights without platform",
            "FAST/AVOD launch",
            "Funding round",
            "Market expansion",
            "New streaming partnership",
            "DTC pivot",
            "M&A / platform unification",
            "Social-first publisher going owned OTT",
            "Gaming company entering video",
            "Post-acquisition integration",
        ],
        "Risk & Distress (whats affecting them)": [
            "RFP activity",
            "Leadership change in digital/streaming",
            "Competitor launched on CTV first",
        ],
    }

    # ----------------------------------------------------------------
    # STAGE A — Intake form (st.form prevents per-widget reruns)
    # ----------------------------------------------------------------
    st.markdown("#### Step 1 — Tell Lead Scout what you're looking for")
    st.caption("Select the type of company and what buying signals you want to target. Lead Scout will search the web and find matching prospects.")
    if st.button("Randomize Query Selection", key="randomize_btn", type="primary",
                 help="Auto-fill with a random discovery scenario"):
        import random as _random
        cfg = _random.choice(RANDOM_CONFIGS)

        st.session_state["form_verticals"] = cfg["verticals"]
        st.session_state["form_signals"]   = cfg["signals"]
        st.session_state["form_context"]   = cfg["context"]

        _bu_label = {
            "NAM": "North America (US, Canada, Mexico)",
            "E&L": "Europe or Latin America",
            "APAC": "Asia Pacific",
        }.get(bu, bu)
        _new_brief = (
            f"Find Tier 1, Tier 2, and ambitious Tier 3 {', '.join(cfg['verticals'])} companies "
            f"headquartered in {_bu_label} "
            f"showing these OTT buying signals: {', '.join(cfg['signals'])}."
        )
        if cfg.get("context"):
            _new_brief += f"\n\nAdditional context: {cfg['context']}"
        st.session_state["brief_text_area"]     = _new_brief
        st.session_state["last_selection_hash"] = None
        st.session_state["brief_used_gemini"]   = False

        for key in ["sweep_result", "grok_prospects", "enrichment_selections"]:
            st.session_state.pop(key, None)
        # Bump form_version so the form re-mounts fresh with the new defaults
        st.session_state["form_version"] = st.session_state.get("form_version", 0) + 1
        st.rerun()

    with st.form(f"discovery_form_{st.session_state.get('form_version', 0)}"):
        st.caption("**What type of company are you targeting?**")
        selected_verticals = []
        v_cols = st.columns(4)
        for i, v in enumerate(VERTICALS):
            default = v in st.session_state.get("form_verticals", [])
            if v_cols[i % 4].checkbox(v, value=default, key=f"v_{v}"):
                selected_verticals.append(v)

        st.divider()
        st.caption("**What buying signals are you looking for?**")
        selected_signals = []
        for group, group_signals in SIGNALS.items():
            picked = st.multiselect(
                group,
                options=group_signals,
                default=[s for s in st.session_state.get("form_signals", [])
                         if s in group_signals],
                key=f"ms_{group}",
            )
            selected_signals.extend(picked)

        st.divider()
        st.caption("**Anything specific to focus on?** *(optional — add context like a specific competitor, technology, or timeline)*")
        context_val = st.text_input(
            "",
            value=st.session_state.get("form_context", ""),
            placeholder="e.g. stranded on 24i, just acquired X, mobile-only right now…",
            key="form_context_input",
            label_visibility="collapsed",
        )

        form_submitted = st.form_submit_button(
            "Build My Search",
            use_container_width=True,
        )

    # Process form submission — runs once when rep clicks Build Brief
    if form_submitted:
        if not selected_verticals or not selected_signals:
            st.warning("Select at least one vertical and one signal.")
        else:
            st.session_state["form_verticals"] = selected_verticals
            st.session_state["form_signals"]   = selected_signals
            st.session_state["form_context"]   = context_val

            bu_label = {
                "NAM":  "North America (US, Canada, Mexico)",
                "E&L":  "Europe or Latin America",
                "APAC": "Asia Pacific",
            }.get(bu, bu)

            auto_brief = (
                f"Find Tier 1, Tier 2, and ambitious Tier 3 {', '.join(selected_verticals)} companies "
                f"headquartered in {bu_label} "
                f"showing these OTT buying signals: {', '.join(selected_signals)}."
            )
            if context_val.strip():
                auto_brief += f"\n\nAdditional context: {context_val.strip()}"

            # Enrich with Gemini — fast call, falls back silently if it fails
            final_brief = auto_brief
            used_gemini = False

            # Create RunUsage now so Gemini tokens are tracked from the start
            from utils.usage_tracker import RunUsage as _RunUsage
            _brief_usage = _RunUsage(", ".join(selected_verticals))
            _brief_usage.start_prospect("_brief_enrichment")

            try:
                _gemini_key = (st.secrets.get("GEMINI_API_KEY", "") or
                               config.GEMINI_API_KEY or
                               os.environ.get("GEMINI_API_KEY", ""))
            except Exception:
                _gemini_key = config.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY", "")

            if _gemini_key:
                try:
                    from tools.gemini import enrich_brief
                    enrichment = enrich_brief(
                        auto_brief=auto_brief,
                        verticals=selected_verticals,
                        signals=selected_signals,
                        bu=bu,
                        usage_tracker=_brief_usage,
                    )
                    final_brief = enrichment.get("enriched_brief", auto_brief)
                    used_gemini = enrichment.get("used_gemini", False)
                except Exception as _e:
                    st.warning(f"Gemini enrichment debug: {_e}")

            _brief_usage.end_prospect()
            st.session_state["brief_run_usage"] = _brief_usage

            st.session_state["brief_text_area"]     = final_brief
            st.session_state["brief_used_gemini"]   = used_gemini
            st.session_state["last_selection_hash"] = hash((
                tuple(sorted(selected_verticals)),
                tuple(sorted(selected_signals)),
                context_val.strip(), bu,
            ))
            for key in ["sweep_result", "grok_prospects", "enrichment_selections"]:
                st.session_state.pop(key, None)

    # ----------------------------------------------------------------
    # STAGE B — Brief display + Find Companies (shown after form submit)
    # ----------------------------------------------------------------
    if st.session_state.get("brief_text_area"):
        st.divider()
        used_gemini = st.session_state.get("brief_used_gemini", False)
        st.caption(
            "**Step 2 — Review your search** — you can edit this before searching"
            + (" · refined by Gemini" if used_gemini else "")
        )

        edited_brief = st.text_area(
            "",
            value=st.session_state.get("brief_text_area", ""),
            height=160,
            key="brief_text_area",
            label_visibility="collapsed",
        )

        sweep_btn = st.button(
            "Find Companies",
            use_container_width=True,
            type="primary",
            key="sweep_btn",
            disabled=not edited_brief.strip(),
        )

        # ---- Discovery sweep ----
        if sweep_btn:
            _apply_model_overrides()
            for key in ["sweep_result", "company_selections",
                        "grok_prospects", "enrichment_selections"]:
                st.session_state.pop(key, None)

            st.info("Grok is scanning the web — this takes 60–90 seconds per vertical…")
            with st.status(
                "Searching for companies…", expanded=True
            ) as status:
                selected_verticals_for_sweep = st.session_state.get("form_verticals", [])
                total_verticals = len(selected_verticals_for_sweep) or 1

                if total_verticals > 1:
                    if config.DISCOVERY_ENGINE == "claude":
                        st.write(f"Running {total_verticals} vertical sweeps with Claude — pausing 60s between each to respect rate limits…")
                    else:
                        st.write(f"Running {total_verticals} vertical sweeps in sequence…")
                v_placeholders = {}
                for v in selected_verticals_for_sweep:
                    v_placeholders[v] = st.empty()
                    v_placeholders[v].markdown(f"**{v}** · queued")

                def _on_v_start(vertical, idx, total):
                    if vertical in v_placeholders:
                        v_placeholders[vertical].markdown(
                            f"**{vertical}** · searching… *({idx}/{total})*"
                        )

                def _on_v_done(vertical, companies, idx, total):
                    if vertical in v_placeholders:
                        v_placeholders[vertical].markdown(
                            f"**{vertical}** · {len(companies)} found"
                        )

                try:
                    sweep = main.run_discovery_sweep(
                        edited_brief,
                        bu=bu,
                        signals=st.session_state.get("form_signals", []),
                        verticals=selected_verticals_for_sweep,
                        director=get_current_user() or "",
                        usage=st.session_state.get("brief_run_usage"),
                        on_vertical_start=_on_v_start,
                        on_vertical_done=_on_v_done,
                    )
                    st.session_state["sweep_result"]  = sweep
                    st.session_state["sweep_brief"]   = edited_brief
                    st.session_state["sweep_usage"]   = sweep.get("usage")
                    st.session_state["sweep_sheets"]  = sweep.get("sheets")
                    companies = sweep.get("companies", [])
                    status.update(
                        label=f"Found {len(companies)} companies — select which to research below",
                        state="complete", expanded=True,
                    )
                    _sweep_u = sweep.get("usage")
                    if _sweep_u:
                        try:
                            _sweep_u.finish()
                            st.session_state["sweep_usage_summary"] = _sweep_u.summary()
                        except Exception:
                            pass
                except Exception as exc:
                    status.update(label="Error", state="error", expanded=True)
                    st.error(f"**Error:** {exc}")
                    st.exception(exc)

            # Render sweep cost outside the collapsible status block
            if st.session_state.get("sweep_usage_summary"):
                render_usage_panel(st.session_state["sweep_usage_summary"])

    # ----------------------------------------------------------------
    # STAGE C — Company selection
    # ----------------------------------------------------------------
    sweep_result = st.session_state.get("sweep_result")

    if sweep_result:
        companies = sweep_result.get("companies", [])
        search_summary = sweep_result.get("search_summary", "")

        if not companies:
            st.warning(
                "No companies found. Try adjusting your brief "
                "or selecting different signals."
            )
        else:
            st.divider()
            st.subheader(f"{len(companies)} companies found")
            if search_summary:
                st.caption(search_summary)
            st.caption(
                "**Step 3 — Pick which companies to research.** "
                "Select up to 5. Lead Scout will read the web for each one and score its opportunity — "
                "results appear as each finishes."
            )

            # Initialise selections — all unchecked by default
            if "company_selections" not in st.session_state:
                st.session_state["company_selections"] = {
                    c.get("name", ""): False for c in companies
                }

            with st.form("company_selection_form"):
                for company in companies:
                    name        = company.get("name", "")
                    evidence    = company.get("evidence", "")
                    signal_type = company.get("signal_type", "")
                    source_url  = company.get("source_url", "")
                    hq          = company.get("hq_country", "")

                    col_check, col_info = st.columns([1, 10])
                    with col_check:
                        current = st.session_state["company_selections"].get(name, False)
                        checked = st.checkbox(
                            "", value=current,
                            key=f"sel_{name}",
                            label_visibility="collapsed",
                        )
                    with col_info:
                        name_md = f"[{name}]({source_url})" if source_url else name
                        meta    = f" · {hq}" if hq else ""
                        badge   = f"`{signal_type}`" if signal_type else ""
                        st.markdown(f"**{name_md}**{meta}  {badge}")
                        if evidence:
                            st.caption(evidence)

                research_submitted = st.form_submit_button(
                    "Research Selected Companies",
                    use_container_width=True,
                    type="primary",
                )

            # Process selections after form submit
            if research_submitted:
                # Collect checked companies from form widget state
                selected_companies = [
                    c for c in companies
                    if st.session_state.get(f"sel_{c.get('name', '')}", False)
                ]
                # Update company_selections session state
                for c in companies:
                    n = c.get("name", "")
                    st.session_state["company_selections"][n] = st.session_state.get(f"sel_{n}", False)

                selected_count = len(selected_companies)
                if selected_count == 0:
                    st.warning("Select at least one company above.")
                else:
                    st.caption(f"{selected_count} selected for deep research")
                    _apply_model_overrides()
                    st.session_state.pop("grok_prospects", None)
                    st.session_state.pop("enrichment_selections", None)

                    total  = selected_count
                    brief  = st.session_state.get("sweep_brief", "")
                    run_id = sweep_result.get("run_id", "")

                    st.divider()
                    st.subheader(f"Researching {total} {'company' if total == 1 else 'companies'}…")

                    placeholders = {}
                    for company in selected_companies:
                        name = company.get("name", "")
                        placeholders[name] = st.empty()
                        placeholders[name].markdown(f"**{name}** · queued")

                    completed_prospects = []

                    def _on_start(name, idx, total):
                        placeholders[name].markdown(
                            f"**{name}** · researching… *({idx}/{total})*"
                        )

                    def _on_done(name, prospect, idx, total):
                        score   = prospect.get("opportunity_score") or 0
                        verdict = "HOT" if score >= 70 else "WARM" if score >= 50 else "COLD"
                        opp     = prospect.get("opportunity_type", "")
                        err     = prospect.get("error")
                        if err:
                            placeholders[name].markdown(f"**{name}** · research failed — {err}")
                        else:
                            placeholders[name].markdown(
                                f"**{name}** · **{score}** · {verdict}"
                                + (f" · *{opp}*" if opp else "")
                            )
                        completed_prospects.append(prospect)

                    try:
                        _sweep_usage  = st.session_state.get("sweep_usage")
                        _sweep_sheets = st.session_state.get("sweep_sheets")

                        with st.spinner("Grok deep research running — 2–4 minutes per company…"):
                            grok_result = main.run_grok_only(
                                query=brief,
                                bu=bu,
                                selected_companies=selected_companies,
                                run_id=run_id,
                                on_company_start=_on_start,
                                on_company_done=_on_done,
                                usage=_sweep_usage,
                                sheets=_sweep_sheets,
                            )

                        all_prospects = grok_result.get("prospects", [])
                        st.session_state["grok_prospects"]  = all_prospects
                        st.session_state["grok_run_id"]     = run_id
                        st.session_state["grok_query"]      = brief
                        st.session_state["grok_usage"]      = grok_result.get("usage")
                        st.session_state["grok_sheets"]     = grok_result.get("sheets")
                        st.session_state["grok_discovery"]  = {
                            "discovery_ran": True,
                            "gemini_ran":    True,
                            "all_found":     [],
                            "selected":      [],
                            "rejected":      [],
                            "search_strings": [],
                        }

                        _interim_usage = grok_result.get("usage")
                        if _interim_usage:
                            _interim_snapshot = _interim_usage.summary()
                            st.session_state["grok_interim_usage"] = _interim_snapshot

                        st.success(
                            f"Research complete — "
                            f"{len(all_prospects)} prospects ready for enrichment below"
                        )
                        _browser_notify(
                            "Accedo Lead Scout — Research complete",
                            f"{len(all_prospects)} prospect(s) ready for enrichment",
                        )
                        _snapshot = st.session_state.get("grok_interim_usage")
                        if _snapshot:
                            render_usage_panel(_snapshot)

                    except Exception as exc:
                        st.error(f"**Research error:** {exc}")
                        st.exception(exc)

    # ----------------------------------------------------------------
    # ----------------------------------------------------------------
    # STAGE E — Enrichment selection (Apollo + Exa + Sonnet)
    # ----------------------------------------------------------------
    grok_prospects = st.session_state.get("grok_prospects", [])

    if grok_prospects:
        st.divider()
        st.subheader("Step 4 — Choose which prospects to qualify fully")
        st.caption(
            "HOT and WARM prospects are pre-checked. "
            "Qualifying a prospect looks up their key decision makers (via Apollo & LinkedIn), "
            "then scores them with Claude. "
            "Companies you don't select are archived to your Cold Leads tab without any contact lookup."
        )

        if "enrichment_selections" not in st.session_state:
            st.session_state["enrichment_selections"] = {
                p.get("name", ""): (p.get("opportunity_score") or 0) >= 50
                for p in grok_prospects
            }

        with st.form("enrichment_selection_form"):
            for prospect in grok_prospects:
                name     = prospect.get("name", "")
                score    = prospect.get("opportunity_score") or 0
                verdict  = "HOT" if score >= 70 else "WARM" if score >= 50 else "COLD"
                opp_type = prospect.get("opportunity_type", "")
                gap      = prospect.get("transition_gap_timer", "")

                col_check, col_score, col_info = st.columns([1, 2, 8])
                with col_check:
                    current = st.session_state["enrichment_selections"].get(name, False)
                    st.checkbox(
                        "", value=current,
                        key=f"enrich_{name}",
                        label_visibility="collapsed",
                    )
                with col_score:
                    st.markdown(_score_bar_html(score), unsafe_allow_html=True)
                    st.markdown(_verdict_chip(verdict), unsafe_allow_html=True)
                with col_info:
                    detail = f"*{opp_type}*" if opp_type else ""
                    if gap:
                        detail += f" · {gap}"
                    st.markdown(
                        f"**{name}**  \n{detail}" if detail else f"**{name}**"
                    )

            enrich_submitted = st.form_submit_button(
                "Qualify Selected",
                type="primary",
                use_container_width=True,
            )

        if enrich_submitted:
            enrichment_names = {
                p.get("name", "") for p in grok_prospects
                if st.session_state.get(f"enrich_{p.get('name', '')}", False)
            }
            for p in grok_prospects:
                n = p.get("name", "")
                st.session_state["enrichment_selections"][n] = n in enrichment_names

            enrichment_count = len(enrichment_names)
            if enrichment_count == 0:
                st.warning("⬆️ Select at least one company above.")
            else:
                _apply_model_overrides()
                _grok_usage  = st.session_state.get("grok_usage")
                _grok_sheets = st.session_state.get("grok_sheets") or _get_sc()
                query        = st.session_state.get("grok_query", "")
                run_id       = st.session_state.get("grok_run_id", "")

                qualified_results = []
                unselected_names  = {
                    p.get("name", "") for p in grok_prospects
                    if p.get("name", "") not in enrichment_names
                }

                # Archive unselected immediately
                for prospect in grok_prospects:
                    name = prospect.get("name", "")
                    if name in unselected_names and not is_dry_run:
                        try:
                            stub_analyst = {
                                "refined_score": prospect.get("opportunity_score", 0),
                                "verdict": "COLD",
                                "write_to_sheet": False,
                                "skip_reason": "Not selected for qualification by user",
                                "top_entry_point": "",
                                "score_delta_reasoning": "Archived by user",
                                "copywriter_brief": "",
                                "transition_gap_confirmed": "",
                                "key_risk_if_no_action": "",
                            }
                            stub_emails = {
                                "visionary_email": {"subject_line": f"{name} — archived", "body": "Not selected for qualification."},
                                "operator_email": {"subject_line": "", "body": ""},
                            }
                            _grok_sheets.append_lead(
                                prospect, stub_analyst, stub_emails,
                                contact=None, query=query,
                                is_cold=True, bu=bu,
                            )
                        except Exception:
                            pass

                # Qualify selected companies
                placeholders = {
                    p.get("name", ""): st.empty()
                    for p in grok_prospects
                    if p.get("name", "") in enrichment_names
                }
                for name in enrichment_names:
                    placeholders[name].markdown(f"**{name}** · queued")

                st.info("Running Apollo → Exa → Sonnet qualification…")

                for prospect in grok_prospects:
                    name = prospect.get("name", "")
                    if name not in enrichment_names:
                        continue
                    placeholders[name].markdown(f"**{name}** · qualifying…")
                    try:
                        result = main.qualify_prospect_only(
                            prospect=prospect,
                            sheets=_grok_sheets,
                            query=query,
                            run_id=run_id,
                            dry_run=is_dry_run,
                            usage=_grok_usage,
                            bu=bu,
                        )
                        score   = result.get("refined_score") or 0
                        verdict = result.get("verdict", "COLD")
                        v_icon  = "" if verdict == "HOT" else "" if verdict == "WARM" else ""
                        entry   = result.get("analyst", {}).get("top_entry_point", "")[:60]
                        placeholders[name].markdown(
                            f"**{name}** · **{score}** · {verdict}"
                            + (f"  \n*{entry}*" if entry else "")
                        )
                        qualified_results.append(result)
                    except Exception as exc:
                        placeholders[name].markdown(f"**{name}** · error: {exc}")

                st.session_state["qualified_results"] = qualified_results
                st.session_state["qualify_run_id"]    = run_id
                st.session_state["qualify_sheets"]    = _grok_sheets
                st.session_state["qualify_usage"]     = _grok_usage

    # ----------------------------------------------------------------
    # STAGE F — Outreach selection (Opus)
    # ----------------------------------------------------------------
    qualified_results = st.session_state.get("qualified_results", [])
    hot_warm = [r for r in qualified_results if r.get("verdict") in ("HOT", "WARM")]

    if qualified_results:
        st.divider()
        st.subheader("Step 5 — Choose who gets a personalised email draft")
        st.caption(
            "Lead Scout will write personalised outreach emails for each prospect you select here — "
            "one for the strategic decision maker and one for the technical owner. "
            "Prospects you skip will still be saved to Sheets, just without email drafts."
        )

        if "outreach_selections" not in st.session_state:
            st.session_state["outreach_selections"] = {
                r.get("company", ""): r.get("verdict") in ("HOT", "WARM")
                for r in qualified_results
            }

        with st.form("outreach_selection_form"):
            for result in qualified_results:
                name    = result.get("company", "")
                score   = result.get("refined_score") or 0
                verdict = result.get("verdict", "COLD")
                entry   = result.get("analyst", {}).get("top_entry_point", "")
                brief   = result.get("analyst", {}).get("copywriter_brief", "")

                col_check, col_score, col_info = st.columns([1, 2, 8])
                with col_check:
                    current = st.session_state["outreach_selections"].get(name, False)
                    st.checkbox(
                        "", value=current,
                        key=f"outreach_{name}",
                        label_visibility="collapsed",
                    )
                with col_score:
                    st.markdown(_score_bar_html(score), unsafe_allow_html=True)
                    st.markdown(_verdict_chip(verdict), unsafe_allow_html=True)
                with col_info:
                    st.markdown(f"**{name}**")
                    if entry:
                        st.caption(f"Entry point: {entry}")
                    if brief:
                        st.caption(brief[:200])

            outreach_submitted = st.form_submit_button(
                "Draft Outreach",
                type="primary",
                use_container_width=True,
            )

        if outreach_submitted:
            _apply_model_overrides()
            outreach_names = {
                r.get("company", "") for r in qualified_results
                if st.session_state.get(f"outreach_{r.get('company', '')}", False)
            }

            _run_id     = st.session_state.get("qualify_run_id", "")
            _sheets     = st.session_state.get("qualify_sheets") or _get_sc()
            _usage      = st.session_state.get("qualify_usage")
            _query      = st.session_state.get("grok_query", "")
            director    = get_current_user() or "Unknown"

            final_results = []
            st.info(
                f"Running Opus for {len(outreach_names)} prospect(s), "
                f"writing {len(qualified_results) - len(outreach_names)} without outreach…"
            )

            with st.spinner("Claude Opus drafting outreach + writing to Sheets…"):
                for result in qualified_results:
                    name = result.get("company", "")
                    skip = name not in outreach_names
                    try:
                        final = main.draft_outreach_for_prospect(
                            result=result,
                            sheets=_sheets,
                            query=_query,
                            run_id=_run_id,
                            dry_run=is_dry_run,
                            usage=_usage,
                            bu=bu,
                            skip_outreach=skip,
                        )
                        final_results.append(final)
                    except Exception as exc:
                        logger.warning(f"Outreach failed for {name}: {exc}")
                        final_results.append(result)

            # Write usage
            if final_results and not is_dry_run and _usage:
                try:
                    usage_sum = _usage.summary()
                    _sheets.write_usage(
                        run_id=_run_id,
                        director=director,
                        track="Discovery",
                        query=_query[:120],
                        companies_researched=len(final_results),
                        usage_summary=usage_sum,
                        bu=bu,
                    )
                except Exception as ue:
                    logger.warning(f"Usage write failed: {ue}")

            for key in ["grok_prospects", "enrichment_selections",
                        "qualified_results", "outreach_selections",
                        "sweep_result", "company_selections",
                        "grok_usage", "grok_sheets",
                        "sweep_usage", "sweep_sheets"]:
                st.session_state.pop(key, None)

            _display_results(final_results, is_dry_run, _query, bu)


elif active_page == "enrich":
    from utils.auth import get_current_user
    from core.enrichment_runner import (
        parse_company_input, estimate_enrichment_cost,
        run_bulk_enrichment, MAX_TOTAL_CALLS,
    )

    st.subheader("Enrich Companies")
    st.caption(
        "Already know which companies you want to target? Enter their names here. "
        "Lead Scout runs the same deep research as the Find Companies pipeline — "
        "power map, opportunity score, signals, and entry points. "
        "Optionally, ask Lead Scout to find 3 competitors per company and assess which is the better opportunity."
    )

    # ---- Input ----
    col_text, col_upload = st.columns([3, 1])
    with col_text:
        enrich_text = st.text_area(
            "Company names",
            placeholder="Nexstar Media Group, Gray Television, Sinclair Broadcast...\n\nor paste one per line",
            height=150,
            key="enrichment_text_input",
        )
    with col_upload:
        st.caption("Or upload a CSV")
        csv_file = st.file_uploader(
            "",
            type=["csv"],
            key="enrichment_csv_upload",
            label_visibility="collapsed",
        )

    csv_bytes    = csv_file.read() if csv_file else None
    company_list = parse_company_input(enrich_text, csv_bytes)

    if company_list:
        st.caption(
            f"**{len(company_list)} companies detected:** {', '.join(company_list[:8])}"
            + (f" +{len(company_list)-8} more" if len(company_list) > 8 else "")
        )

    # ---- Options ----
    col_opts1, col_opts2 = st.columns(2)
    with col_opts1:
        include_competitors = st.checkbox(
            "Include competitor analysis (3 competitors per company)",
            key="enrich_include_competitors",
            help=(
                f"For each company, Grok identifies 3 direct competitors and runs a light scan "
                f"to argue for or against each as a better opportunity. "
                f"Max {MAX_TOTAL_CALLS // 4} companies when enabled."
            ),
        )
    with col_opts2:
        is_dry_run_enrich = st.checkbox(
            "Preview — check cache only, no API calls",
            key="enrichment_dry_run",
        )

    # ---- Cap warning ----
    if company_list and include_competitors and len(company_list) > MAX_TOTAL_CALLS // 4:
        st.warning(
            f"With competitor analysis enabled, only the first {MAX_TOTAL_CALLS // 4} companies "
            f"will be processed (cap: {MAX_TOTAL_CALLS} total API calls). "
            f"Disable competitor analysis to process up to {MAX_TOTAL_CALLS} companies."
        )
    elif company_list and not include_competitors and len(company_list) > MAX_TOTAL_CALLS:
        st.warning(f"Only the first {MAX_TOTAL_CALLS} companies will be processed.")

    # ---- Estimate + Run ----
    col_est, col_run = st.columns([3, 2])

    with col_est:
        if st.button(
            "Estimate Cost",
            key="estimate_cost_btn",
            type="primary",
            disabled=not company_list,
        ):
            director = get_current_user()
            if not director:
                st.warning("Sign in to continue.")
            else:
                sc = _get_sc()
                cached_count = 0
                if sc and not is_dry_run_enrich:
                    for name in company_list:
                        from core.enrichment_runner import _resolve_domain
                        domain = _resolve_domain(name)
                        if domain and sc.get_enrichment_cache(domain):
                            cached_count += 1
                est = estimate_enrichment_cost(
                    len(company_list), cached_count,
                    include_competitors=include_competitors,
                )
                st.session_state["enrichment_estimate"] = est

        estimate = st.session_state.get("enrichment_estimate")
        if estimate:
            fresh    = estimate["effective_fresh"]
            cached   = estimate["cached"]
            total_c  = estimate["estimated_total"]
            calls    = estimate["total_calls"]
            inc_comp = estimate["include_competitors"]
            st.info(
                f"**Estimate:** {fresh} fresh · {cached} cached · {calls} API calls  \n"
                f"**~${total_c:.2f}** total · ${estimate['cost_per_fresh']:.2f}/company"
                + (" · includes competitor analysis" if inc_comp else "")
            )

    with col_run:
        run_enrich_btn = st.button(
            f"Enrich {len(company_list)} {'Company' if len(company_list) == 1 else 'Companies'}"
            if company_list else "Add companies above",
            type="primary",
            use_container_width=True,
            key="bulk_enrich_btn",
            disabled=not company_list,
        )

    if run_enrich_btn:
        director = get_current_user()
        if not director:
            st.warning("Sign in to continue.")
        else:
            estimate = st.session_state.get("enrichment_estimate", {})
            if (not is_dry_run_enrich and
                    estimate.get("estimated_total", 0) > 1.0 and
                    not st.session_state.get("enrichment_confirmed")):
                st.warning(
                    f"This will cost approximately **${estimate.get('estimated_total', 0):.2f}**. "
                    f"Click **Enrich** again to confirm."
                )
                st.session_state["enrichment_confirmed"] = True
            else:
                st.session_state.pop("enrichment_confirmed", None)
                st.session_state.pop("enrichment_results", None)

                st.divider()
                st.subheader(
                    f"{'Checking cache for' if is_dry_run_enrich else 'Enriching'} "
                    f"{len(company_list)} {'company' if len(company_list) == 1 else 'companies'}…"
                )

                placeholders = {name: st.empty() for name in company_list}
                for name in company_list:
                    placeholders[name].markdown(f"**{name}** · queued")

                all_results = []

                def _enrich_start(name, idx, total):
                    msg = "checking cache" if is_dry_run_enrich else (
                        "researching + competitor analysis…" if include_competitors
                        else "researching…"
                    )
                    placeholders[name].markdown(f"**{name}** · {msg} *({idx}/{total})*")

                def _enrich_done(name, result, idx, total):
                    if result.get("error"):
                        placeholders[name].markdown(f"**{name}** · ❌ {result['error']}")
                    elif result.get("dry_run"):
                        cached = result.get("from_cache", False)
                        placeholders[name].markdown(
                            f"**{name}** · {'📦 cached — free' if cached else '🆕 fresh — ~$0.55'}"
                        )
                    else:
                        score   = result.get("opportunity_score", 0)
                        verdict = result.get("verdict", "?")
                        cached  = result.get("from_cache", False)
                        n_comp  = len(result.get("competitors", []))
                        placeholders[name].markdown(
                            f"**{name}** · **{score}** · {verdict}"
                            + (f" · {n_comp} competitors analysed" if n_comp else "")
                            + (" · 📦 cached" if cached else "")
                        )
                    all_results.append(result)

                sc = _get_sc()
                with st.spinner(
                    f"Running {'cache check' if is_dry_run_enrich else 'full pipeline'} "
                    f"for {len(company_list)} companies…"
                ):
                    run_bulk_enrichment(
                        companies=company_list,
                        bu=bu,
                        director=director,
                        include_competitors=include_competitors,
                        dry_run=is_dry_run_enrich,
                        sheets=sc,
                        on_company_start=_enrich_start,
                        on_company_done=_enrich_done,
                    )

                st.session_state["enrichment_results"] = all_results
                if is_dry_run_enrich:
                    cached_n = sum(1 for r in all_results if r.get("from_cache"))
                    st.success(
                        f"Preview complete — {cached_n} cached, "
                        f"{len(all_results)-cached_n} would require fresh enrichment"
                    )
                else:
                    st.success(f"Enrichment complete — {len(all_results)} companies processed")

    # ---- Results ----
    enrich_results = st.session_state.get("enrichment_results", [])
    fresh_results  = [r for r in enrich_results if not r.get("dry_run") and not r.get("error")]

    if fresh_results:
        st.divider()
        for result in fresh_results:
            company_name  = result.get("company", "")
            domain        = result.get("domain", "")
            score         = result.get("opportunity_score", 0)
            verdict       = result.get("verdict", "")
            from_cache    = result.get("from_cache", False)
            competitors   = result.get("competitors", [])

            with st.expander(
                f"{'📦 ' if from_cache else ''}{company_name}  ·  {score}/100  ·  {verdict}",
                expanded=True,
            ):
                # Header row
                col_score, col_meta = st.columns([2, 5])
                with col_score:
                    st.markdown(_score_bar_html(score), unsafe_allow_html=True)
                    st.markdown(_verdict_chip(verdict), unsafe_allow_html=True)
                    if domain:
                        st.caption(f"[{domain}](https://{domain})")
                    if from_cache:
                        st.caption(f"📦 Cached · {result.get('cached_date', '')[:10]}")

                with col_meta:
                    causal = result.get("causal_inflection", "")
                    gap    = result.get("transition_gap", "")
                    vendor = result.get("incumbent_vendor", "")
                    entry  = result.get("entry_point", "")
                    risk   = result.get("risk_if_no_action", "")

                    if causal:
                        st.markdown("**Causal Inflection**")
                        st.write(causal)
                    if gap:
                        st.info(f"**Transition Gap:** {gap}")
                    if vendor:
                        st.caption(f"**Incumbent Vendor:** {vendor}")

                # Power map
                vis_name = result.get("visionary_name", "")
                ops_name = result.get("operator_name", "")
                if vis_name or ops_name:
                    st.markdown("---")
                    pm_col1, pm_col2 = st.columns(2)
                    with pm_col1:
                        if vis_name:
                            vis_li = result.get("visionary_linkedin", "")
                            nm = f"[{vis_name}]({vis_li})" if vis_li else vis_name
                            st.markdown(f"**Visionary:** {nm}  \n*{result.get('visionary_title', '')}*")
                    with pm_col2:
                        if ops_name:
                            ops_li = result.get("operator_linkedin", "")
                            nm = f"[{ops_name}]({ops_li})" if ops_li else ops_name
                            st.markdown(f"**Operator:** {nm}  \n*{result.get('operator_title', '')}*")

                # Entry point and risk
                if entry or risk:
                    st.markdown("---")
                    ep_col, risk_col = st.columns(2)
                    with ep_col:
                        if entry:
                            st.markdown("**Accedo Entry Point**")
                            st.success(entry)
                    with risk_col:
                        if risk:
                            st.markdown("**Risk if Accedo Waits**")
                            st.warning(risk)

                # Copywriter brief
                brief = result.get("copywriter_brief", "")
                if brief:
                    st.markdown("---")
                    st.markdown("**Copywriter Brief**")
                    st.caption(brief)

                # Apollo contacts (preferred) or Grok power map contacts
                apollo_contacts = result.get("apollo_contacts", [])
                decision_makers = result.get("decision_makers", [])
                contacts_to_show = apollo_contacts if apollo_contacts else decision_makers

                if contacts_to_show:
                    st.markdown("---")
                    source_label = "Apollo" if apollo_contacts else "Grok Power Map"
                    st.markdown(f"**Decision Makers** · *via {source_label}*")
                    for dm in contacts_to_show:
                        name  = dm.get("name", "")
                        title = dm.get("title", "")
                        li    = dm.get("linkedin", "")
                        email = dm.get("email", "")
                        if not name:
                            continue
                        dm_c1, dm_c2, dm_c3 = st.columns([3, 3, 2])
                        with dm_c1:
                            name_md = f"[{name}]({li})" if li else name
                            st.markdown(f"**{name_md}**  \n{title}")
                        with dm_c2:
                            if email:
                                st.caption(f"✉️ {email}")
                        with dm_c3:
                            if li:
                                st.markdown(f"[LinkedIn →]({li})")

                # Top signal
                top_sig = result.get("top_signal", "")
                if top_sig:
                    st.markdown("---")
                    st.markdown("**Top Signal**")
                    st.caption(top_sig)

                # Competitor analysis — only show if target company is worth pursuing
                if competitors and result.get("opportunity_score", 0) >= 30:
                    st.markdown("---")
                    st.markdown(f"**Competitor Analysis** — {len(competitors)} companies assessed")
                    st.caption("Ranked by opportunity score. Green = better opportunity than the target company.")

                    comp_cols = st.columns(len(competitors))
                    for ci, comp in enumerate(competitors):
                        with comp_cols[ci]:
                            comp_name    = comp.get("name", "")
                            comp_score   = comp.get("opportunity_score", 0)
                            comp_verdict = comp.get("verdict", "COLD")
                            argument     = comp.get("argument", "")
                            better       = comp.get("better_opportunity", False)

                            border_color = "#22c55e" if better else "#606060"
                            st.markdown(
                                f'<div style="border:1px solid {border_color};border-radius:8px;'
                                f'padding:12px;margin-bottom:8px;">'
                                f'<div style="font-weight:600;font-size:0.95rem;">{comp_name}</div>'
                                f'<div style="font-size:0.8rem;color:#a0a0a0;margin-top:2px;">'
                                f'{comp_score}/100 · {comp_verdict}'
                                + (' · <span style="color:#22c55e;font-weight:600;">Better opportunity</span>' if better else '')
                                + f'</div>'
                                f'<div style="font-size:0.85rem;margin-top:8px;color:#d0d0d0;">{argument}</div>'
                                f'</div>',
                                unsafe_allow_html=True,
                            )



elif active_page == "accounts":
    st.subheader(f"Account Intelligence · {bu}")
    st.caption(
        "Research companies you're already tracking — no search step needed. "
        "Lead Scout goes straight to deep research on each account in your list. "
        "Use the import section below to add accounts, then click Run."
    )


    # ---- Import section ----
    with st.expander("Import Accounts from CSV", expanded=False):
        st.caption(
            "Upload a spreadsheet of companies to add to your tracked accounts list. "
            "Required columns: **Company**, **Domain**. "
            "Optional but helpful: LinkedIn URL, Tier, Region."
        )
        uploaded = st.file_uploader(
            "Upload CSV",
            type=["csv"],
            key="account_upload",
            help="Company and Domain columns are required.",
        )

        if uploaded:
            try:
                import io
                df_import = pd.read_csv(io.StringIO(uploaded.read().decode("utf-8")))
                df_import.columns = [c.strip() for c in df_import.columns]

                required = {"Company", "Domain"}
                missing_cols = required - set(df_import.columns)
                if missing_cols:
                    st.error(f"Missing required columns: {', '.join(missing_cols)}")
                else:
                    # Show coverage gap warnings
                    missing_li = df_import["LinkedIn URL"].isna().sum() if "LinkedIn URL" in df_import.columns else len(df_import)
                    if missing_li > 0:
                        st.warning(f"{missing_li} row(s) missing LinkedIn URL — these will have reduced Exa enrichment.")

                    missing_domain = df_import["Domain"].isna().sum()
                    if missing_domain > 0:
                        st.error(f"{missing_domain} row(s) missing Domain — these will be skipped.")
                        df_import = df_import.dropna(subset=["Domain"])

                    st.markdown(f"**Preview — {len(df_import)} accounts · BU={bu}**")
                    st.dataframe(df_import.head(10), hide_index=True)

                    if st.button("Confirm Import", key="confirm_import", type="primary"):
                        sc = _get_sc()
                        imported = 0
                        for _, row in df_import.iterrows():
                            sc.upsert_account({
                                "Company":      str(row.get("Company", "")),
                                "Domain":       str(row.get("Domain", "")),
                                "LinkedIn URL": str(row.get("LinkedIn URL", "")),
                                "BU":           bu,
                                "Tier":         str(row.get("Tier", "")),
                                "Region":       str(row.get("Region", "")),
                            })
                            imported += 1
                        st.success(f"{imported} account(s) imported to Accounts tab · BU={bu}")
                        # Invalidate accounts cache
                        st.session_state.pop("accounts_cache", None)
                        st.rerun()

            except Exception as exc:
                st.error(f"Could not parse CSV: {exc}")

    # ---- Accounts table ----
    st.markdown(f"**Tracked Accounts · BU={bu}**")

    # on button click the load accounts
    acc_cache_key = f"accounts_{bu}"
    acc_cache_ts  = f"accounts_cache_ts_{bu}"

    col_refresh, _ = st.columns([1, 4])
    with col_refresh:
        if st.button("Load Accounts", key="load_accounts_btn", type="primary"):
            try:
                sc = _get_sc()
                if sc:
                    st.session_state[acc_cache_key] = sc.get_accounts(bu_filter=bu)
            except Exception as exc:
                st.error(f"Could not load accounts: {exc}")

    accounts = st.session_state.get(acc_cache_key, [])

    if accounts:
        acc_df = pd.DataFrame(accounts)
        # Highlight accounts never run or not run in 30+ days
        def _last_run_color(val):
            if not val:
                return "background-color: #fde8e8"
            try:
                from datetime import datetime as dt
                last = dt.strptime(val, "%Y-%m-%d %H:%M UTC")
                days = (dt.utcnow() - last).days
                if days > 30:
                    return "background-color: #fff7d6"
            except Exception:
                pass
            return ""
        st.dataframe(
            acc_df.style.applymap(_last_run_color, subset=["Last Run"]) if "Last Run" in acc_df.columns else acc_df,
            width='stretch', hide_index=True,
        )
    else:
        st.caption(f"No accounts found for BU={bu}. Import a CSV above to get started.")

    # ---- Run account intelligence ----
    st.divider()

    _acc_run_mode = st.selectbox(
        "Run Mode",
        options=["Live — save results to Google Sheet", "Preview — research only, no save"],
        index=1 if st.session_state.get("is_dry_run", False) else 0,
        key="dry_run_select_accounts",
        help="Live mode saves all results. Preview runs all AI research but skips the save step.",
    )
    is_dry_run = _acc_run_mode.startswith("Preview")
    st.session_state["is_dry_run"] = is_dry_run

    acc_run_btn = st.button(
        f"Run Account Intelligence · BU={bu}",
        type="primary",
        use_container_width=True,
        key="acc_run_btn",
        disabled=not accounts,
    )

    if acc_run_btn:
        _apply_model_overrides()
        st.session_state["view_mode"] = "run"
        log_stream = st.session_state.get("log_stream")
        if log_stream:
            log_stream.truncate(0)
            log_stream.seek(0)

        with st.status(
            f"Running account intelligence for {len(accounts)} account(s) · BU={bu}…",
            expanded=True,
        ) as status:
            st.write(f"Grok researching {len(accounts)} tracked account(s)…")
            try:
                sc = _get_sc()
                results = main.run_account_pipeline(
                    bu=bu,
                    dry_run=is_dry_run,
                    sheets_client=sc,
                )
                status.update(label="Account intelligence complete", state="complete", expanded=False)
                _browser_notify(
                    "Accedo Lead Scout — Account intelligence complete",
                    f"BU={bu} · results are ready",
                )
            except Exception as exc:
                status.update(label="Pipeline error", state="error", expanded=True)
                st.error(f"**Error:** {exc}")
                st.exception(exc)
                results = []

        if not results:
            st.warning("No results returned. Check the Pipeline Log for details.")
        else:
            # Invalidate accounts cache so Last Run updates
            st.session_state.pop(acc_cache_key, None)
            _display_results(results, is_dry_run, f"[ACCOUNT] BU={bu}", bu)




# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(
    f"Accedo Lead Scout · "
    f"{config.GROK_SCOUT_MODEL} · "
    f"{config.GEMINI_DISCOVERY_MODEL} discovery · "
    f"{config.CLAUDE_ANALYST_MODEL} analyst · "
    f"{config.CLAUDE_COPYWRITER_MODEL} copywriter · "
    f"BU={st.session_state.get('selected_bu', config.BU_DEFAULT)} · "
    f"Last render: {datetime.now().strftime('%H:%M:%S')}"
)