"""
core/enrichment_runner.py — Company Enrichment track (Track 2).

Full pipeline per company:
1. Check Sheets cache (90 days)
2. Run full Grok research waterfall (same as Discovery deep research)
3. Optional: find 3 competitors + run light Grok pass on each
4. Write to Company Enrichment tab
5. Return structured result for GUI display
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import List, Optional

import config
from utils.helpers import with_retries

logger = logging.getLogger("ott_lead_gen.enrichment")


# ---------------------------------------------------------------------------
# Cost constants
# ---------------------------------------------------------------------------

COST_PER_FULL_WATERFALL  = 0.55   # Grok full waterfall avg
COST_PER_LIGHT_PASS      = 0.12   # Grok light competitor pass avg
COST_PER_COMPANY_WITH_COMPETITORS    = COST_PER_FULL_WATERFALL + (3 * COST_PER_LIGHT_PASS)
COST_PER_COMPANY_WITHOUT_COMPETITORS = COST_PER_FULL_WATERFALL

MAX_TOTAL_CALLS = 15  # hard cap: direct companies + competitors


# ---------------------------------------------------------------------------
# Competitor identification prompt
# ---------------------------------------------------------------------------

COMPETITOR_IDENTIFICATION_PROMPT = """
You are a B2B sales researcher for Accedo, an OTT front-end development firm.

Given the company below, identify exactly 3 direct competitors — companies that:
1. Operate in the same vertical (sports, news, entertainment, etc.)
2. Are of similar or slightly larger scale
3. Are headquartered in the same geographic region
4. Could plausibly be in the market for OTT platform services

For each competitor, provide a 2-sentence argument for or against why they might be
a BETTER outreach opportunity than {company} right now.

Target company: {company}
Domain: {domain}
HQ Country: {hq_country}
Opportunity Score for {company}: {score}/100
Top signal for {company}: {top_signal}

Return ONLY this JSON, no preamble:
{{
  "competitors": [
    {{
      "name": "Competitor Name",
      "domain": "competitor.com",
      "hq_country": "Country",
      "argument": "2-sentence argument for or against this being a better opportunity than {company}.",
      "better_opportunity": true
    }}
  ]
}}
"""


# ---------------------------------------------------------------------------
# Light competitor pass prompt
# ---------------------------------------------------------------------------

COMPETITOR_LIGHT_PASS_PROMPT = """
You are a B2B sales researcher for Accedo, an OTT front-end development firm.

Run a QUICK scan of {company} ({domain}) as a potential OTT platform development prospect.
Focus only on: current platform signals, recent hiring, any vendor migration indicators.
Do NOT do a full waterfall — this is a 2-minute quick scan only.

