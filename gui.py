"""
gui.py — Accedo Strategic Lead Scout
=====================================
Two tracks:
  🔍 Discovery — Gemini + Exa find companies, Grok researches them
  📋 Account Intelligence — research tracked accounts from Sheets

Both tracks respect the BU selector (NAM / E&L / APAC).
"""

import logging
import random
from datetime import datetime
from io import StringIO

import pandas as pd
import streamlit as st

import config
import main
from utils.helpers import setup_logging
from utils.usage_tracker import load_usage_history

setup_logging(level=logging.INFO)


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
    initial_sidebar_state="expanded",
)

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
        f"💰 Run Cost: ${total:.4f} total  ·  ${per_p:.4f}/prospect  ·  {n} prospect(s)",
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
                        "Company": "🔍 Discovery + Grok (shared)",
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

    label = f"{'❄️' if is_cold else '🔥'} {company}   ·   {score}/100   ·   {verdict}   ·   {bu}"

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
            st.markdown("❄️ Cold Leads" if is_cold else "🔥 Leads")
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
            "🧠 Intelligence", "✉️ Outreach Emails", "🛡️ Objection Counters"
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
                st.markdown("**👤 Visionary**")
                if vis.get("name"):
                    li = vis.get("linkedin", "")
                    nm = f"[{vis['name']}]({li})" if li else vis["name"]
                    st.markdown(f"{nm} — *{vis.get('title', '')}*")
                    if vis.get("public_quote"):
                        st.caption(f'💬 "{vis["public_quote"][:220]}"')
                    if vis.get("angle"):
                        st.info(f"Hook: {vis['angle']}")
                else:
                    st.caption("Not identified in this run")
                st.markdown("**⚙️ Operator**")
                if ops.get("name"):
                    li = ops.get("linkedin", "")
                    nm = f"[{ops['name']}]({li})" if li else ops["name"]
                    st.markdown(f"{nm} — *{ops.get('title', '')}*")
                    if ops.get("public_quote"):
                        st.caption(f'💬 "{ops["public_quote"][:220]}"')
                    if ops.get("angle"):
                        st.info(f"Hook: {ops['angle']}")
                else:
                    st.caption("Not identified in this run")

            signals = prospect.get("signals", [])
            if signals:
                st.markdown("---")
                st.markdown("**📡 Research Signals**")
                for sig in signals[:4]:
                    conf = sig.get("confidence", "")
                    icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(conf, "⚪")
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
                st.markdown(f"**✉️ To: {vis_name}**")
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
                st.markdown(f"**✉️ To: {ops_name}**")
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
                        st.markdown(f"**❓ {objection}**")
                        if counter:
                            st.success(f"**Counter:** {counter}")
                        if evidence:
                            st.caption(f"Evidence: {evidence}")
                        st.divider()
            note = outreach.get("salesforce_note", "")
            if note:
                st.markdown("**📋 Salesforce Note**")
                st.code(note, language=None)


# ---------------------------------------------------------------------------
# History card (from Sheets row)
# ---------------------------------------------------------------------------

