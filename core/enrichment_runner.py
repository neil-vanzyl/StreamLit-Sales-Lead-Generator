"""
core/enrichment_runner.py — Company Enrichment track (Track 2).

Given a company name:
1. Check Sheets cache — return cached result if < 90 days old
2. Apollo: find decision makers + intent signals
3. Grok: quick signal sweep for recent OTT buying signals
4. Write to Company Enrichment tab
5. Return structured result for GUI display
"""

import logging
import time
from datetime import datetime, timezone

import config
from utils.helpers import with_retries

logger = logging.getLogger("ott_lead_gen.enrichment")


# ---------------------------------------------------------------------------
# Apollo enrichment — decision makers + intent
# ---------------------------------------------------------------------------

def _fetch_apollo_enrichment(company: str, domain: str) -> dict:
    """
    Pull decision makers and intent signals from Apollo for a named company.
    Returns dict with 'decision_makers', 'c_suite_changes', 'intent_topics'.
    """
    import requests

    if not config.APOLLO_MASTER_API_KEY:
        logger.warning("Enrichment: APOLLO_MASTER_API_KEY not set")
        return {"decision_makers": [], "c_suite_changes": "", "intent_topics": []}

    DECISION_MAKER_TITLES = [
        "Chief Executive Officer", "CEO",
        "Chief Technology Officer", "CTO",
        "Chief Product Officer", "CPO",
        "Chief Revenue Officer", "CRO",
        "Chief Content Officer",
        "President", "General Manager",
        "VP Engineering", "SVP Engineering",
        "VP Product", "VP Technology",
        "VP Streaming", "VP OTT", "Head of OTT",
        "Head of Streaming", "Head of Digital",
        "SVP Digital", "VP Digital",
        "Managing Director",
    ]

    SENIORITIES = ["c_suite", "vp", "partner", "owner", "founder", "head", "director"]

    decision_makers = []
    c_suite_changes = ""
    intent_topics   = []

    # --- People Search ---
    try:
        payload = {
            "q_organization_domains_list": [domain] if domain else [],
            "q_keywords": company if not domain else "",
            "person_titles": DECISION_MAKER_TITLES[:8],
            "person_seniorities": SENIORITIES,
            "per_page": 10,
        }
        resp = requests.post(
            "https://api.apollo.io/api/v1/mixed_people/api_search",
            json=payload,
            headers={"Content-Type": "application/json",
                     "X-Api-Key": config.APOLLO_MASTER_API_KEY},
            timeout=25,
        )
        if resp.status_code == 200:
            people = resp.json().get("people", [])
            for p in people:
                li = p.get("linkedin_url", "") or ""
                if li and not li.startswith("http"):
                    li = f"https://www.linkedin.com/in/{li}"
                decision_makers.append({
                    "name":       p.get("name", ""),
                    "title":      p.get("title", ""),
                    "linkedin":   li,
                    "email":      p.get("email", ""),
                    "seniority":  p.get("seniority", ""),
                    "city":       p.get("city", ""),
                    "country":    p.get("country", ""),
                })
            logger.info(f"Enrichment: Apollo found {len(decision_makers)} decision makers")
        else:
            logger.warning(f"Enrichment: Apollo people search {resp.status_code}")
    except Exception as exc:
        logger.warning(f"Enrichment: Apollo people search failed: {exc}")

    # --- Intent Topics (Bombora) ---
    try:
        if config.APOLLO_MASTER_API_KEY and domain:
            intent_resp = requests.post(
                "https://api.apollo.io/api/v1/organizations/bulk_enrich",
                json={"domains": [domain], "reveal_intent_signals": True},
                headers={"Content-Type": "application/json",
                         "X-Api-Key": config.APOLLO_MASTER_API_KEY},
                timeout=25,
            )
            if intent_resp.status_code == 200:
                orgs = intent_resp.json().get("organizations", [])
                if orgs:
                    org = orgs[0]
                    raw_intent = org.get("intent_signals", []) or []
                    intent_topics = [
                        s.get("topic", "") for s in raw_intent if s.get("topic")
                    ][:10]
                    logger.info(f"Enrichment: {len(intent_topics)} intent topics found")
    except Exception as exc:
        logger.warning(f"Enrichment: Apollo intent failed: {exc}")

    return {
        "decision_makers": decision_makers,
        "c_suite_changes": c_suite_changes,
        "intent_topics":   intent_topics,
    }


# ---------------------------------------------------------------------------
# Grok signal sweep for enrichment
# ---------------------------------------------------------------------------