Return a brief JSON assessment:
{{
  "opportunity_score": 0-100,
  "top_signal": "One sentence describing the strongest buying signal found",
  "verdict": "HOT | WARM | COLD",
  "argument": "2 sentences: why this company is or isn't a better opportunity than the original target"
}}
"""


# ---------------------------------------------------------------------------
# Domain resolution
# ---------------------------------------------------------------------------

def _resolve_domain(company: str) -> str:
    """Best-effort domain resolution from company name via Apollo."""
    import requests
    if not config.APOLLO_MASTER_API_KEY:
        return ""
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
# Full Grok waterfall for enrichment
# ---------------------------------------------------------------------------

def _run_full_waterfall(company: str, domain: str, usage_tracker=None) -> dict:
    """
    Run the full Grok research waterfall on a named company.
    Returns the same prospect dict as the Discovery deep research path.
    """
    from tools.grok import run_research_waterfall
    query = f"{company} ({domain})" if domain else company
    try:
        result = run_research_waterfall(query, usage_tracker=usage_tracker)
        prospects = result.get("prospects", [])
        if prospects:
            return prospects[0]
        return {}
    except Exception as exc:
        logger.error(f"Enrichment: full waterfall failed for {company}: {exc}")
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Competitor identification
# ---------------------------------------------------------------------------

def _identify_competitors(
    company: str,
    domain: str,
    hq_country: str,
    score: int,
    top_signal: str,
    usage_tracker=None,
) -> list:
    """
    Ask Grok to identify 3 competitors and provide a for/against argument.
    Returns list of competitor dicts.
    """
    import requests
    import re

    if not config.XAI_API_KEY:
        return []

    prompt = COMPETITOR_IDENTIFICATION_PROMPT.format(
        company=company,
        domain=domain,
        hq_country=hq_country,
        score=score,
        top_signal=top_signal,
    )

    url     = "https://api.x.ai/v1/responses"
    headers = {
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {config.XAI_API_KEY}",
    }
    payload = {
        "model":   config.GROK_SCOUT_MODEL,
        "input":   [{"role": "user", "content": prompt}],
        "tools":   [{"type": "web_search"}],
        "temperature": 0.2,
        "store_messages": True,
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        if resp.status_code != 200:
            logger.warning(f"Enrichment: competitor ID failed {resp.status_code}")
            return []

        data = resp.json()
        raw  = ""
        for item in data.get("output", []):
            if item.get("type") == "message":
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        raw = part.get("text", "")
                        break
            if raw:
                break

        if usage_tracker:
            usage = data.get("usage", {})
            usage_tracker.record_grok(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            )

        # Parse JSON
        cleaned = raw.strip()
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            cleaned = m.group(0)
        result = json.loads(cleaned)
        return result.get("competitors", [])

    except Exception as exc:
        logger.warning(f"Enrichment: competitor identification failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# Light competitor pass
# ---------------------------------------------------------------------------

def _light_competitor_pass(
    competitor_name: str,
    competitor_domain: str,
    original_company: str,
    existing_argument: str,
    usage_tracker=None,
) -> dict:
    """
    Run a quick Grok scan on a competitor to validate the argument.
    Returns enriched competitor dict.
    """
    import requests
    import re

    if not config.XAI_API_KEY:
        return {
            "name": competitor_name,
            "domain": competitor_domain,
            "argument": existing_argument,
            "opportunity_score": 0,
            "verdict": "COLD",
            "better_opportunity": False,
        }

    prompt = COMPETITOR_LIGHT_PASS_PROMPT.format(
        company=competitor_name,
        domain=competitor_domain,
    ) + f"\nOriginal target was: {original_company}. Argument so far: {existing_argument}"

    url     = "https://api.x.ai/v1/responses"
    headers = {
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {config.XAI_API_KEY}",
    }
    payload = {
        "model":   config.GROK_SCOUT_MODEL,
        "input":   [{"role": "user", "content": prompt}],
        "tools":   [{"type": "web_search"}],
        "temperature": 0.2,
        "store_messages": True,
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        if resp.status_code != 200:
            return {"name": competitor_name, "domain": competitor_domain,
                    "argument": existing_argument, "opportunity_score": 0,
                    "verdict": "COLD", "better_opportunity": False}

        data = resp.json()
        raw  = ""
        for item in data.get("output", []):
            if item.get("type") == "message":
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        raw = part.get("text", "")
                        break
            if raw:
                break

        if usage_tracker:
            usage = data.get("usage", {})
            usage_tracker.record_grok(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            )

        cleaned = raw.strip()
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            cleaned = m.group(0)
        light_result = json.loads(cleaned)

        return {
            "name":               competitor_name,
            "domain":             competitor_domain,
            "hq_country":         "",
            "argument":           light_result.get("argument", existing_argument),
            "opportunity_score":  light_result.get("opportunity_score", 0),
            "verdict":            light_result.get("verdict", "COLD"),
            "better_opportunity": light_result.get("opportunity_score", 0) > 0,
        }

    except Exception as exc:
        logger.warning(f"Enrichment: light pass failed for {competitor_name}: {exc}")
        return {
            "name": competitor_name,
            "domain": competitor_domain,
            "argument": existing_argument,
            "opportunity_score": 0,
            "verdict": "COLD",
            "better_opportunity": False,
        }


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------

def estimate_enrichment_cost(
    company_count: int,
    cached_count: int = 0,
    include_competitors: bool = False,
) -> dict:
    """
    Estimate cost for enriching a list of companies.
    Respects the MAX_TOTAL_CALLS cap.
    """
    fresh = company_count - cached_count

    if include_competitors:
        # With competitors: each company = 1 full + 3 light passes = 4 calls
        total_calls     = fresh * 4
        over_cap        = total_calls > MAX_TOTAL_CALLS
        capped_fresh    = min(fresh, MAX_TOTAL_CALLS // 4)
        cost_per_fresh  = COST_PER_COMPANY_WITH_COMPETITORS
        max_companies   = MAX_TOTAL_CALLS // 4  # = 3
    else:
        total_calls     = fresh
        over_cap        = total_calls > MAX_TOTAL_CALLS
        capped_fresh    = min(fresh, MAX_TOTAL_CALLS)
        cost_per_fresh  = COST_PER_COMPANY_WITHOUT_COMPETITORS
        max_companies   = MAX_TOTAL_CALLS  # = 15

    effective_fresh = capped_fresh
    total_cost      = round(effective_fresh * cost_per_fresh, 2)

    return {
        "total_companies":     company_count,
        "cached":              cached_count,
        "fresh":               fresh,
        "effective_fresh":     effective_fresh,
        "cost_per_fresh":      cost_per_fresh,
        "estimated_total":     total_cost,
        "include_competitors": include_competitors,
        "total_calls":         effective_fresh * (4 if include_competitors else 1),
        "over_cap":            over_cap,
        "max_companies":       max_companies,
    }


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------

def parse_company_input(text: str = "", csv_bytes: bytes = None) -> list:
    """
    Parse company names from comma/newline separated text or CSV bytes.
    Returns deduplicated list, hard-capped at 15.
    """
    names = []

    if text and text.strip():
        for part in text.replace("\n", ",").split(","):
            name = part.strip().strip('"').strip("'")
            if name:
                names.append(name)

    if csv_bytes:
        import io
        import csv
        try:
            reader = csv.reader(io.StringIO(csv_bytes.decode("utf-8", errors="replace")))
            for i, row in enumerate(reader):
                if not row:
                    continue
                if i == 0 and row[0].lower() in ("company", "company name", "name", "organisation"):
                    continue
                name = row[0].strip().strip('"')
                if name:
                    names.append(name)
        except Exception as exc:
            logger.warning(f"CSV parse error: {exc}")

    seen   = set()
    result = []
    for n in names:
        key = n.lower()
        if key not in seen:
            seen.add(key)
            result.append(n)

    return result[:MAX_TOTAL_CALLS]


# ---------------------------------------------------------------------------
# Single company enrichment
# ---------------------------------------------------------------------------

def run_company_enrichment(
    company: str,
    bu: str = "",
    director: str = "",
    run_id: str = "",
    include_competitors: bool = False,
    sheets=None,
    usage_tracker=None,
) -> dict:
    """
    Full enrichment pipeline for one company.

    1. Check 90-day Sheets cache
    2. Resolve domain via Apollo
    3. Run full Grok research waterfall
    4. Optional: identify 3 competitors + light pass each
    5. Write to Company Enrichment tab
    6. Return result dict for GUI

    Returns:
        {
            "company", "domain", "hq_country",
            "opportunity_score", "verdict",
            "causal_inflection", "transition_gap", "incumbent_vendor",
            "top_signal", "entry_point", "risk_if_no_action",
            "visionary_name", "visionary_title", "visionary_linkedin",
            "operator_name", "operator_title", "operator_linkedin",
            "decision_makers", "intent_topics", "grok_signal_summary",
            "competitors",
            "from_cache", "cached_date", "error"
        }
    """
    from core.sheets import SheetsClient

    run_id  = run_id  or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    sheets  = sheets  or SheetsClient()
    company = company.strip()

    if not company:
        return {"error": "Company name is required.", "company": "", "domain": ""}

    logger.info(f"Enrichment: starting '{company}' | director={director} | competitors={include_competitors}")

    # Step 1 — resolve domain
    domain = _resolve_domain(company)
    logger.info(f"Enrichment: domain → '{domain}'")

    # Step 2 — check cache
    if domain:
        cached = sheets.get_enrichment_cache(domain, max_age_days=90)
        if cached:
            import json as _json
            logger.info(f"Enrichment: cache hit for '{company}'")
            try:
                dms = _json.loads(cached.get("Decision Makers", "[]"))
            except Exception:
                dms = []
            try:
                comps = _json.loads(cached.get("Competitors", "[]"))
            except Exception:
                comps = []
            return {
                "company":            cached.get("Company", company),
                "domain":             domain,
                "hq_country":         cached.get("HQ Country", ""),
                "opportunity_score":  int(cached.get("Opportunity Score", 0) or 0),
                "verdict":            cached.get("Verdict", ""),
                "causal_inflection":  cached.get("Causal Inflection", ""),
                "transition_gap":     cached.get("Transition Gap", ""),
                "incumbent_vendor":   cached.get("Incumbent Vendor", ""),
                "top_signal":         cached.get("Top Signal", ""),
                "entry_point":        cached.get("Entry Point", ""),
                "risk_if_no_action":  cached.get("Risk if No Action", ""),
                "visionary_name":     cached.get("Visionary Name", ""),
                "visionary_title":    cached.get("Visionary Title", ""),
                "visionary_linkedin": cached.get("Visionary LinkedIn", ""),
                "operator_name":      cached.get("Operator Name", ""),
                "operator_title":     cached.get("Operator Title", ""),
                "operator_linkedin":  cached.get("Operator LinkedIn", ""),
                "decision_makers":    dms,
                "intent_topics":      [t.strip() for t in cached.get("Intent Topics", "").split(",") if t.strip()],
                "grok_signal_summary": cached.get("Grok Signal Summary", ""),
                "competitors":        comps,
                "from_cache":         True,
                "cached_date":        cached.get("Timestamp", ""),
                "error":              None,
            }

    # Step 3 — Full Grok waterfall
    t0       = time.monotonic()
    prospect = _run_full_waterfall(company, domain, usage_tracker=usage_tracker)
    logger.info(f"Enrichment: waterfall done in {time.monotonic()-t0:.1f}s")

    if prospect.get("error"):
        return {
            "company": company, "domain": domain,
            "error": prospect["error"],
            "from_cache": False, "competitors": [],
        }

    # Extract fields from prospect
    pm              = prospect.get("power_map", {})
    vis             = pm.get("the_visionary", {})
    ops             = pm.get("the_operator",  {})
    signals         = prospect.get("signals", [])
    top_sig         = signals[0].get("evidence", "") if signals else ""
    hq_country      = prospect.get("hq_country", "")
    score           = int(prospect.get("opportunity_score") or 0)
    verdict_raw     = "HOT" if score >= 70 else "WARM" if score >= 50 else "COLD"

    result = {
        "company":            company,
        "domain":             domain or prospect.get("domain", ""),
        "hq_country":         hq_country,
        "opportunity_score":  score,
        "verdict":            verdict_raw,
        "causal_inflection":  prospect.get("causal_inflection", ""),
        "transition_gap":     prospect.get("transition_gap_timer", ""),
        "incumbent_vendor":   prospect.get("incumbent_vendor", ""),
        "top_signal":         top_sig,
        "entry_point":        "",
        "risk_if_no_action":  "",
        "visionary_name":     vis.get("name", ""),
        "visionary_title":    vis.get("title", ""),
        "visionary_linkedin": vis.get("linkedin", ""),
        "operator_name":      ops.get("name", ""),
        "operator_title":     ops.get("title", ""),
        "operator_linkedin":  ops.get("linkedin", ""),
        "decision_makers":    [{"name": vis.get("name", ""), "title": vis.get("title", ""),
                                "linkedin": vis.get("linkedin", "")},
                               {"name": ops.get("name", ""), "title": ops.get("title", ""),
                                "linkedin": ops.get("linkedin", "")}] if vis.get("name") else [],
        "intent_topics":      [],
        "grok_signal_summary": top_sig,
        "competitors":        [],
        "from_cache":         False,
        "cached_date":        "",
        "error":              None,
        "prospect":           prospect,  # keep full prospect for result card display
    }

    # Step 4 — Optional competitor analysis
    if include_competitors:
        logger.info(f"Enrichment: identifying competitors for '{company}'")
        t0          = time.monotonic()
        competitors = _identify_competitors(
            company=company,
            domain=domain,
            hq_country=hq_country,
            score=score,
            top_signal=top_sig,
            usage_tracker=usage_tracker,
        )
        logger.info(f"Enrichment: {len(competitors)} competitors identified in {time.monotonic()-t0:.1f}s")

        enriched_competitors = []
        for comp in competitors[:3]:
            logger.info(f"Enrichment: light pass on {comp.get('name', '')}")
            enriched = _light_competitor_pass(
                competitor_name=comp.get("name", ""),
                competitor_domain=comp.get("domain", ""),
                original_company=company,
                existing_argument=comp.get("argument", ""),
                usage_tracker=usage_tracker,
            )
            enriched_competitors.append(enriched)

        result["competitors"] = enriched_competitors

    # Step 5 — Write to Sheets
    try:
        sheets.write_enrichment(
            run_id=run_id,
            director=director,
            company=company,
            domain=result["domain"],
            hq_country=hq_country,
            opportunity_score=score,
            verdict=verdict_raw,
            causal_inflection=result["causal_inflection"],
            transition_gap=result["transition_gap"],
            incumbent_vendor=result["incumbent_vendor"],
            top_signal=top_sig,
            entry_point=result["entry_point"],
            risk_if_no_action=result["risk_if_no_action"],
            visionary_name=result["visionary_name"],
            visionary_title=result["visionary_title"],
            visionary_linkedin=result["visionary_linkedin"],
            operator_name=result["operator_name"],
            operator_title=result["operator_title"],
            operator_linkedin=result["operator_linkedin"],
            decision_makers=result["decision_makers"],
            intent_topics=result["intent_topics"],
            grok_signal_summary=result["grok_signal_summary"],
            competitors=result["competitors"],
            bu=bu,
        )
    except Exception as exc:
        logger.error(f"Enrichment: Sheets write failed: {exc}")

    return result


# ---------------------------------------------------------------------------
# Bulk enrichment
# ---------------------------------------------------------------------------

def run_bulk_enrichment(
    companies: list,
    bu: str = "",
    director: str = "",
    include_competitors: bool = False,
    dry_run: bool = False,
    sheets=None,
    usage_tracker=None,
    on_company_start: callable = None,
    on_company_done: callable = None,
) -> list:
    """
    Enrich a list of companies, respecting the MAX_TOTAL_CALLS cap.
    """
    from core.sheets import SheetsClient

    sheets  = sheets  or SheetsClient()
    run_id  = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    total   = len(companies)
    results = []

    # Apply cap
    if include_competitors:
        max_direct = MAX_TOTAL_CALLS // 4
        companies  = companies[:max_direct]
    else:
        companies  = companies[:MAX_TOTAL_CALLS]

    for idx, company in enumerate(companies, 1):
        if on_company_start:
            on_company_start(company, idx, len(companies))

        if dry_run:
            domain = _resolve_domain(company)
            cached = sheets.get_enrichment_cache(domain) if domain else None
            result = {
                "company":    company,
                "domain":     domain,
                "from_cache": bool(cached),
                "dry_run":    True,
                "error":      None,
            }
        else:
            result = run_company_enrichment(
                company=company,
                bu=bu,
                director=director,
                run_id=run_id,
                include_competitors=include_competitors,
                sheets=sheets,
                usage_tracker=usage_tracker,
            )

        results.append(result)

        if on_company_done:
            on_company_done(company, result, idx, len(companies))

    return results