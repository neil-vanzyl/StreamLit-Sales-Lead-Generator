"""
core/sheets.py — Google Sheets persistence (Multi-Tab Edition).

Supports:
- Leads / Cold Leads tab routing based on analyst verdict
- Logs tab for per-step API audit trail
- Accounts tab for tracked prospect list (account intelligence track)
- Signals tab for persistent signal history across all runs
- get_press_sources() / get_semantic_guide() — built but gated
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional, Set

import gspread
from google.oauth2.service_account import Credentials

import config

logger = logging.getLogger("ott_lead_gen.sheets")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

LOG_COLUMNS = [
    "Timestamp", "Run ID", "Query", "Company", "Domain",
    "Step", "Status", "Detail", "Tokens In", "Tokens Out",
    "Credits", "Cost USD", "Error", "Duration ms",
]

USER_PREFS_COLUMNS = ["Email", "BU", "Updated At"]

USAGE_TRACKER_COLUMNS = [
    "Timestamp", "Run ID", "Sales Director", "Track",
    "Query / Company", "Companies Researched",
    "Grok Cost USD", "Sonnet Cost USD", "Opus Cost USD",
    "Gemini Cost USD", "Exa Cost USD", "Apollo Cost USD",
    "Total Cost USD", "Month", "BU",
]

ENRICHMENT_COLUMNS = [
    "Timestamp", "Run ID", "Sales Director", "Company", "Domain",
    "HQ Country", "Opportunity Score", "Verdict",
    "Causal Inflection", "Transition Gap", "Incumbent Vendor",
    "Top Signal", "Entry Point", "Risk if No Action",
    "Visionary Name", "Visionary Title", "Visionary LinkedIn",
    "Operator Name", "Operator Title", "Operator LinkedIn",
    "Decision Makers", "Intent Topics", "Grok Signal Summary",
    "Competitors", "BU", "Status",
]


class SheetsClient:
    """
    Writes lead intelligence to Google Sheets.
    Supports Leads, Cold Leads, Logs, Accounts, and Signals worksheets.
    """

    def __init__(self) -> None:
        self._ss: Optional[gspread.Spreadsheet] = None
        self._ws_hot: Optional[gspread.Worksheet] = None
        self._ws_cold: Optional[gspread.Worksheet] = None
        self._ws_logs: Optional[gspread.Worksheet] = None
        self._ws_accounts: Optional[gspread.Worksheet] = None
        self._ws_signals: Optional[gspread.Worksheet] = None
        self._ws_usage: Optional[gspread.Worksheet] = None
        self._ws_enrichment: Optional[gspread.Worksheet] = None
        self._ws_user_prefs: Optional[gspread.Worksheet] = None
        self._seen_domains: Set[str] = set()
        self._seen_pairs: Set[tuple] = set()

    # ------------------------------------------------------------------
    # Connection logic
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        """Initialize the spreadsheet connection and all worksheets."""
        if self._ss is not None:
            return

        import json, os
        sa_path = config.GOOGLE_SERVICE_ACCOUNT_JSON
        if os.path.exists(sa_path):
            creds = Credentials.from_service_account_file(sa_path, scopes=SCOPES)
            logger.info("Sheets: credentials loaded from local file")
        else:
            sa_info = None
            try:
                import streamlit as st
                if "GOOGLE_SERVICE_ACCOUNT_JSON" in st.secrets:
                    sa_info = dict(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"])
                    logger.info("Sheets: credentials loaded from Streamlit TOML secret")
            except Exception:
                pass
            if sa_info is None:
                sa_info = json.loads(os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "{}"))
                logger.info("Sheets: credentials loaded from env var JSON string")
            creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES)

        gc = gspread.authorize(creds)
        try:
            self._ss = gc.open(config.GOOGLE_SHEET_NAME)
        except gspread.SpreadsheetNotFound:
            logger.info(f"Sheets: creating new spreadsheet '{config.GOOGLE_SHEET_NAME}'")
            self._ss = gc.create(config.GOOGLE_SHEET_NAME)

        self._ws_hot        = self._get_or_create_ws(config.GOOGLE_WORKSHEET_NAME)
        self._ws_cold       = self._get_or_create_ws(config.GOOGLE_COLD_WORKSHEET_NAME)
        self._ws_logs       = self._get_or_create_ws(config.GOOGLE_LOGS_WORKSHEET_NAME, LOG_COLUMNS)
        self._ws_accounts   = self._get_or_create_ws(config.GOOGLE_ACCOUNTS_WORKSHEET_NAME, config.ACCOUNTS_COLUMNS)
        self._ws_signals    = self._get_or_create_ws(config.GOOGLE_SIGNALS_WORKSHEET_NAME, config.SIGNALS_COLUMNS)
        self._ws_usage      = self._get_or_create_ws(config.GOOGLE_USAGE_TRACKER_WORKSHEET_NAME, USAGE_TRACKER_COLUMNS)
        self._ws_enrichment = self._get_or_create_ws(config.GOOGLE_ENRICHMENT_WORKSHEET_NAME, ENRICHMENT_COLUMNS)
        self._ws_user_prefs = self._get_or_create_ws(config.GOOGLE_USER_PREFS_WORKSHEET_NAME, USER_PREFS_COLUMNS)

        self._load_dedup_cache()

        # Cache the sheet URL in Streamlit session state so the nav bar link works
        # regardless of when _connect() is first called successfully.
        try:
            import streamlit as _st
            if self._ss and not _st.session_state.get("_cached_sheet_url"):
                _st.session_state["_cached_sheet_url"] = (
                    f"https://docs.google.com/spreadsheets/d/{self._ss.id}"
                )
        except Exception:
            pass

    def _get_or_create_ws(self, title: str, columns: list = None) -> gspread.Worksheet:
        """Find or create a worksheet and ensure headers exist."""
        cols = columns or config.SHEET_COLUMNS
        try:
            ws = self._ss.worksheet(title)
        except gspread.WorksheetNotFound:
            ws = self._ss.add_worksheet(
                title=title,
                rows=10000,
                cols=len(cols),
            )
        if not ws.row_values(1) or ws.row_values(1) != cols:
            ws.update("A1", [cols])
            logger.info(f"Sheets: header row written for '{title}'")
        return ws

    # ------------------------------------------------------------------
    # Dedup cache
    # ------------------------------------------------------------------

    def _load_dedup_cache(self) -> None:
        """Load records from both lead tabs to prevent duplicates."""
        for ws in [self._ws_hot, self._ws_cold]:
            try:
                records = ws.get_all_records()
                for r in records:
                    domain = r.get("Domain", "").strip().lower()
                    contact = r.get("Apollo Contact Name", "").strip().lower()
                    if domain:
                        self._seen_domains.add(domain)
                    if domain and contact:
                        self._seen_pairs.add((domain, contact))
            except Exception as exc:
                logger.warning(f"Sheets: could not load cache for '{ws.title}': {exc}")
        logger.info(f"Sheets: dedup cache loaded — {len(self._seen_domains)} total domains")

    def is_duplicate(self, domain: str, contact_name: str = "") -> bool:
        d = domain.strip().lower()
        if config.DEDUP_STRATEGY == "domain+contact" and contact_name:
            return (d, contact_name.strip().lower()) in self._seen_pairs
        return d in self._seen_domains

    def _mark_seen(self, domain: str, contact_name: str = "") -> None:
        d = domain.strip().lower()
        self._seen_domains.add(d)
        if contact_name:
            self._seen_pairs.add((d, contact_name.strip().lower()))

    # ------------------------------------------------------------------
    # Lead write
    # ------------------------------------------------------------------

    def append_lead(
        self,
        prospect: dict,
        analyst: dict,
        emails: dict,
        contact=None,
        query: str = "",
        is_cold: bool = False,
        exa_rejected: str = "",
        gemini_reasoning: str = "",
        bu: str = "",
    ) -> bool:
        """Write a single lead row to either the HOT or COLD worksheet."""
        domain = prospect.get("domain", "")
        company = prospect.get("name", "")
        contact_name = contact.name if contact else ""

        self._connect()

        is_rerun = self.is_duplicate(domain, contact_name)
        if is_rerun:
            logger.info(f"Sheets: RE-RUN detected — {company} / {contact_name or 'no contact'} — writing with Re-run status")

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        score = analyst.get("refined_score", prospect.get("opportunity_score", ""))
        priority = prospect.get("priority", "")
        opp_type = prospect.get("opportunity_type", "")
        gap = prospect.get("transition_gap_timer", "")
        inflection = prospect.get("causal_inflection", "")
        stack = prospect.get("tech_stack_fingerprint", {})
        app = prospect.get("app_intelligence", {})
        pm = prospect.get("power_map", {})
        visionary = pm.get("the_visionary", {})
        operator = pm.get("the_operator", {})
        outreach = prospect.get("outreach", {})

        signals = prospect.get("signals", [])
        top_sig = signals[0] if signals else {}

        obj = outreach.get("objection_stack", [{}, {}, {}])
        obj_inhouse   = obj[0].get("counter", "") if len(obj) > 0 else ""
        obj_incumbent = obj[1].get("counter", "") if len(obj) > 1 else ""
        obj_budget    = obj[2].get("counter", "") if len(obj) > 2 else ""

        vis_email = emails.get("visionary_email", {})
        ops_email = emails.get("operator_email", {})

        apollo_name     = contact.name if contact else ""
        apollo_title    = contact.title if contact else ""
        apollo_email    = contact.email if contact else ""
        apollo_linkedin = contact.linkedin_url if contact else ""

        vis_exa_quote = str(visionary.get("_exa_sheet_quote", "") or "")[:300]
        vis_exa_pain  = str(visionary.get("_exa_sheet_pain",  "") or "")[:300]
        ops_exa_quote = str(operator.get("_exa_sheet_quote",  "") or "")[:300]
        ops_exa_pain  = str(operator.get("_exa_sheet_pain",   "") or "")[:300]

        row = [
            ts, company, domain, priority, f"{score}/100" if score else "",
            opp_type, gap, inflection, _strip_citation(stack.get("incumbent_vendor", "") or ""),
            _fmt_stack(stack), str(app.get("ios_rating", "") or ""),
            str(app.get("android_rating", "") or ""),
            top_sig.get("evidence", "")[:300],
            top_sig.get("source_url", top_sig.get("source_type", "")),
            top_sig.get("confidence", ""), top_sig.get("against", ""),
            visionary.get("name", ""), visionary.get("title", ""),
            visionary.get("linkedin", ""), visionary.get("angle", ""),
            operator.get("name", ""), operator.get("title", ""),
            operator.get("linkedin", ""), operator.get("angle", ""),
            vis_email.get("subject_line", ""), vis_email.get("body", ""),
            ops_email.get("subject_line", ""), ops_email.get("body", ""),
            obj_inhouse, obj_incumbent, obj_budget,
            vis_exa_quote, vis_exa_pain, ops_exa_quote, ops_exa_pain,
            apollo_name, apollo_title, apollo_email, apollo_linkedin,
            outreach.get("salesforce_note", ""), str(prospect.get("research_gaps", "")),
            query, "Re-run" if is_rerun else "New", exa_rejected, gemini_reasoning, bu,
        ]

        target_ws = self._ws_cold if is_cold else self._ws_hot

        if len(row) != len(config.SHEET_COLUMNS):
            logger.error(f"Row mismatch in {target_ws.title} for {company}. "
                         f"Row={len(row)} Cols={len(config.SHEET_COLUMNS)}")
            return False

        target_ws.append_row(row, value_input_option="RAW")
        self._mark_seen(domain, contact_name)
        logger.info(
            f"Sheets: WRITTEN TO {'COLD' if is_cold else 'HOT'} — "
            f"{company} | score={score} | bu={bu}"
            f"{' | RE-RUN' if is_rerun else ''}"
        )
        return True

    # ------------------------------------------------------------------
    # Log write
    # ------------------------------------------------------------------

    def write_log(
        self,
        run_id: str,
        query: str,
        company: str,
        domain: str,
        step: str,
        status: str,
        detail: str = "",
        tokens_in: int = 0,
        tokens_out: int = 0,
        credits: int = 0,
        cost_usd: float = 0.0,
        error: str = "",
        duration_ms: int = 0,
    ) -> None:
        """Write one API call audit row to the Logs worksheet."""
        self._connect()
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        row = [
            ts, run_id, query[:80], company, domain, step, status,
            detail[:300] if detail else "",
            tokens_in or "", tokens_out or "", credits or "",
            round(cost_usd, 4) if cost_usd else "",
            error[:300] if error else "",
            duration_ms or "",
        ]
        try:
            self._ws_logs.append_row(row, value_input_option="RAW")
        except AttributeError:
            logger.error(
                f"Sheets: _ws_logs is None for '{company}' / {step} — "
                f"_connect() may not have initialised the Logs worksheet"
            )
        except Exception as exc:
            logger.error(f"Sheets: log write failed for '{company}' / {step}: {exc}")

    # ------------------------------------------------------------------
    # Signal persistence
    # ------------------------------------------------------------------

    def write_signals(
        self,
        signals: list,
        company: str,
        domain: str,
        bu: str,
        run_id: str,
        score: int = 0,
        prospect_type: str = "",
    ) -> None:
        """
        Write individual signals to the Signals worksheet for historical tracking.
        Called after Sonnet qualification so score is available.
        """
        self._connect()
        if not signals:
            return

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        rows = []
        for sig in signals:
            rows.append([
                ts,
                run_id,
                company,
                domain,
                bu,
                sig.get("signal_type", ""),
                sig.get("evidence", "")[:300],
                sig.get("source_url") or sig.get("source_type", ""),
                sig.get("confidence", ""),
                str(score) if score else "",
                prospect_type,
            ])

        try:
            self._ws_signals.append_rows(rows, value_input_option="RAW")
            logger.info(f"Sheets: {len(rows)} signal(s) written for '{company}'")
        except Exception as exc:
            logger.warning(f"Sheets: signal write failed for '{company}': {exc}")

    # ------------------------------------------------------------------
    # Accounts tab
    # ------------------------------------------------------------------

    def get_accounts(self, bu_filter: str = None) -> list:
        """
        Read all tracked accounts from the Accounts tab.
        Optionally filter by BU.
        """
        self._connect()
        try:
            records = self._ws_accounts.get_all_records()
            if bu_filter:
                records = [r for r in records if r.get("BU", "") == bu_filter]
            return records
        except Exception as exc:
            logger.warning(f"Sheets: could not read accounts: {exc}")
            return []

    def upsert_account(self, row: dict) -> None:
        """
        Add a new account or update an existing one by domain.
        Matches on Domain column.
        """
        self._connect()
        domain = row.get("Domain", "").strip().lower()
        if not domain:
            logger.warning("Sheets: upsert_account called with no domain — skipping")
            return

        try:
            records = self._ws_accounts.get_all_records()
            for i, r in enumerate(records, start=2):  # row 1 is header
                if r.get("Domain", "").strip().lower() == domain:
                    # Update existing row
                    update_row = [
                        row.get("Company", r.get("Company", "")),
                        row.get("Domain", r.get("Domain", "")),
                        row.get("LinkedIn URL", r.get("LinkedIn URL", "")),
                        row.get("BU", r.get("BU", "")),
                        row.get("Tier", r.get("Tier", "")),
                        row.get("Region", r.get("Region", "")),
                        r.get("Last Run", ""),
                        r.get("Status", "Active"),
                    ]
                    self._ws_accounts.update(f"A{i}", [update_row])
                    logger.info(f"Sheets: updated account '{domain}'")
                    return

            # New account
            new_row = [
                row.get("Company", ""),
                row.get("Domain", ""),
                row.get("LinkedIn URL", ""),
                row.get("BU", ""),
                row.get("Tier", ""),
                row.get("Region", ""),
                "",
                "Active",
            ]
            self._ws_accounts.append_row(new_row, value_input_option="RAW")
            logger.info(f"Sheets: added account '{row.get('Company', domain)}'")
        except Exception as exc:
            logger.warning(f"Sheets: upsert_account failed for '{domain}': {exc}")

    def update_account_last_run(self, domain: str, timestamp: str) -> None:
        """Stamp the Last Run timestamp on an account after it has been researched."""
        self._connect()
        domain_lower = domain.strip().lower()
        try:
            records = self._ws_accounts.get_all_records()
            for i, r in enumerate(records, start=2):
                if r.get("Domain", "").strip().lower() == domain_lower:
                    # Last Run is column G (index 7, 1-based)
                    self._ws_accounts.update_cell(i, 7, timestamp)
                    logger.debug(f"Sheets: updated last run for '{domain}'")
                    return
        except Exception as exc:
            logger.warning(f"Sheets: update_account_last_run failed for '{domain}': {exc}")

    # ------------------------------------------------------------------
    # Recent leads (history sidebar)
    # ------------------------------------------------------------------

    def get_recent_leads(self, max_rows: int = 10, bu_filter: str = None) -> list:
        """
        Fetch the most recent leads across both Leads and Cold Leads tabs.
        Optionally filter by BU. Returns list sorted by Timestamp descending.
        """
        self._connect()
        rows = []

        for ws, tab in [(self._ws_hot, "Leads"), (self._ws_cold, "Cold Leads")]:
            try:
                records = ws.get_all_records(expected_headers=config.SHEET_COLUMNS)
                for r in records:
                    if bu_filter and r.get("BU", "") != bu_filter:
                        continue
                    r["_tab"] = tab
                    rows.append(r)
            except Exception as exc:
                logger.warning(f"Sheets: could not fetch recent leads from '{tab}': {exc}")

        def _parse_ts(r):
            try:
                return datetime.strptime(r.get("Timestamp", ""), "%Y-%m-%d %H:%M UTC")
            except Exception:
                return datetime.min

        rows.sort(key=_parse_ts, reverse=True)
        return rows[:max_rows]

    # ------------------------------------------------------------------
    # External reference data — built but gated
    # ------------------------------------------------------------------

    def get_press_sources(self) -> list:
        """
        Read active press sources from the external Press Sources Google Sheet.
        Returns list of dicts with Source Name, URL, Category.
        Degrades gracefully if sheet ID not configured.

        GATED: not called by pipeline until GOOGLE_PRESS_SOURCES_SHEET_ID is set.
        """
        if not config.GOOGLE_PRESS_SOURCES_SHEET_ID:
            logger.debug("Sheets: GOOGLE_PRESS_SOURCES_SHEET_ID not set — skipping press sources")
            return []
        try:
            import json, os
            sa_path = config.GOOGLE_SERVICE_ACCOUNT_JSON
            if os.path.exists(sa_path):
                creds = Credentials.from_service_account_file(sa_path, scopes=SCOPES)
            else:
                sa_info = None
                try:
                    import streamlit as st
                    if "GOOGLE_SERVICE_ACCOUNT_JSON" in st.secrets:
                        sa_info = dict(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"])
                except Exception:
                    pass
                if sa_info is None:
                    sa_info = json.loads(os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "{}"))
                creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES)

            gc = gspread.authorize(creds)
            ss = gc.open_by_key(config.GOOGLE_PRESS_SOURCES_SHEET_ID)
            ws = ss.get_worksheet(0)
            records = ws.get_all_records()
            active = [r for r in records if str(r.get("Active", "")).upper() == "TRUE"]
            logger.info(f"Sheets: loaded {len(active)} active press sources")
            return active
        except Exception as exc:
            logger.warning(f"Sheets: could not load press sources: {exc}")
            return []

    def get_semantic_guide(self) -> str:
        """
        Read semantic search guidance from the external Google Doc.
        Returns plain text content.
        Degrades gracefully if doc ID not configured.

        GATED: not called by pipeline until GOOGLE_SEMANTIC_GUIDE_DOC_ID is set.
        """
        if not config.GOOGLE_SEMANTIC_GUIDE_DOC_ID:
            logger.debug("Sheets: GOOGLE_SEMANTIC_GUIDE_DOC_ID not set — skipping semantic guide")
            return ""
        try:
            # Google Docs export as plain text via Drive API
            import requests as req
            import json, os
            sa_path = config.GOOGLE_SERVICE_ACCOUNT_JSON
            if os.path.exists(sa_path):
                creds = Credentials.from_service_account_file(sa_path, scopes=SCOPES)
            else:
                sa_info = None
                try:
                    import streamlit as st
                    if "GOOGLE_SERVICE_ACCOUNT_JSON" in st.secrets:
                        sa_info = dict(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"])
                except Exception:
                    pass
                if sa_info is None:
                    sa_info = json.loads(os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "{}"))
                creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES)

            from google.auth.transport.requests import Request
            creds.refresh(Request())
            url = f"https://docs.googleapis.com/v1/documents/{config.GOOGLE_SEMANTIC_GUIDE_DOC_ID}"
            headers = {"Authorization": f"Bearer {creds.token}"}
            resp = req.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                doc = resp.json()
                text_parts = []
                for block in doc.get("body", {}).get("content", []):
                    for el in block.get("paragraph", {}).get("elements", []):
                        text_parts.append(el.get("textRun", {}).get("content", ""))
                content = "".join(text_parts).strip()
                logger.info(f"Sheets: loaded semantic guide ({len(content)} chars)")
                return content
            logger.warning(f"Sheets: semantic guide fetch returned {resp.status_code}")
            return ""
        except Exception as exc:
            logger.warning(f"Sheets: could not load semantic guide: {exc}")
            return ""

    # ------------------------------------------------------------------
    # Usage Tracker
    # ------------------------------------------------------------------

    def write_usage(
        self,
        run_id: str,
        director: str,
        track: str,
        query: str,
        companies_researched: int,
        usage_summary: dict,
        bu: str = "",
    ) -> None:
        """Write one row to the Usage Tracker tab after a pipeline run completes."""
        self._connect()
        ts    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        month = datetime.now(timezone.utc).strftime("%Y-%m")

        grok_cost   = usage_summary.get("grok", {}).get("cost_usd", 0)
        sonnet_cost = usage_summary.get("sonnet", {}).get("cost_usd", 0)
        opus_cost   = usage_summary.get("opus", {}).get("cost_usd", 0)
        gemini_cost = usage_summary.get("gemini", {}).get("cost_usd", 0)
        exa_cost    = usage_summary.get("exa", {}).get("cost_usd", 0)
        apollo_cost = usage_summary.get("apollo", {}).get("cost_usd", 0)
        total_cost  = usage_summary.get("total_cost_usd", 0)

        row = [
            ts, run_id, director, track,
            query[:120], companies_researched,
            round(grok_cost, 4), round(sonnet_cost, 4),
            round(opus_cost, 4), round(gemini_cost, 4),
            round(exa_cost, 4), round(apollo_cost, 4),
            round(total_cost, 4), month, bu,
        ]
        try:
            self._ws_usage.append_row(row, value_input_option="RAW")
            logger.info(
                f"Sheets: Usage logged — {director} | {track} | "
                f"${total_cost:.4f} | {companies_researched} companies"
            )
        except Exception as exc:
            logger.error(f"Sheets: Usage write failed: {exc}")

    def get_director_month_spend(self, director: str) -> list:
        """
        Return list of Total Cost USD values for this director in the current month.
        Used by auth.py to calculate budget remaining.
        """
        self._connect()
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        try:
            rows = self._ws_usage.get_all_records()
            return [
                float(r.get("Total Cost USD", 0) or 0)
                for r in rows
                if r.get("Sales Director") == director
                and str(r.get("Month", "")).startswith(month)
            ]
        except Exception as exc:
            logger.warning(f"Sheets: could not read usage for {director}: {exc}")
            return []

    # ------------------------------------------------------------------
    # Company Enrichment
    # ------------------------------------------------------------------

    def write_enrichment(
        self,
        run_id: str,
        director: str,
        company: str,
        domain: str,
        hq_country: str,
        opportunity_score: int = 0,
        verdict: str = "",
        causal_inflection: str = "",
        transition_gap: str = "",
        incumbent_vendor: str = "",
        top_signal: str = "",
        entry_point: str = "",
        risk_if_no_action: str = "",
        visionary_name: str = "",
        visionary_title: str = "",
        visionary_linkedin: str = "",
        operator_name: str = "",
        operator_title: str = "",
        operator_linkedin: str = "",
        decision_makers: list = None,
        intent_topics: list = None,
        grok_signal_summary: str = "",
        competitors: list = None,
        bu: str = "",
    ) -> None:
        """Write one row to the Company Enrichment tab."""
        self._connect()
        import json as _json
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        row = [
            ts, run_id, director, company, domain, hq_country,
            opportunity_score, verdict,
            causal_inflection[:500],
            transition_gap[:300],
            incumbent_vendor[:200],
            top_signal[:300],
            entry_point[:500],
            risk_if_no_action[:500],
            visionary_name, visionary_title, visionary_linkedin,
            operator_name, operator_title, operator_linkedin,
            _json.dumps(decision_makers or [], ensure_ascii=False)[:2000],
            ", ".join(intent_topics or [])[:300],
            grok_signal_summary[:800],
            _json.dumps(competitors or [], ensure_ascii=False)[:2000],
            bu, "Fresh",
        ]
        try:
            self._ws_enrichment.append_row(row, value_input_option="RAW")
            logger.info(f"Sheets: Enrichment written — {company} | score={opportunity_score} | {director}")
        except Exception as exc:
            logger.error(f"Sheets: Enrichment write failed: {exc}")

    def get_enrichment_cache(self, domain: str, max_age_days: int = 90) -> Optional[dict]:
        """
        Return the most recent enrichment row for this domain if within max_age_days.
        Returns None if not found or too old.
        """
        self._connect()
        try:
            rows = self._ws_enrichment.get_all_records()
            from datetime import timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
            matches = [
                r for r in rows
                if r.get("Domain", "").lower() == domain.lower()
            ]
            if not matches:
                return None
            # Most recent first
            matches.sort(key=lambda r: r.get("Timestamp", ""), reverse=True)
            latest = matches[0]
            ts_str = latest.get("Timestamp", "")
            try:
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M UTC").replace(
                    tzinfo=timezone.utc
                )
                if ts < cutoff:
                    return None
            except Exception:
                return None
            return latest
        except Exception as exc:
            logger.warning(f"Sheets: enrichment cache lookup failed: {exc}")
            return None

    # ------------------------------------------------------------------
    # User preferences
    # ------------------------------------------------------------------

    def get_user_bu(self, email: str) -> Optional[str]:
        """Return the stored BU preference for this user, or None if not set."""
        self._connect()
        try:
            records = self._ws_user_prefs.get_all_records()
            for r in records:
                if r.get("Email", "").strip().lower() == email.strip().lower():
                    bu = r.get("BU", "").strip()
                    return bu if bu else None
            return None
        except Exception as exc:
            logger.warning(f"Sheets: could not read user prefs for {email}: {exc}")
            return None

    def set_user_bu(self, email: str, bu: str) -> None:
        """Upsert the BU preference for this user."""
        self._connect()
        ts          = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        email_lower = email.strip().lower()
        try:
            records = self._ws_user_prefs.get_all_records()
            for i, r in enumerate(records, start=2):
                if r.get("Email", "").strip().lower() == email_lower:
                    self._ws_user_prefs.update(f"A{i}", [[email, bu, ts]])
                    logger.info(f"Sheets: updated BU pref for {email} → {bu}")
                    return
            self._ws_user_prefs.append_row([email, bu, ts], value_input_option="RAW")
            logger.info(f"Sheets: wrote new BU pref for {email} → {bu}")
        except Exception as exc:
            logger.warning(f"Sheets: could not set user pref for {email}: {exc}")


def _strip_citation(value: str) -> str:
    import re
    if not value:
        return value
    cleaned = re.sub(
        r'\s*\((?:Source|source|via|Via|from|From|ref|Ref)[^)]*\)', '', value
    ).strip()
    cleaned = re.sub(r'\s*\(https?://[^)]+\)', '', cleaned).strip()
    return cleaned


def _fmt_stack(stack: dict) -> str:
    parts = []
    for key in ("video_player", "cdn", "ovp", "drm", "ssai"):
        val = _strip_citation(stack.get(key, "") or "")
        if val:
            parts.append(f"{key.replace('_', ' ').title()}: {val}")
    return " | ".join(parts)