def render_history_card(row: dict) -> None:
    company  = row.get("Company", "Unknown")
    score    = row.get("Opportunity Score", "").replace("/100", "")
    verdict  = row.get("Priority", "")
    tab      = row.get("_tab", "")
    domain   = row.get("Domain", "")
    ts       = row.get("Timestamp", "")
    bu       = row.get("BU", "")
    is_cold  = tab == "Cold Leads"

    st.markdown(f"### {'❄️' if is_cold else '🔥'} {company}")
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
        st.markdown("❄️ Cold Leads" if is_cold else "🔥 Leads")

    st.divider()
    t_intel, t_emails, t_obj = st.tabs([
        "🧠 Intelligence", "✉️ Outreach Emails", "🛡️ Objection Counters"
    ])

    with t_intel:
        ic1, ic2 = st.columns(2)
        with ic1:
            for field, label in [
                ("Causal Inflection", "**Causal Inflection**"),
                ("Transition Gap", "**Transition Gap**"),
                ("Opportunity Type", "**Opportunity Type**"),
            ]:
                val = row.get(field, "")
                if val:
                    st.markdown(label)
                    st.write(val) if field != "Opportunity Type" else st.caption(val)
            signal = row.get("Top Signal", "")
            if signal:
                st.markdown("**Top Signal**")
                conf = row.get("Signal Confidence", "")
                icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(conf, "⚪")
                src = row.get("Signal Source", "")
                src_md = f" · [source]({src})" if src and src.startswith("http") else (f" · {src}" if src else "")
                st.markdown(f"{icon} {signal[:250]}{src_md}")
        with ic2:
            vis_name  = row.get("Visionary Name", "")
            vis_title = row.get("Visionary Title", "")
            vis_li    = row.get("Visionary LinkedIn", "")
            vis_hook  = row.get("Visionary Hook", "")
            st.markdown("**👤 Visionary**")
            if vis_name:
                nm = f"[{vis_name}]({vis_li})" if vis_li else vis_name
                st.markdown(f"{nm} — *{vis_title}*")
                if vis_hook:
                    st.info(f"Hook: {vis_hook}")
            else:
                st.caption("Not identified")

            ops_name  = row.get("Operator Name", "")
            ops_title = row.get("Operator Title", "")
            ops_li    = row.get("Operator LinkedIn", "")
            ops_hook  = row.get("Operator Hook", "")
            st.markdown("**⚙️ Operator**")
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
                st.markdown("**🔗 Apollo Contact**")
                st.markdown(f"{apollo_name} — *{apollo_title}*")
                if apollo_email:
                    st.caption(f"✉️ {apollo_email}")
                if apollo_li:
                    st.caption(f"[LinkedIn]({apollo_li})")

    with t_emails:
        ec1, ec2 = st.columns(2)
        with ec1:
            st.markdown(f"**✉️ To: {vis_name or 'Visionary'}**")
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
            st.markdown(f"**✉️ To: {ops_name or 'Operator'}**")
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
                st.markdown(f"**❓ {objection}**")
                st.success(f"**Counter:** {counter}")
                st.divider()
        note = row.get("Salesforce Note", "")
        if note:
            st.markdown("**📋 Salesforce Note**")
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
            from core.sheets import SheetsClient
            sc = SheetsClient()
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
        score   = row.get("Opportunity Score", "").replace("/100", "")
        tab     = row.get("_tab", "")
        ts      = row.get("Timestamp", "")[:10]
        is_cold = tab == "Cold Leads"
        icon    = "❄️" if is_cold else "🔥"
        label   = f"{icon} {company[:22]}  ·  {score}  ·  {ts}"
        if st.button(label, key=f"hist_{company}_{ts}", use_container_width=True):
            st.session_state["history_view"] = row
            st.session_state["view_mode"]    = "history"
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
    m2.metric("🔥 HOT", hot)
    m3.metric("🌡️ WARM", warm)
    m4.metric("❄️ COLD", cold)
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
            f"🔍 Discovery: Exa found {len(discovery_meta.get('all_found', []))} companies "
            f"· Gemini selected {len(discovery_meta.get('selected', []))}",
            expanded=True,
        ):
            if discovery_meta.get("selected"):
                st.markdown("**✅ Selected for deep research**")
                for c in discovery_meta["selected"]:
                    li   = c.get("linkedin_url", "")
                    name = f"[{c['name']}]({li})" if li else c["name"]
                    st.markdown(
                        f"**{name}** — *{c.get('signal_type', '')}*  \n"
                        f"{c.get('reasoning', '')}"
                    )
            if discovery_meta.get("rejected"):
                st.markdown("**❌ Filtered out by Gemini**")
                for r in discovery_meta["rejected"]:
                    st.caption(f"**{r.get('name')}** — {r.get('reason', '')}")

    if not dry:
        if written > 0:
            st.success(f"✅ {written} lead(s) written to **{config.GOOGLE_SHEET_NAME}** · BU={bu}")
        else:
            st.error(
                "⚠️ No rows written to Sheets. Possible causes:\n"
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
            "Tab":      "❄️ Cold" if r.get("verdict") == "COLD" else "🔥 Hot",
            "Exa":      "✓" if r.get("exa_enriched") == "found" else ("~" if r.get("exa_enriched") == "ran" else "—"),
            "Apollo":   "✓" if r.get("apollo_active") and config.APOLLO_ENABLED else "—",
            "Written":  "✅" if r.get("rows_written", 0) > 0 else ("🔍" if dry else "—"),
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
    with st.expander("📋 Pipeline Log (last run)", expanded=False):
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
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## 🎯 Lead Scout")
    st.caption("Accedo · Director of Strategic Accounts")
    st.divider()

    # -----------------------------------------------------------------------
    # Sales Director selector
    # -----------------------------------------------------------------------
    from utils.auth import get_current_user, render_budget_bar
    from core.sheets import SheetsClient as _SC

    selected_director = st.selectbox(
        "👤 Sales Director",
        options=config.SALES_DIRECTORS,
        index=config.SALES_DIRECTORS.index(
            st.session_state.get("selected_director", config.SALES_DIRECTORS[0])
        ),
        key="selected_director",
        help="Select your name to track usage and budget",
    )

    if selected_director and selected_director != config.SALES_DIRECTORS[0]:
        try:
            _sc = _SC()
            render_budget_bar(selected_director, _sc)
        except Exception:
            st.caption("Budget data unavailable")
    st.divider()

    # -----------------------------------------------------------------------
    # Model selector
    # -----------------------------------------------------------------------
    with st.expander("⚙️ Model Configuration", expanded=False):
        st.caption("Select models for each pipeline stage. Changes apply to the next run.")

        def _model_selectbox(role: str, label: str) -> str:
            options = config.MODEL_OPTIONS[role]
            labels  = [o["label"] for o in options]
            key     = f"model_sel_{role}"
            if key not in st.session_state:
                st.session_state[key] = 0
            idx = st.selectbox(
                label,
                options=range(len(labels)),
                format_func=lambda i: labels[i],
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

        _model_selectbox("grok",       "🔬 Grok — Research")
        st.divider()
        _model_selectbox("gemini",     "🔍 Gemini — Discovery")
        st.divider()
        _model_selectbox("analyst",    "🧠 Claude — Analyst")
        st.divider()
        _model_selectbox("copywriter", "✉️ Claude — Copywriter")
        st.divider()
        st.markdown("**Exa — LinkedIn Intel**")
        st.caption("🔒 Fixed — no model selection  \n💰 ~$0.005 per exec search")
        st.divider()
        st.markdown("**Apollo — Contact Enrichment**")
        st.caption("🔒 Fixed — no model selection  \n💰 $0.49/credit (bulk enrich)")

    st.divider()

    # BU selector — affects both tracks
    selected_bu = st.selectbox(
        "Business Unit",
        options=config.BU_OPTIONS,
        index=config.BU_OPTIONS.index(config.BU_DEFAULT),
        help="Filters both Discovery and Account Intelligence runs. All results are tagged with this BU.",
    )
    st.session_state["selected_bu"] = selected_bu
    st.caption(f"Active BU: `{selected_bu}`")

    st.divider()

    is_dry_run = st.checkbox(
        "Dry Run Mode",
        value=False,
        help="ON = research + qualify only, no Sheets writes.\nOFF = full pipeline.",
    )
    if is_dry_run:
        st.warning("🔍 Dry Run active")
    else:
        st.success("✅ Live Mode — will write to Sheets")

    st.divider()
    st.markdown("**Google Sheets**")
    st.caption(f"Sheet: `{config.GOOGLE_SHEET_NAME}`")
    st.caption(f"Hot: `{config.GOOGLE_WORKSHEET_NAME}`")
    st.caption(f"Cold: `{config.GOOGLE_COLD_WORKSHEET_NAME}`")

    st.divider()
    st.markdown("**API Status**")

    def _api_status(attr: str, label: str) -> None:
        val = getattr(config, attr, "")
        icon = "🟢" if val else "🔴"
        st.caption(f"{icon} {label}")

    _api_status("XAI_API_KEY",           "Grok / xAI")
    _api_status("ANTHROPIC_API_KEY",     "Claude / Anthropic")
    _api_status("EXA_API_KEY",           "Exa (LinkedIn)")
    _api_status("APOLLO_MASTER_API_KEY", "Apollo Master Key (Search)")
    _api_status("APOLLO_API_KEY",        "Apollo Standard Key (Enrich)")
    _api_status("GEMINI_API_KEY",        "Gemini Flash (Discovery)")

    st.divider()
    st.markdown(f"**Run History** · BU={selected_bu}")
    render_history_sidebar(bu_filter=selected_bu)

    st.divider()
    st.markdown("**Usage History**")
    with st.expander("📊 Historical Cost Log", expanded=False):
        try:
            history = load_usage_history(max_runs=10)
            if history:
                rows = [
                    {
                        "Date":       h.get("timestamp", "")[:16],
                        "Query":      h.get("query", "")[:30],
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

st.title("Media & Entertainment Revenue Unearther GUI for Sales aka MRUGS")
st.markdown(
    "**Grok-4** live research · **Claude Sonnet** qualification · "
    "**Claude Opus** outreach · **Exa** LinkedIn intel · **Apollo** contact enrichment · "
    f"**BU: {st.session_state.get('selected_bu', config.BU_DEFAULT)}**"
)

bu = st.session_state.get("selected_bu", config.BU_DEFAULT)


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


# ---------------------------------------------------------------------------
# View mode handler (history card)
# ---------------------------------------------------------------------------

def _handle_view_mode() -> bool:
    if st.session_state.get("view_mode") == "history":
        row = st.session_state.get("history_view", {})
        if row:
            col1, col2 = st.columns([1, 5])
            with col1:
                if st.button("← Back to last run"):
                    st.session_state["view_mode"] = "run"
                    st.rerun()
            with col2:
                st.caption(
                    f"Viewing historical record: **{row.get('Company', '')}** "
                    f"· {row.get('Timestamp', '')} · BU={row.get('BU', '—')}"
                )
            st.divider()
            render_history_card(row)
            return True
    return False


if _handle_view_mode():
    pass

else:
    # ---------------------------------------------------------------------------
    # Two-track tabs
    # ---------------------------------------------------------------------------
    tab_discovery, tab_enrichment, tab_accounts = st.tabs([
        "🔍 Discovery", "🏢 Company Enrichment", "📋 Account Intelligence"
    ])

    # -----------------------------------------------------------------------
    # DISCOVERY TAB
    # -----------------------------------------------------------------------
    with tab_discovery:

        from prompts.gemini_scorer import RANDOM_CONFIGS

        VERTICALS = [
            "Sports", "News", "Entertainment", "Faith", "Fitness",
            "Education", "Audio", "In-Vehicle", "Pay TV", "Multi-Vertical", "Other",
        ]

        SIGNALS = {
            "🏗️ OTT / CTV": [
                "First CTV build", "CTV expansion", "Smart TV app launch",
                "Platform migration", "Vendor migration", "Video player overhaul",
                "App store complaints", "RFP activity", "SSAI/DRM change",
            ],
            "🎨 Product / UX": [
                "App redesign", "Rebrand", "Platform consolidation",
                "Leadership change", "New product/UX leadership",
            ],
            "👥 Hiring": [
                "Hiring: OTT/CTV engineers", "Hiring: Front-end engineers",
                "Hiring: QA automation", "Hiring: UX/UI designers",
                "Hiring: Product managers", "Hiring: TPMs",
            ],
            "📈 Commercial": [
                "Rights deal", "FAST/AVOD launch", "Funding round",
                "Market expansion", "New streaming partnership",
                "DTC pivot", "M&A / platform unification",
            ],
        }

        # ----------------------------------------------------------------
        # STAGE A — Intake form
        # ----------------------------------------------------------------
        col_title, col_rand = st.columns([5, 1])
        with col_title:
            st.markdown("#### Find Companies")
        with col_rand:
            if st.button("🎲 Randomize", key="randomize_btn",
                         use_container_width=True,
                         help="Auto-fill with a random discovery scenario"):
                import random as _random
                cfg = _random.choice(RANDOM_CONFIGS)

                # Update form tracking state
                st.session_state["form_verticals"]      = cfg["verticals"]
                st.session_state["form_signals"]        = cfg["signals"]
                st.session_state["form_context"]        = cfg["context"]
                st.session_state["form_signals_live"]   = cfg["signals"]
                st.session_state["form_verticals_live"] = cfg["verticals"]

                # Build the new brief now and write directly to the widget key
                # so the text area reflects the new values immediately
                _bu_label = {
                    "NAM": "North America (US, Canada, Mexico)",
                    "E&L": "Europe or Latin America",
                    "APAC": "Asia Pacific",
                }.get(bu, bu)
                _new_brief = (
                    f"Find Tier 1 and Tier 2 {', '.join(cfg['verticals'])} companies "
                    f"headquartered in {_bu_label} "
                    f"showing these OTT buying signals: {', '.join(cfg['signals'])}."
                )
                if cfg.get("context"):
                    _new_brief += f"\n\nAdditional context: {cfg['context']}"
                st.session_state["brief_text_area"] = _new_brief
                st.session_state["form_context_input"] = cfg["context"]

                # Set each checkbox widget state directly
                for _v in VERTICALS:
                    st.session_state[f"v_{_v}"] = _v in cfg["verticals"]
                for _group_signals in SIGNALS.values():
                    for _s in _group_signals:
                        st.session_state[f"s_{_s}"] = _s in cfg["signals"]

                # Clear downstream state only
                for key in ["assembled_brief", "sweep_result",
                            "grok_prospects", "enrichment_selections"]:
                    st.session_state.pop(key, None)

                st.rerun()

        st.caption("**What kind of company are you hunting?**")
        selected_verticals = []
        v_cols = st.columns(4)
        for i, v in enumerate(VERTICALS):
            default = v in st.session_state.get("form_verticals", [])
            if v_cols[i % 4].checkbox(v, value=default, key=f"v_{v}"):
                selected_verticals.append(v)

        st.divider()
        st.caption("**What signals are you looking for?**")
        selected_signals = []
        for group, group_signals in SIGNALS.items():
            st.markdown(f"*{group}*")
            s_cols = st.columns(3)
            for i, s in enumerate(group_signals):
                default = s in st.session_state.get("form_signals", [])
                if s_cols[i % 3].checkbox(s, value=default, key=f"s_{s}"):
                    selected_signals.append(s)

        st.divider()
        st.caption("**Anything specific to focus on?** *(optional)*")
        context_val = st.text_input(
            "",
            value=st.session_state.get("form_context", ""),
            placeholder="e.g. running on ViewLift, just acquired X, mobile-only right now…",
            key="form_context_input",
            label_visibility="collapsed",
        )
        st.divider()

        form_ready = bool(selected_verticals and selected_signals)

        if not form_ready:
            st.caption("Select at least one vertical and one signal to continue.")

        # Build query directly from form selections — no LLM needed
        if form_ready:
            bu_label = {
                "NAM":  "North America (US, Canada, Mexico)",
                "E&L":  "Europe or Latin America",
                "APAC": "Asia Pacific",
            }.get(bu, bu)

            # Read from previous render's persisted values for the brief
            # Fall back to current render values only if nothing persisted yet
            brief_signals   = st.session_state.get("form_signals_live", selected_signals)
            brief_verticals = st.session_state.get("form_verticals", selected_verticals)

            # Now persist current render values for the NEXT render
            st.session_state["form_signals_live"]    = selected_signals
            st.session_state["form_verticals_live"]  = selected_verticals

            auto_brief = (
                f"Find Tier 1 and Tier 2 {', '.join(brief_verticals)} companies "
                f"headquartered in {bu_label} "
                f"showing these OTT buying signals: {', '.join(brief_signals)}."
            )
            if context_val.strip():
                auto_brief += f"\n\nAdditional context: {context_val.strip()}"

            # Sync brief when selections change
            _selection_hash = hash((
                tuple(sorted(brief_verticals)),
                tuple(sorted(brief_signals)),
                context_val.strip(),
                bu,
            ))
            if st.session_state.get("last_selection_hash") != _selection_hash:
                st.session_state["brief_text_area"]     = auto_brief
                st.session_state["last_selection_hash"] = _selection_hash

            st.caption("**Research Brief** — edit before searching if needed")

            edited_brief = st.text_area(
                "",
                value=st.session_state.get("brief_text_area", auto_brief),
                height=160,
                key="brief_text_area",
                label_visibility="collapsed",
            )


            sweep_btn = st.button(
                "🔍 Find Companies",
                use_container_width=True,
                type="primary",
                key="sweep_btn",
                disabled=not edited_brief.strip(),
            )

            # ---- Discovery sweep ----
            if sweep_btn:
                _apply_model_overrides()
                st.session_state["form_verticals"] = selected_verticals
                st.session_state["form_signals"]   = selected_signals
                st.session_state["form_context"]   = context_val
                st.session_state["form_signals_live"] = selected_signals
                for key in ["sweep_result", "company_selections",
                            "grok_prospects", "enrichment_selections"]:
                    st.session_state.pop(key, None)

                with st.status(
                    "🔍 Searching for companies…", expanded=True
                ) as status:
                    st.write(
                        "Grok is scanning the web for companies matching "
                        "your brief. This takes about 60-90 seconds…"
                    )
                    try:
                        sweep = main.run_discovery_sweep(edited_brief, bu=bu)
                        st.session_state["sweep_result"]  = sweep
                        st.session_state["sweep_brief"]   = edited_brief
                        st.session_state["sweep_usage"]   = sweep.get("usage")
                        st.session_state["sweep_sheets"]  = sweep.get("sheets")
                        companies = sweep.get("companies", [])
                        status.update(
                            label=f"✅ Found {len(companies)} companies — select which to research",
                            state="complete", expanded=False,
                        )
                        # Show discovery sweep cost
                        _sweep_u = sweep.get("usage")
                        if _sweep_u:
                            _sweep_u.finish()
                            render_usage_panel(_sweep_u.summary())
                    except Exception as exc:
                        status.update(label="❌ Error", state="error", expanded=True)
                        st.error(f"**Error:** {exc}")
                        st.exception(exc)

        # ----------------------------------------------------------------
        # STAGE C — Company selection
        # ----------------------------------------------------------------
        sweep_result = st.session_state.get("sweep_result")

        if sweep_result:
            companies = sweep_result.get("companies", [])
            search_summary = sweep_result.get("search_summary", "")

            if not companies:
                st.warning(
                    "⚠️ No companies found. Try adjusting your brief "
                    "or selecting different signals."
                )
            else:
                st.divider()
                st.subheader(f"🔍 {len(companies)} companies found")
                if search_summary:
                    st.caption(search_summary)
                st.caption(
                    "Select up to 5 companies for deep research. "
                    "Grok will research each one individually — "
                    "results appear as each completes."
                )

                # Initialise selections — all unchecked by default
                # (rep chooses, not pre-selected)
                if "company_selections" not in st.session_state:
                    st.session_state["company_selections"] = {
                        c.get("name", ""): False for c in companies
                    }

                selected_count = sum(
                    st.session_state["company_selections"].values()
                )

                for company in companies:
                    name        = company.get("name", "")
                    evidence    = company.get("evidence", "")
                    signal_type = company.get("signal_type", "")
                    source_url  = company.get("source_url", "")
                    hq          = company.get("hq_country", "")

                    col_check, col_info = st.columns([1, 10])
                    with col_check:
                        current  = st.session_state["company_selections"].get(name, False)
                        disabled = selected_count >= 5 and not current
                        checked  = st.checkbox(
                            "", value=current,
                            key=f"sel_{name}",
                            disabled=disabled,
                            label_visibility="collapsed",
                        )
                        st.session_state["company_selections"][name] = checked
                        if checked != current:
                            st.rerun()

                    with col_info:
                        name_md = f"[{name}]({source_url})" if source_url else name
                        meta    = f" · {hq}" if hq else ""
                        badge   = f"`{signal_type}`" if signal_type else ""
                        st.markdown(f"**{name_md}**{meta}  {badge}")
                        if evidence:
                            st.caption(evidence)

                selected_count = sum(
                    st.session_state["company_selections"].values()
                )
                st.caption(f"{selected_count}/5 selected for deep research")

                research_btn = st.button(
                    f"🔬 Deep Research {selected_count} Selected "
                    f"{'Company' if selected_count == 1 else 'Companies'}"
                    if selected_count > 0
                    else "⬆️ Select companies above to research",
                    type="primary",
                    use_container_width=True,
                    key="research_btn",
                    disabled=selected_count == 0,
                )

                # ----------------------------------------------------------------
                # STAGE D — Per-company deep research with live progress
                # ----------------------------------------------------------------
                if research_btn:
                    _apply_model_overrides()
                    st.session_state.pop("grok_prospects", None)
                    st.session_state.pop("enrichment_selections", None)

                    selected_companies = [
                        c for c in companies
                        if st.session_state["company_selections"].get(
                            c.get("name", ""), False
                        )
                    ]
                    total = len(selected_companies)
                    brief = st.session_state.get("sweep_brief", "")
                    run_id = sweep_result.get("run_id", "")

                    st.divider()
                    st.subheader(f"🔬 Researching {total} {'company' if total == 1 else 'companies'}…")

                    # One placeholder per company — updated as each completes
                    placeholders = {}
                    for company in selected_companies:
                        name = company.get("name", "")
                        placeholders[name] = st.empty()
                        # Show queued state immediately
                        placeholders[name].markdown(
                            f"⬜ **{name}** · queued"
                        )

                    completed_prospects = []

                    def _on_start(name, idx, total):
                        placeholders[name].markdown(
                            f"⏳ **{name}** · researching now… "
                            f"*({idx}/{total})*"
                        )

                    def _on_done(name, prospect, idx, total):
                        score   = prospect.get("opportunity_score") or 0
                        verdict = "HOT 🔥" if score >= 70 else "WARM ♨️" if score >= 50 else "COLD ❄️"
                        opp     = prospect.get("opportunity_type", "")
                        err     = prospect.get("error")
                        if err:
                            placeholders[name].markdown(
                                f"❌ **{name}** · research failed — {err}"
                            )
                        else:
                            placeholders[name].markdown(
                                f"✅ **{name}** · "
                                f"**{score}** · {verdict}"
                                + (f" · *{opp}*" if opp else "")
                            )
                        completed_prospects.append(prospect)

                    try:
                        # Pass sweep's usage+sheets so Grok tokens accumulate
                        # in the same RunUsage instance from discovery
                        _sweep_usage  = st.session_state.get("sweep_usage")
                        _sweep_sheets = st.session_state.get("sweep_sheets")

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

                        # Store usage+sheets for the enrichment stage
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

                        # Show interim usage after deep research
                        _interim_usage = grok_result.get("usage")
                        if _interim_usage:
                            _interim_usage.finish()
                            render_usage_panel(_interim_usage.summary())

                        st.success(
                            f"✅ Research complete — "
                            f"{len(all_prospects)} prospects ready for enrichment"
                        )
                    except Exception as exc:
                        st.error(f"**Research error:** {exc}")
                        st.exception(exc)

        # ----------------------------------------------------------------
        # STAGE E — Enrichment selection (unchanged from before)
        # ----------------------------------------------------------------
        grok_prospects = st.session_state.get("grok_prospects", [])

        if grok_prospects:
            st.divider()
            st.subheader("🧠 Select which prospects to enrich")
            st.caption(
                "HOT and WARM are pre-checked. "
                "Unselected companies are archived to Cold Leads."
            )

            if "enrichment_selections" not in st.session_state:
                st.session_state["enrichment_selections"] = {
                    p.get("name", ""): (p.get("opportunity_score") or 0) >= 50
                    for p in grok_prospects
                }

            for prospect in grok_prospects:
                name     = prospect.get("name", "")
                score    = prospect.get("opportunity_score") or 0
                verdict  = "HOT" if score >= 70 else "WARM" if score >= 50 else "COLD"
                opp_type = prospect.get("opportunity_type", "")
                gap      = prospect.get("transition_gap_timer", "")

                col_check, col_score, col_info = st.columns([1, 2, 8])
                with col_check:
                    current = st.session_state["enrichment_selections"].get(name, False)
                    checked = st.checkbox(
                        "", value=current,
                        key=f"enrich_{name}",
                        label_visibility="collapsed",
                    )
                    st.session_state["enrichment_selections"][name] = checked
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

            enrichment_count = sum(
                st.session_state["enrichment_selections"].values()
            )
            st.caption(
                f"{enrichment_count} selected for enrichment · "
                f"{len(grok_prospects) - enrichment_count} archived to Cold Leads"
            )

            enrich_btn = st.button(
                f"🚀 Enrich & Draft Outreach for {enrichment_count} Selected"
                if enrichment_count > 0
                else "⬆️ Select at least one company above",
                type="primary",
                use_container_width=True,
                key="enrich_btn",
                disabled=enrichment_count == 0,
            )

            if enrich_btn:
                _apply_model_overrides()
                enrichment_names = {
                    name for name, sel
                    in st.session_state["enrichment_selections"].items()
                    if sel
                }
                log_stream = st.session_state.get("log_stream")
                if log_stream:
                    log_stream.truncate(0)
                    log_stream.seek(0)

                with st.status(
                    f"Enriching {enrichment_count} prospect(s)…",
                    expanded=True,
                ) as status:
                    st.write(
                        "🔗 Apollo → Exa exec intel → "
                        "Claude Sonnet → Claude Opus → Sheets…"
                    )
                    try:
                        from core.sheets import SheetsClient
                        from utils.auth import get_current_user
                        director = get_current_user() or "Unknown"

                        # Reuse usage+sheets threaded from sweep → grok
                        _grok_usage  = st.session_state.get("grok_usage")
                        _grok_sheets = st.session_state.get("grok_sheets") or SheetsClient()

                        results = main.run_enrichment_from_selection(
                            query=st.session_state.get("grok_query", ""),
                            bu=bu,
                            all_prospects=grok_prospects,
                            enrichment_names=enrichment_names,
                            run_id=st.session_state.get("grok_run_id", ""),
                            dry_run=is_dry_run,
                            discovery=st.session_state.get("grok_discovery"),
                            usage=_grok_usage,
                            sheets=_grok_sheets,
                        )
                        # Write usage row with fully accumulated cost
                        if results and not is_dry_run:
                            usage_sum = results[0].get("usage_summary", {})
                            if usage_sum:
                                try:
                                    _grok_sheets.write_usage(
                                        run_id=st.session_state.get("grok_run_id", ""),
                                        director=director,
                                        track="Discovery",
                                        query=st.session_state.get("grok_query", "")[:120],
                                        companies_researched=len(enrichment_names),
                                        usage_summary=usage_sum,
                                        bu=bu,
                                    )
                                except Exception as ue:
                                    logger.warning(f"Usage write failed: {ue}")
                        status.update(
                            label="✅ Enrichment complete!",
                            state="complete", expanded=False,
                        )
                    except Exception as exc:
                        status.update(
                            label="❌ Enrichment error",
                            state="error", expanded=True,
                        )
                        st.error(f"**Error:** {exc}")
                        st.exception(exc)
                        results = []

                if results:
                    for key in ["grok_prospects", "enrichment_selections",
                                "sweep_result", "company_selections",
                                "grok_usage", "grok_sheets",
                                "sweep_usage", "sweep_sheets"]:
                        st.session_state.pop(key, None)
                    _display_results(
                        results, is_dry_run,
                        st.session_state.get("grok_query", ""), bu,
                    )



        VERTICALS = [
            "Sports", "News", "Entertainment", "Faith", "Fitness",
            "Education", "Audio", "In-Vehicle", "Pay TV", "Multi-Vertical", "Other",
        ]

        SIGNALS = {
            "🏗️ OTT / CTV": [
                "First CTV build",
                "CTV expansion",
                "Smart TV app launch",
                "Platform migration",
                "Vendor migration",
                "Video player overhaul",
                "App store complaints",
                "RFP activity",
                "SSAI/DRM change",
            ],
            "🎨 Product / UX": [
                "App redesign",
                "Rebrand",
                "Platform consolidation",
                "Leadership change",
                "New product/UX leadership",
            ],
            "👥 Hiring": [
                "Hiring: OTT/CTV engineers",
                "Hiring: Front-end engineers",
                "Hiring: QA automation",
                "Hiring: UX/UI designers",
                "Hiring: Product managers",
                "Hiring: TPMs",
            ],
            "📈 Commercial": [
                "Rights deal",
                "FAST/AVOD launch",
                "Funding round",
                "Market expansion",
                "New streaming partnership",
                "DTC pivot",
                "M&A / platform unification",
            ],
        }

        # Randomizer button
        col_title, col_rand = st.columns([5, 1])
        with col_title:
            st.markdown("#### Find Companies")


    # -----------------------------------------------------------------------
    # COMPANY ENRICHMENT TAB
    # -----------------------------------------------------------------------
    with tab_enrichment:
        from utils.auth import require_user
        from core.enrichment_runner import run_company_enrichment
        import json as _json

        st.subheader("🏢 Company Enrichment")
        st.caption(
            "Look up decision makers, intent signals, and recent OTT buying "
            "signals for any company. Results are cached for 90 days."
        )

        enrich_company = st.text_input(
            "Company name",
            placeholder="e.g. Nexstar Media Group",
            key="enrichment_company_input",
        )

        enrich_run_btn = st.button(
            "🔍 Enrich Company",
            type="primary",
            use_container_width=True,
            key="enrich_company_btn",
            disabled=not enrich_company.strip(),
        )

        if enrich_run_btn:
            director = get_current_user()
            if not director:
                st.warning("⚠️ Please select your name in the sidebar first.")
            else:
                with st.status(
                    f"Enriching {enrich_company}…", expanded=True
                ) as status:
                    st.write("Checking cache → Apollo → Grok signal sweep…")
                    try:
                        from core.sheets import SheetsClient
                        _sc = SheetsClient()
                        result = run_company_enrichment(
                            company=enrich_company.strip(),
                            bu=bu,
                            director=director,
                            sheets=_sc,
                        )
                        st.session_state["enrichment_result"] = result
                        if result.get("from_cache"):
                            status.update(
                                label=f"✅ Loaded from cache ({result.get('cached_date', '')})",
                                state="complete", expanded=False,
                            )
                        else:
                            status.update(
                                label="✅ Enrichment complete",
                                state="complete", expanded=False,
                            )
                    except Exception as exc:
                        status.update(label="❌ Error", state="error", expanded=True)
                        st.error(f"**Error:** {exc}")
                        st.exception(exc)

        # ---- Display enrichment results ----
        enrich_result = st.session_state.get("enrichment_result")
        if enrich_result and not enrich_result.get("error"):
            st.divider()

            company_name = enrich_result.get("company", "")
            domain       = enrich_result.get("domain", "")
            from_cache   = enrich_result.get("from_cache", False)

            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"### {company_name}")
                if domain:
                    st.caption(f"[{domain}](https://{domain})")
            with col2:
                if from_cache:
                    st.info(f"📦 Cached  \n{enrich_result.get('cached_date', '')[:10]}")
                else:
                    st.success("🆕 Fresh run")

            # Grok signal
            grok_sig = enrich_result.get("grok_signal", "")
            if grok_sig:
                st.markdown("**📡 Recent OTT Signal**")
                st.info(grok_sig)

            # Intent topics
            intent = enrich_result.get("intent_topics", [])
            if intent:
                st.markdown("**🎯 Intent Topics**")
                st.write("  ".join(f"`{t}`" for t in intent))

            # Decision makers
            dms = enrich_result.get("decision_makers", [])
            if dms:
                st.markdown(f"**👥 Decision Makers** ({len(dms)} found)")
                for dm in dms:
                    name    = dm.get("name", "")
                    title   = dm.get("title", "")
                    li      = dm.get("linkedin", "")
                    email   = dm.get("email", "")
                    loc     = ", ".join(filter(None, [dm.get("city"), dm.get("country")]))

                    dm_col1, dm_col2, dm_col3 = st.columns([3, 2, 2])
                    with dm_col1:
                        name_md = f"[{name}]({li})" if li else name
                        st.markdown(f"**{name_md}**  \n{title}")
                    with dm_col2:
                        if email:
                            st.caption(f"✉️ {email}")
                        if loc:
                            st.caption(f"📍 {loc}")
                    with dm_col3:
                        if li:
                            st.markdown(f"[LinkedIn →]({li})")
                    st.divider()
            else:
                st.caption("No decision makers found via Apollo.")

    # -----------------------------------------------------------------------
    # ACCOUNT INTELLIGENCE TAB
    # -----------------------------------------------------------------------
    with tab_accounts:
        st.subheader(f"Account Intelligence · BU={bu}")
        st.caption(
            "Import a prospect list or run intelligence on your tracked accounts. "
            "Discovery is skipped — Grok researches each account directly."
        )


        # ---- Import section ----
        with st.expander("📥 Import Accounts", expanded=False):
            st.caption(
                "CSV must have at minimum: **Company**, **Domain**. "
                "Optional: LinkedIn URL, Tier, Region."
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
                            st.warning(f"⚠️ {missing_li} row(s) missing LinkedIn URL — these will have reduced Exa enrichment.")

                        missing_domain = df_import["Domain"].isna().sum()
                        if missing_domain > 0:
                            st.error(f"❌ {missing_domain} row(s) missing Domain — these will be skipped.")
                            df_import = df_import.dropna(subset=["Domain"])

                        st.markdown(f"**Preview — {len(df_import)} accounts · BU={bu}**")
                        st.dataframe(df_import.head(10), hide_index=True)

                        if st.button("✅ Confirm Import", key="confirm_import"):
                            from core.sheets import SheetsClient
                            sc = SheetsClient()
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
                            st.success(f"✅ {imported} account(s) imported to Accounts tab · BU={bu}")
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
            if st.button("🔄 Load Accounts", key="load_accounts_btn"):
                try:
                    from core.sheets import SheetsClient
                    sc = SheetsClient()
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
        acc_run_btn = st.button(
            f"▶️ Run Account Intelligence · BU={bu}",
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
                st.write(f"🔍 Grok researching {len(accounts)} tracked account(s) — skipping discovery…")
                try:
                    from core.sheets import SheetsClient
                    sc = SheetsClient()
                    results = main.run_account_pipeline(
                        bu=bu,
                        dry_run=is_dry_run,
                        sheets_client=sc,
                    )
                    status.update(label="✅ Account intelligence complete!", state="complete", expanded=False)
                except Exception as exc:
                    status.update(label="❌ Pipeline error", state="error", expanded=True)
                    st.error(f"**Error:** {exc}")
                    st.exception(exc)
                    results = []

            if not results:
                st.warning("⚠️ No results returned. Check the Pipeline Log for details.")
            else:
                # Invalidate accounts cache so Last Run updates
                st.session_state.pop(acc_cache_key, None)
                _display_results(results, is_dry_run, f"[ACCOUNT] BU={bu}", bu)


# ---------------------------------------------------------------------------
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