def _fetch_grok_signals(company: str, domain: str, bu: str = "") -> str:
    """
    Quick Grok web search for recent OTT buying signals for a named company.
    Returns a 2-3 sentence summary string.
    """
    from tools.grok import run_discovery_waterfall

    brief = (
        f"Find the most recent OTT/streaming/CTV buying signals for {company} "
        f"({domain}). Look for: platform launches, vendor changes, job postings "
        f"for streaming roles, funding, rights deals, app store issues, or "
        f"leadership changes in digital/streaming. Focus on signals from the "
        f"last 12 months. Return only 1-3 companies max."
    )

    try:
        result    = run_discovery_waterfall(brief, bu=bu)
        companies = result.get("companies", [])
        summary   = result.get("search_summary", "")

        # Find signal for this specific company
        for c in companies:
            if company.lower() in c.get("name", "").lower():
                evidence = c.get("evidence", "")
                signal   = c.get("signal_type", "")
                if evidence:
                    return f"[{signal}] {evidence}"

        return summary or "No recent OTT signals found."
    except Exception as exc:
        logger.warning(f"Enrichment: Grok signal sweep failed: {exc}")
        return "Signal sweep unavailable."


# ---------------------------------------------------------------------------
# Domain lookup helper
# ---------------------------------------------------------------------------

def _resolve_domain(company: str) -> str:
    """Best-effort domain resolution from company name."""
    import requests
    try:
        resp = requests.post(
            "https://api.apollo.io/api/v1/organizations/enrich",
            json={"name": company},
            headers={"Content-Type": "application/json",
                     "X-Api-Key": config.APOLLO_MASTER_API_KEY},
            timeout=15,
        )
        if resp.status_code == 200:
            org = resp.json().get("organization", {})
            return org.get("primary_domain", "") or ""
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_company_enrichment(
    company: str,
    bu: str = "",
    director: str = "",
    run_id: str = "",
    sheets=None,
) -> dict:
    """
    Full enrichment pipeline for a named company.

    1. Check Sheets cache (90 days)
    2. Resolve domain via Apollo
    3. Apollo: decision makers + intent topics
    4. Grok: recent signal sweep
    5. Write to Company Enrichment tab
    6. Return result dict for GUI

    Returns:
        {
            "company":           str,
            "domain":            str,
            "hq_country":        str,
            "decision_makers":   list,
            "c_suite_changes":   str,
            "intent_topics":     list,
            "grok_signal":       str,
            "from_cache":        bool,
            "cached_date":       str,
            "error":             str or None,
        }
    """
    from core.sheets import SheetsClient

    run_id  = run_id  or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    sheets  = sheets  or SheetsClient()
    company = company.strip()

    if not company:
        return {"error": "Company name is required.", "company": "", "domain": ""}

    logger.info(f"Enrichment: starting for '{company}' | director={director} | bu={bu}")

    # Step 1 — resolve domain
    domain = _resolve_domain(company)
    logger.info(f"Enrichment: domain resolved → '{domain}'")

    # Step 2 — check cache
    if domain:
        cached = sheets.get_enrichment_cache(domain, max_age_days=90)
        if cached:
            import json as _json
            logger.info(f"Enrichment: cache hit for '{company}' ({cached.get('Timestamp')})")
            try:
                dms = _json.loads(cached.get("Decision Makers", "[]"))
            except Exception:
                dms = []
            return {
                "company":         cached.get("Company", company),
                "domain":          domain,
                "hq_country":      cached.get("HQ Country", ""),
                "decision_makers": dms,
                "c_suite_changes": cached.get("C-Suite Changes", ""),
                "intent_topics":   [
                    t.strip() for t in
                    cached.get("Intent Topics", "").split(",") if t.strip()
                ],
                "grok_signal":     cached.get("Grok Signal Summary", ""),
                "from_cache":      True,
                "cached_date":     cached.get("Timestamp", ""),
                "error":           None,
            }

    # Step 3 — Apollo enrichment
    t0     = time.monotonic()
    apollo = _fetch_apollo_enrichment(company, domain)
    logger.info(f"Enrichment: Apollo done in {time.monotonic()-t0:.1f}s")

    # Step 4 — Grok signal sweep
    t0           = time.monotonic()
    grok_signal  = _fetch_grok_signals(company, domain, bu=bu)
    hq_country   = ""
    logger.info(f"Enrichment: Grok done in {time.monotonic()-t0:.1f}s")

    # Step 5 — write to Sheets
    try:
        sheets.write_enrichment(
            run_id=run_id,
            director=director,
            company=company,
            domain=domain,
            hq_country=hq_country,
            decision_makers=apollo["decision_makers"],
            c_suite_changes=apollo["c_suite_changes"],
            intent_topics=apollo["intent_topics"],
            grok_signal_summary=grok_signal,
            bu=bu,
        )
    except Exception as exc:
        logger.error(f"Enrichment: Sheets write failed: {exc}")

    return {
        "company":         company,
        "domain":          domain,
        "hq_country":      hq_country,
        "decision_makers": apollo["decision_makers"],
        "c_suite_changes": apollo["c_suite_changes"],
        "intent_topics":   apollo["intent_topics"],
        "grok_signal":     grok_signal,
        "from_cache":      False,
        "cached_date":     "",
        "error":           None,
    }