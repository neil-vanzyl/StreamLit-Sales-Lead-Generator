"""
OTT Lead Generation Pipeline — Frontier Edition
================================================
Full pipeline steps per prospect:

  1. Grok        — autonomous research waterfall (SEC, jobs, press, app stores)
  2. Apollo      — validate/discover power map contacts, get LinkedIn URLs + emails
  3. Exa         — LinkedIn post intelligence per exec (uses Apollo's confirmed URLs)
  4. Claude Sonnet — qualification scoring (LinkedIn-aware)
  5. Claude Opus   — outreach drafting (opens with exec's own words)
  6. Google Sheets — Hot/Cold tab routing + persistence

Two pipeline tracks:
  DISCOVERY — Gemini + Exa find companies, Grok researches them
  ACCOUNT   — reads tracked accounts from Sheets, skips discovery

Usage:
  python main.py --query "sports broadcaster OTT launch 2025" --bu NAM
  python main.py --rotate --bu E&L
  python main.py --prospect "FuboTV" --prospect "Sling TV" --bu NAM
  python main.py --query "..." --dry-run --bu APAC
  python main.py --accounts --bu NAM
"""

from tools.claude_client import qualify_prospect, draft_outreach
from tools.exa import enrich_prospect_power_map
from tools.apollo import enrich_power_map, get_contacts_from_power_map
from tools.grok import run_research_waterfall
from core.sheets import SheetsClient
import time
from datetime import datetime, timezone
import argparse
import logging
import json
import sys
from typing import List

import config
from utils.helpers import setup_logging
from utils.usage_tracker import RunUsage

logger = logging.getLogger("ott_lead_gen.main")


# ---------------------------------------------------------------------------
# Single prospect processor
# ---------------------------------------------------------------------------

def process_prospect(
    prospect: dict,
    sheets: SheetsClient,
    query: str,
    run_id: str,
    dry_run: bool = False,
    usage: "RunUsage" = None,
    exa_rejected: str = "",
    gemini_reasoning: str = "",
    bu: str = "",
) -> dict:
    """
    Run the full enrichment + qualification + write pipeline for one prospect.

    Execution order:
      Apollo → Exa → Claude Sonnet → Claude Opus → Sheets
    """
    company = prospect.get("name", "unknown")
    domain = prospect.get("domain", "")
    if usage:
        usage.start_prospect(company)

    logger.info(f"--- Processing Prospect: {company} ({domain}) | BU={bu} ---")

    result = {
        "company":       company,
        "domain":        domain,
        "grok_score":    prospect.get("opportunity_score"),
        "refined_score": None,
        "verdict":       None,
        "exa_enriched":  False,
        "apollo_active": config.APOLLO_ENABLED,
        "rows_written":  0,
        "skipped":       False,
        "skip_reason":   "",
        "error":         None,
        "bu":            bu,
        "prospect":      prospect,
        "analyst":       {},
        "emails":        {},
    }

    # ------------------------------------------------------------------
    # Step 1 — Apollo
    # ------------------------------------------------------------------
    if config.APOLLO_ENABLED:
        logger.info(f"  Step 1: Apollo Validation/Discovery...")
        if not config.APOLLO_MASTER_API_KEY or not config.APOLLO_API_KEY:
            sheets.write_log(
                run_id=run_id, query=query, company=company, domain=domain,
                step="Apollo", status="SKIPPED",
                detail="One or both API keys missing",
            )
            logger.warning(
                "Apollo is ENABLED but one or both API keys are missing.")
        else:
            t0 = time.monotonic()
            try:
                prospect = enrich_power_map(prospect, usage_tracker=usage)
                result["prospect"] = prospect
                duration_ms = int((time.monotonic() - t0) * 1000)
                contacts_found = len(get_contacts_from_power_map(prospect))
                cur = usage._current
                sheets.write_log(
                    run_id=run_id, query=query, company=company, domain=domain,
                    step="Apollo", status="OK",
                    detail=f"{contacts_found} contact(s) found",
                    credits=cur.apollo_enrich_credits if cur else 0,
                    cost_usd=cur.apollo_enrich_credits * 0.49 if cur else 0,
                    duration_ms=duration_ms,
                )
                logger.info(f"  Apollo: power map enriched for '{company}'")
            except Exception as exc:
                duration_ms = int((time.monotonic() - t0) * 1000)
                sheets.write_log(
                    run_id=run_id, query=query, company=company, domain=domain,
                    step="Apollo", status="FAILED",
                    error=str(exc), duration_ms=duration_ms,
                )
                logger.warning(
                    f"  Apollo: enrichment failed for '{company}': {exc}")

    # ------------------------------------------------------------------
    # Step 2 — Exa LinkedIn intelligence
    # ------------------------------------------------------------------
    logger.info(f"  Step 2: Exa LinkedIn Intelligence...")
    t0 = time.monotonic()
    try:
        prospect = enrich_prospect_power_map(prospect, usage_tracker=usage)
        result["prospect"] = prospect
        pm = prospect.get("power_map", {})
        vis_li = pm.get("the_visionary", {}).get("linkedin_intel", {})
        ops_li = pm.get("the_operator", {}).get("linkedin_intel", {})
        if vis_li.get("linkedin_posts_found") or ops_li.get("linkedin_posts_found"):
            result["exa_enriched"] = "found"
            exa_detail = "Posts found"
        elif vis_li or ops_li:
            result["exa_enriched"] = "ran"
            exa_detail = "Ran — no posts found in last 90 days"
        else:
            result["exa_enriched"] = False
            exa_detail = "Skipped — no exec name or key not set"
        duration_ms = int((time.monotonic() - t0) * 1000)
        cur = usage._current
        exa_credits = cur.exa_exec_searches if cur else 0
        sheets.write_log(
            run_id=run_id, query=query, company=company, domain=domain,
            step="Exa",
            status="SKIPPED" if not (vis_li or ops_li) else "OK",
            detail=exa_detail,
            credits=exa_credits,
            cost_usd=exa_credits * 0.005,
            duration_ms=duration_ms,
        )
        if result["exa_enriched"] == "found":
            logger.info(f"  Exa: LinkedIn intel found for '{company}'")
        elif result["exa_enriched"] == "ran":
            logger.info(f"  Exa: ran for '{company}' but no posts found")
        else:
            logger.debug(f"  Exa: skipped for '{company}'")
    except Exception as exc:
        duration_ms = int((time.monotonic() - t0) * 1000)
        sheets.write_log(
            run_id=run_id, query=query, company=company, domain=domain,
            step="Exa", status="FAILED",
            error=str(exc), duration_ms=duration_ms,
        )
        logger.warning(f"  Exa: enrichment failed for '{company}': {exc}")

    # ------------------------------------------------------------------
    # Step 3 — Claude Sonnet qualification
    # ------------------------------------------------------------------
    logger.info(f"  Step 3: Analyst Qualification (Sonnet)...")
    clean_prospect = json.loads(json.dumps(prospect, default=lambda o: None))
    t0 = time.monotonic()
    try:
        analyst = qualify_prospect(clean_prospect, usage_tracker=usage)
        duration_ms = int((time.monotonic() - t0) * 1000)
        result["refined_score"] = analyst.get("refined_score")
        result["verdict"] = analyst.get("verdict")
        result["analyst"] = analyst
        score = result["refined_score"]
        override = False
        if score is not None:
            if score >= 70:
                enforced_verdict = "HOT"
            elif score >= 50:
                enforced_verdict = "WARM"
            else:
                enforced_verdict = "COLD"
            if enforced_verdict != result["verdict"]:
                logger.warning(
                    f"  Analyst verdict override: Claude said {result['verdict']} "
                    f"but score={score} → forcing {enforced_verdict}"
                )
                result["verdict"] = enforced_verdict
                analyst["verdict"] = enforced_verdict
                override = True
        cur = usage._current
        sheets.write_log(
            run_id=run_id, query=query, company=company, domain=domain,
            step="Sonnet", status="OK",
            detail=(
                f"score={result['refined_score']} verdict={result['verdict']}"
                + (" [OVERRIDE]" if override else "")
            ),
            tokens_in=cur.sonnet_input_tokens if cur else 0,
            tokens_out=cur.sonnet_output_tokens if cur else 0,
            cost_usd=(
                (cur.sonnet_input_tokens / 1e6 * 3) +
                (cur.sonnet_output_tokens / 1e6 * 15)
            ) if cur else 0,
            duration_ms=duration_ms,
        )

        # Write signals to persistent Signals tab
        signals = prospect.get("signals", [])
        if signals and not dry_run:
            sheets.write_signals(
                signals=signals,
                company=company,
                domain=domain,
                bu=bu,
                run_id=run_id,
                score=result["refined_score"] or 0,
                prospect_type=prospect.get("prospect_type", ""),
            )

    except Exception as exc:
        duration_ms = int((time.monotonic() - t0) * 1000)
        sheets.write_log(
            run_id=run_id, query=query, company=company, domain=domain,
            step="Sonnet", status="FAILED",
            error=str(exc), duration_ms=duration_ms,
        )
        logger.error(f"  Analyst failed for '{company}': {exc}")
        result["error"] = f"Analyst: {exc}"
        return result

    verdict = result["verdict"] or "COLD"
    is_cold = verdict == "COLD"

    if is_cold:
        logger.info(
            f"  ROUTING '{company}' -> Cold Leads tab "
            f"(score: {result['refined_score']}, "
            f"reason: {analyst.get('skip_reason', 'score < 50')})"
        )
    else:
        logger.info(
            f"  ROUTING '{company}' -> Leads tab "
            f"(score: {result['refined_score']}, verdict: {verdict})"
        )

    # ------------------------------------------------------------------
    # Step 4 — Claude Opus outreach
    # ------------------------------------------------------------------
    if is_cold:
        logger.info(f"  Step 4: Skipping Opus for COLD lead '{company}'")
        sheets.write_log(
            run_id=run_id, query=query, company=company, domain=domain,
            step="Opus", status="SKIPPED",
            detail="COLD lead — outreach not drafted",
        )
        emails = {
            "visionary_email": {
                "subject_line": f"{company} — archived",
                "body": "COLD lead — no outreach drafted. Re-qualify in 90 days.",
            },
            "operator_email": {"subject_line": "", "body": ""},
        }
    else:
        logger.info(f"  Step 4: Copywriter Personalization (Opus)...")
        t0 = time.monotonic()
        try:
            emails = draft_outreach(prospect, analyst, usage_tracker=usage)
            if not isinstance(emails, dict) or "visionary_email" not in emails:
                raise ValueError("Copywriter returned prose instead of JSON")
            duration_ms = int((time.monotonic() - t0) * 1000)
            cur = usage._current
            sheets.write_log(
                run_id=run_id, query=query, company=company, domain=domain,
                step="Opus", status="OK",
                detail=f"subj='{emails['visionary_email'].get('subject_line', '')[:60]}'",
                tokens_in=cur.opus_input_tokens if cur else 0,
                tokens_out=cur.opus_output_tokens if cur else 0,
                cost_usd=(
                    (cur.opus_input_tokens / 1e6 * 15) +
                    (cur.opus_output_tokens / 1e6 * 75)
                ) if cur else 0,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - t0) * 1000)
            sheets.write_log(
                run_id=run_id, query=query, company=company, domain=domain,
                step="Opus", status="FAILED",
                error=str(exc), duration_ms=duration_ms,
            )
            logger.error(f"  Copywriter failed for '{company}': {exc}")
            emails = {
                "visionary_email": {
                    "subject_line": "Strategizing for OTT",
                    "body": "AI draft failed — manual write required.",
                },
                "operator_email": {
                    "subject_line": "Technical Inquiry",
                    "body": "AI draft failed — manual write required.",
                },
            }
    result["emails"] = emails

    # ------------------------------------------------------------------
    # Step 5 — Extract Apollo contacts
    # ------------------------------------------------------------------
    contacts = []
    if config.APOLLO_ENABLED:
        contacts = get_contacts_from_power_map(prospect)
        if contacts:
            logger.info(
                f"  Apollo: {len(contacts)} contact(s) ready for Sheets columns")

    # ------------------------------------------------------------------
    # Step 6 — Write to Sheets
    # ------------------------------------------------------------------
    t0 = time.monotonic()
    try:
        primary_contact = contacts[0] if contacts else None
        written = sheets.append_lead(
            prospect, analyst, emails,
            contact=primary_contact,
            query=query,
            is_cold=is_cold,
            exa_rejected=exa_rejected,
            gemini_reasoning=gemini_reasoning,
            bu=bu,
        )
        if written:
            result["rows_written"] = 1
        duration_ms = int((time.monotonic() - t0) * 1000)
        sheets.write_log(
            run_id=run_id, query=query, company=company, domain=domain,
            step="Sheets",
            status="OK" if written else "SKIPPED",
            detail=(
                f"Written to {'Cold Leads' if is_cold else 'Leads'}"
                if written else "Duplicate — skipped"
            ),
            duration_ms=duration_ms,
        )
    except Exception as exc:
        duration_ms = int((time.monotonic() - t0) * 1000)
        sheets.write_log(
            run_id=run_id, query=query, company=company, domain=domain,
            step="Sheets", status="FAILED",
            error=str(exc), duration_ms=duration_ms,
        )
        logger.error(f"  Sheets write failed for '{company}': {exc}")
        result["error"] = f"Sheets: {exc}"

    if usage:
        usage.end_prospect()
    return result


# ---------------------------------------------------------------------------
# Discovery pipeline run
# ---------------------------------------------------------------------------

def run_pipeline(query: str, dry_run: bool = False, bu: str = "") -> List[dict]:
    """
    Run the full discovery pipeline for a single query.
    Gemini + Exa discover companies, Grok researches them.
    """
    logger.info(f"\n{'='*65}")
    logger.info(f"Pipeline: '{query}' | BU={bu}")
    logger.info(f"{'='*65}")
    logger.info(
        f"Modules active: "
        f"Apollo={'ON' if config.APOLLO_ENABLED else 'OFF'} | "
        f"Exa={'ON' if config.EXA_ENABLED else 'OFF'}"
    )

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    usage = RunUsage(query)
    sheets = SheetsClient()
    # sheets._connect()
    summary = []

    usage.start_prospect("_grok_research")

    # Stage 0 — Discovery
    logger.info("Stage 0: Company Discovery (Gemini + Exa)...")
    discovery = discover_companies(
        query,
        usage_tracker=usage,
        sheets=sheets,
        run_id=run_id,
    )

    rejected_companies = discovery.get("rejected", [])
    exa_rejected_str = ", ".join(
        r.get("name", "") for r in rejected_companies
    ) if rejected_companies else ""

    discovery_meta = {
        "discovery_ran":  discovery.get("discovery_ran", False),
        "gemini_ran":     discovery.get("gemini_ran", False),
        "all_found":      discovery.get("all_found", []),
        "selected":       discovery.get("selected", []),
        "rejected":       discovery.get("rejected", []),
        "search_strings": discovery.get("search_strings", []),
    }

    if discovery.get("discovery_ran") and discovery.get("selected"):
        company_names = [c.get("name", "")
                         for c in discovery["selected"] if c.get("name")]
        gemini_reasonings = {
            c.get("name", ""): c.get("reasoning", "")
            for c in discovery["selected"]
        }
        logger.info(
            f"Discovery: passing {len(company_names)} companies to Grok — "
            f"{', '.join(company_names)}"
        )
        use_prospect_mode = True
    else:
        logger.info("Discovery: degrading to standard Grok waterfall")
        company_names = []
        gemini_reasonings = {}
        use_prospect_mode = False

    bu_context = {
                    "NAM": "Prioritise companies headquartered in North America (US, Canada, Mexico).",
                    "E&L": "Prioritise companies headquartered in Europe or Latin America.",
                    "APAC": "Prioritise companies headquartered in Asia Pacific (including Australia and New Zealand).",
                }.get(bu, "")
    # Stage 1 — Grok
    t0 = time.monotonic()
    try:
        if use_prospect_mode and company_names:
            all_prospects = []
            for name in company_names:
                named_query = (
                    f"{name} — research this company thoroughly for OTT sales intelligence.\n\n"
                    f"ORIGINAL DISCOVERY CONTEXT: {query}\n\n"
                    f"HEADQUARTERS CONTEXT: {bu_context}\n\n"
                    f"Based on that context, research whichever is most relevant:\n"
                    f"- If they have an existing OTT platform: technology infrastructure, "
                    f"OEM strategy, SSAI/DRM, app store ratings, incumbent vendor, job postings\n"
                    f"- If they are pre-platform or mobile-only: content strategy, social "
                    f"audience size, funding history, current distribution platforms, "
                    f"CTV ambition signals, platform expansion announcements\n\n"
                    f"Return intelligence specifically about {name}, not similar companies. "
                    f"Classify this as TYPE_A (pain signal) or TYPE_B (growth catalyst) "
                    f"based on what you find."
                )
                
                contextualised_query = f"{query}\n\nHEADQUARTERS CONTEXT: {bu_context}" if bu_context else query
                grok_result = run_research_waterfall(
                    contextualised_query, usage_tracker=usage)
                all_prospects.extend(grok_result.get("prospects", []))
            prospects = all_prospects
            top_recommendation = ""
        else:
            grok_result = run_research_waterfall(query, usage_tracker=usage)
            prospects = grok_result.get("prospects", [])
            top_recommendation = grok_result.get("top_recommendation", "")

        duration_ms = int((time.monotonic() - t0) * 1000)
        cur = usage._prospects[0] if usage._prospects else None
        sheets.write_log(
            run_id=run_id, query=query, company="—", domain="—",
            step="Grok", status="OK",
            detail=(
                f"{len(prospects)} prospect(s) returned | "
                f"discovery={'YES' if use_prospect_mode else 'NO'} | bu={bu}"
            ),
            tokens_in=cur.grok_input_tokens if cur else 0,
            tokens_out=cur.grok_output_tokens if cur else 0,
            duration_ms=duration_ms,
        )
    except Exception as exc:
        duration_ms = int((time.monotonic() - t0) * 1000)
        sheets.write_log(
            run_id=run_id, query=query, company="—", domain="—",
            step="Grok", status="FAILED",
            error=str(exc), duration_ms=duration_ms,
        )
        usage.end_prospect()
        logger.error(f"Grok waterfall failed: {exc}")
        return [{"error": str(exc), "company": "", "domain": "",
                 "discovery_meta": discovery_meta}]

    usage.end_prospect()

    if not prospects:
        logger.warning("Grok returned no prospects. Try a broader query.")
        return [{"error": None, "company": "", "domain": "",
                 "discovery_meta": discovery_meta}]

    if top_recommendation:
        logger.info(f"\n★ TOP PICK: {str(top_recommendation)[:200]}\n")

    logger.info(
        f"Grok returned {len(prospects)} prospect(s) — enriching + qualifying now\n")

    for i, prospect in enumerate(prospects, 1):
        company = prospect.get("name", "?")
        logger.info(f"[{i}/{len(prospects)}] {company}")
        gemini_reasoning = gemini_reasonings.get(company, "")
        result = process_prospect(
            prospect, sheets, query, run_id,
            dry_run=dry_run, usage=usage,
            exa_rejected=exa_rejected_str,
            gemini_reasoning=gemini_reasoning,
            bu=bu,
        )
        result["discovery_meta"] = discovery_meta
        summary.append(result)

    usage.finish()
    usage.save()
    usage_summary = usage.summary()
    for r in summary:
        r["usage_summary"] = usage_summary
    return summary

# ---------------------------------------------------------------------------
# Stage 1 — Fast discovery sweep (names + evidence only, no deep research)
# ---------------------------------------------------------------------------

def run_discovery_sweep(
    brief: str,
    bu: str = "",
    run_id: str = "",
    usage: "RunUsage" = None,
    sheets: SheetsClient = None,
) -> dict:
    """
    Lightweight Grok pass using the discovery system prompt (not scout.py).
    Scans the web broadly for company names with one-line evidence each.
    Fast (~60-90s), cheap, no deep research.

    Returns:
        {
            "run_id":         str,
            "companies":      List[dict],
            "search_summary": str,
            "bu":             str,
            "brief":          str,
            "usage":          RunUsage,
            "sheets":         SheetsClient,
        }
    """
    from tools.grok import run_discovery_waterfall

    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    usage  = usage  or RunUsage(brief[:80])
    sheets = sheets or SheetsClient()

    logger.info(f"\n{'='*65}")
    logger.info(f"Discovery Sweep: BU={bu} | brief={brief[:80]}...")
    logger.info(f"{'='*65}")

    usage.start_prospect("_discovery_sweep")
    t0 = time.monotonic()
    companies      = []
    search_summary = ""

    try:
        result         = run_discovery_waterfall(brief, bu=bu, usage_tracker=usage)
        companies      = result.get("companies", [])
        search_summary = result.get("search_summary", "")
        duration_ms    = int((time.monotonic() - t0) * 1000)

        cur = usage._prospects[-1] if usage._prospects else None
        sheets.write_log(
            run_id=run_id, query=brief[:120], company="—", domain="—",
            step="Discovery Sweep", status="OK",
            detail=f"{len(companies)} companies found | bu={bu}",
            tokens_in=cur.grok_input_tokens if cur else 0,
            tokens_out=cur.grok_output_tokens if cur else 0,
            duration_ms=duration_ms,
        )
        logger.info(f"Discovery Sweep complete: {len(companies)} companies in {duration_ms}ms")

    except Exception as exc:
        duration_ms = int((time.monotonic() - t0) * 1000)
        sheets.write_log(
            run_id=run_id, query=brief[:120], company="—", domain="—",
            step="Discovery Sweep", status="FAILED",
            error=str(exc), duration_ms=duration_ms,
        )
        logger.error(f"Discovery Sweep failed: {exc}")

    usage.end_prospect()

    return {
        "run_id":         run_id,
        "companies":      companies,
        "search_summary": search_summary,
        "bu":             bu,
        "brief":          brief,
        "usage":          usage,
        "sheets":         sheets,
    }


# ---------------------------------------------------------------------------
# Stage 2 — Per-company deep research (one at a time, progress callback)
# ---------------------------------------------------------------------------

def run_grok_only(
    query: str,
    bu: str,
    selected_companies: list,
    run_id: str,
    usage: "RunUsage" = None,
    sheets: SheetsClient = None,
    on_company_start: callable = None,
    on_company_done: callable = None,
) -> List[dict]:
    """
    Run full scout.py deep research on each selected company, one at a time.
    Calls on_company_start(name, index, total) before each company starts.
    Calls on_company_done(name, prospect, index, total) when each completes.
    These callbacks allow the GUI to update progressively.

    Returns list of raw Grok prospect dicts with full scores.
    """
    logger.info(f"\n{'='*65}")
    logger.info(f"Deep Research: {len(selected_companies)} companies | BU={bu}")
    logger.info(f"{'='*65}")

    usage  = usage  or RunUsage(query)
    sheets = sheets or SheetsClient()

    bu_context = {
        "NAM":  "Prioritise companies headquartered in North America (US, Canada, Mexico).",
        "E&L":  "Prioritise companies headquartered in Europe or Latin America.",
        "APAC": "Prioritise companies headquartered in Asia Pacific (including Australia and New Zealand).",
    }.get(bu, "")

    all_prospects = []
    total = len(selected_companies)

    for idx, company in enumerate(selected_companies, 1):
        name = company.get("name", "")
        if not name:
            continue

        # Notify GUI this company is starting
        if on_company_start:
            on_company_start(name, idx, total)

        evidence = company.get("evidence", "")
        signal_type = company.get("signal_type", "")

        named_query = (
            f"{name} — deep OTT sales intelligence research.\n\n"
            f"DISCOVERY CONTEXT: {query}\n\n"
            f"KNOWN SIGNAL: {signal_type} — {evidence}\n\n"
            f"HEADQUARTERS CONTEXT: {bu_context}\n\n"
            f"Research this company thoroughly using the full intelligence waterfall. "
            f"The known signal above is your starting point — verify it and find additional signals. "
            f"Return intelligence specifically about {name}, not similar companies."
        )

        usage.start_prospect(name)
        t0 = time.monotonic()

        try:
            grok_result = run_research_waterfall(named_query, usage_tracker=usage)
            prospects   = grok_result.get("prospects", [])
            duration_ms = int((time.monotonic() - t0) * 1000)

            cur = usage._prospects[-1] if usage._prospects else None
            sheets.write_log(
                run_id=run_id, query=query, company=name, domain="",
                step="Deep Research", status="OK",
                detail=f"score={prospects[0].get('opportunity_score', '?') if prospects else '?'} | bu={bu}",
                tokens_in=cur.grok_input_tokens if cur else 0,
                tokens_out=cur.grok_output_tokens if cur else 0,
                duration_ms=duration_ms,
            )

            prospect = prospects[0] if prospects else {"name": name, "opportunity_score": 0}
            all_prospects.append(prospect)

            # Notify GUI this company is done
            if on_company_done:
                on_company_done(name, prospect, idx, total)

            logger.info(
                f"[{idx}/{total}] {name} — "
                f"score={prospect.get('opportunity_score', '?')} | "
                f"{duration_ms}ms"
            )

        except Exception as exc:
            duration_ms = int((time.monotonic() - t0) * 1000)
            sheets.write_log(
                run_id=run_id, query=query, company=name, domain="",
                step="Deep Research", status="FAILED",
                error=str(exc), duration_ms=duration_ms,
            )
            logger.error(f"  Deep research failed for '{name}': {exc}")
            stub = {"name": name, "opportunity_score": 0, "error": str(exc)}
            all_prospects.append(stub)
            if on_company_done:
                on_company_done(name, stub, idx, total)

        usage.end_prospect()

    return {
        "prospects": all_prospects,
        "usage":     usage,
        "sheets":    sheets,
    }



# ---------------------------------------------------------------------------
# Stages 2-6 — enrichment on user-approved subset of Grok prospects
# ---------------------------------------------------------------------------

def run_enrichment_from_selection(
    query: str,
    bu: str,
    all_prospects: list,
    enrichment_names: set,
    run_id: str,
    dry_run: bool = False,
    discovery: dict = None,
    usage: "RunUsage" = None,
    sheets: SheetsClient = None,
) -> List[dict]:
    """
    Run Apollo + Exa exec intel + Claude Sonnet + Claude Opus + Sheets
    on a user-selected subset of Grok prospects.

    Unselected prospects are written directly to Cold Leads with no enrichment.
    Selected prospects go through the full process_prospect() pipeline.

    Args:
        all_prospects:    All raw prospect dicts Grok returned
        enrichment_names: Set of company names the user selected for enrichment
    """
    logger.info(
        f"\n{'='*65}\n"
        f"Enrichment: {len(enrichment_names)} selected of {len(all_prospects)} total | BU={bu}\n"
        f"{'='*65}"
    )

    usage  = usage  or RunUsage(query)
    sheets = sheets or SheetsClient()
    summary = []

    discovery_meta = {
        "discovery_ran":  discovery.get("discovery_ran", False) if discovery else False,
        "gemini_ran":     discovery.get("gemini_ran", False) if discovery else False,
        "all_found":      discovery.get("all_found", []) if discovery else [],
        "selected":       discovery.get("selected", []) if discovery else [],
        "rejected":       discovery.get("rejected", []) if discovery else [],
        "search_strings": discovery.get("search_strings", []) if discovery else [],
    }

    exa_rejected_str = ", ".join(
        r.get("name", "") for r in (discovery.get("rejected", []) if discovery else [])
    )

    for i, prospect in enumerate(all_prospects, 1):
        company = prospect.get("name", "?")
        selected_for_enrichment = company in enrichment_names

        logger.info(
            f"[{i}/{len(all_prospects)}] {company} — "
            f"{'ENRICH' if selected_for_enrichment else 'ARCHIVE to Cold'}"
        )

        if selected_for_enrichment:
            result = process_prospect(
                prospect, sheets, query, run_id,
                dry_run=dry_run, usage=usage,
                exa_rejected=exa_rejected_str,
                gemini_reasoning="",
                bu=bu,
            )
        else:
            if usage:
                usage.start_prospect(company)

            domain = prospect.get("domain", "")
            stub_analyst = {
                "refined_score": prospect.get("opportunity_score", 0),
                "verdict": "COLD",
                "write_to_sheet": False,
                "skip_reason": "Not selected for enrichment by user",
                "top_entry_point": "",
                "score_delta_reasoning": "Archived by user at enrichment selection step",
                "copywriter_brief": "",
                "transition_gap_confirmed": "",
                "key_risk_if_no_action": "",
            }
            stub_emails = {
                "visionary_email": {
                    "subject_line": f"{company} — archived",
                    "body": "Not selected for enrichment — re-qualify in next run.",
                },
                "operator_email": {"subject_line": "", "body": ""},
            }

            result = {
                "company":       company,
                "domain":        domain,
                "grok_score":    prospect.get("opportunity_score"),
                "refined_score": prospect.get("opportunity_score"),
                "verdict":       "COLD",
                "exa_enriched":  False,
                "apollo_active": False,
                "rows_written":  0,
                "skipped":       False,
                "error":         None,
                "bu":            bu,
                "prospect":      prospect,
                "analyst":       stub_analyst,
                "emails":        stub_emails,
            }

            if not dry_run:
                t0 = time.monotonic()
                try:
                    written = sheets.append_lead(
                        prospect, stub_analyst, stub_emails,
                        contact=None,
                        query=query,
                        is_cold=True,
                        exa_rejected=exa_rejected_str,
                        gemini_reasoning="User archived at enrichment step",
                        bu=bu,
                    )
                    if written:
                        result["rows_written"] = 1
                    duration_ms = int((time.monotonic() - t0) * 1000)
                    sheets.write_log(
                        run_id=run_id, query=query,
                        company=company, domain=domain,
                        step="Sheets",
                        status="OK" if written else "SKIPPED",
                        detail="Archived to Cold Leads — not selected for enrichment",
                        duration_ms=duration_ms,
                    )
                except Exception as exc:
                    logger.error(f"  Sheets write failed for '{company}': {exc}")
                    result["error"] = f"Sheets: {exc}"

            if usage:
                usage.end_prospect()

        result["discovery_meta"] = discovery_meta
        summary.append(result)

    usage.finish()
    usage.save()
    usage_summary = usage.summary()
    for r in summary:
        r["usage_summary"] = usage_summary

    return summary


# ---------------------------------------------------------------------------
# CLI convenience wrapper — runs Grok then enriches all prospects unattended
# ---------------------------------------------------------------------------

def run_pipeline_from_selection(
    query: str,
    bu: str,
    selected_companies: list,
    run_id: str,
    dry_run: bool = False,
    discovery: dict = None,
) -> List[dict]:
    """
    Stages 1-6 — run Grok + enrichment + qualification + outreach + Sheets write
    for a user-selected list of companies.

    Args:
        query:              Original user query
        bu:                 Business unit
        selected_companies: List of dicts with 'name' and 'linkedin_url'
        run_id:             Run ID from run_discovery()
        dry_run:            Skip Sheets writes if True
        discovery:          Full discovery dict from run_discovery()
    """
    """
    CLI path: runs Grok then immediately enriches all prospects automatically
    using score-based routing (score >= 50 → enrich, below → archive to Cold).
    GUI uses run_grok_only() + run_enrichment_from_selection() instead so the
    user can review Grok scores before the expensive Apollo/Claude steps run.
    """
    usage  = RunUsage(query)
    sheets = SheetsClient()

    all_prospects = run_grok_only(
        query=query,
        bu=bu,
        selected_companies=selected_companies,
        run_id=run_id,
        usage=usage,
        sheets=sheets,
    )

    if not all_prospects:
        logger.warning("Grok returned no prospects.")
        return [{"error": None, "company": "", "domain": ""}]

    # Auto-select: enrich HOT/WARM (score >= 50), archive COLD
    enrichment_names = {
        p.get("name", "")
        for p in all_prospects
        if (p.get("opportunity_score") or 0) >= 50
    }

    logger.info(
        f"CLI auto-select: {len(enrichment_names)} of {len(all_prospects)} "
        f"prospects qualify for enrichment (score >= 50)"
    )

    return run_enrichment_from_selection(
        query=query,
        bu=bu,
        all_prospects=all_prospects,
        enrichment_names=enrichment_names,
        run_id=run_id,
        dry_run=dry_run,
        discovery=discovery,
        usage=usage,
        sheets=sheets,
    )
# ---------------------------------------------------------------------------
# Account intelligence pipeline run
# ---------------------------------------------------------------------------

def run_account_pipeline(
    bu: str,
    dry_run: bool = False,
    sheets_client: SheetsClient = None,
) -> List[dict]:
    """
    Run the full intelligence waterfall on tracked accounts for a given BU.
    Skips Gemini + Exa discovery — goes straight to Grok per named account.
    Updates Last Run timestamp on each account after processing.
    """
    sheets = sheets_client or SheetsClient()
    # sheets._connect()

    accounts = sheets.get_accounts(bu_filter=bu)
    if not accounts:
        logger.warning(f"Account pipeline: no accounts found for BU='{bu}'")
        return []

    logger.info(f"\n{'='*65}")
    logger.info(f"Account Pipeline: {len(accounts)} account(s) | BU={bu}")
    logger.info(f"{'='*65}")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    usage = RunUsage(f"[ACCOUNT] BU={bu}")
    all_results = []

    for i, account in enumerate(accounts, 1):
        name = account.get("Company", "")
        domain = account.get("Domain", "")
        if not name:
            continue

        logger.info(f"[{i}/{len(accounts)}] {name} ({domain})")

        bu_context = {
            "NAM": "This company is headquartered in North America.",
            "E&L": "This company is headquartered in Europe or Latin America.",
            "APAC": "This company is headquartered in Asia Pacific.",
        }.get(bu, "")
        # Build context-aware query for account track
        query = (
            f"{name} — research this company thoroughly for OTT sales intelligence.\n\n"
            f"HEADQUARTERS CONTEXT: {bu_context}\n\n"
            f"Research whichever is most relevant:\n"
            f"- If they have an existing OTT platform: technology infrastructure, "
            f"OEM strategy, SSAI/DRM, app store ratings, incumbent vendor, job postings\n"
            f"- If they are pre-platform or mobile-only: content strategy, social "
            f"audience size, funding history, current distribution platforms, "
            f"CTV ambition signals, platform expansion announcements\n\n"
            f"Return intelligence specifically about {name}, not similar companies. "
            f"Classify this as TYPE_A (pain signal) or TYPE_B (growth catalyst)."
        )

        usage.start_prospect("_grok_research")
        t0 = time.monotonic()
        try:
            grok_result = run_research_waterfall(query, usage_tracker=usage)
            prospects = grok_result.get("prospects", [])
            duration_ms = int((time.monotonic() - t0) * 1000)
            cur = usage._prospects[-1] if usage._prospects else None
            sheets.write_log(
                run_id=run_id, query=query[:80], company=name, domain=domain,
                step="Grok", status="OK",
                detail=f"{len(prospects)} prospect(s) returned | track=ACCOUNT | bu={bu}",
                tokens_in=cur.grok_input_tokens if cur else 0,
                tokens_out=cur.grok_output_tokens if cur else 0,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - t0) * 1000)
            sheets.write_log(
                run_id=run_id, query=query[:80], company=name, domain=domain,
                step="Grok", status="FAILED",
                error=str(exc), duration_ms=duration_ms,
            )
            usage.end_prospect()
            logger.error(f"Grok failed for '{name}': {exc}")
            all_results.append({
                "company": name, "domain": domain, "error": str(exc),
                "bu": bu, "track": "account",
            })
            continue

        usage.end_prospect()

        for prospect in prospects:
            result = process_prospect(
                prospect, sheets, query, run_id,
                dry_run=dry_run, usage=usage,
                bu=bu,
            )
            result["track"] = "account"
            all_results.append(result)

        # Update last run timestamp on the account
        if not dry_run:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            sheets.update_account_last_run(domain, ts)

    usage.finish()
    usage.save()
    usage_summary = usage.summary()
    for r in all_results:
        r["usage_summary"] = usage_summary

    return all_results


# ---------------------------------------------------------------------------
# Legacy prospect mode (CLI only)
# ---------------------------------------------------------------------------

def run_prospect_mode(
    company_names: List[str],
    dry_run: bool = False,
    bu: str = "",
) -> List[dict]:
    all_results = []
    for name in company_names:
        query = (
            f"{name} OTT streaming platform 2024 2025 — research their technology "
            f"infrastructure, OEM platform strategy, SSAI/DRM implementation, "
            f"recent acquisitions, sports rights deals, app store ratings, "
            f"engineering job postings, and incumbent vendor. "
            f"Return intelligence specifically about {name}, not similar companies."
        )
        results = run_pipeline(query, dry_run=dry_run, bu=bu)
        all_results.extend(results)
    return all_results


# ---------------------------------------------------------------------------
# Run report
# ---------------------------------------------------------------------------

def print_report(summary: List[dict]) -> None:
    if not summary:
        return
    logger.info(f"\n{'='*80}")
    logger.info("RUN COMPLETE")
    logger.info(f"{'='*80}")
    logger.info(
        f"{'Company':<30} {'Grok':>5} {'Score':>6} {'Verdict':>7} "
        f"{'Exa':>5} {'Written':>7} {'BU':>5} {'Status':>7}"
    )
    logger.info(f"{'-'*80}")
    total_written = 0
    for r in summary:
        if r.get("error") and not r.get("company"):
            logger.info(f"  Pipeline error: {r['error']}")
            continue
        status = "SKIP" if r.get("skipped") else (
            "ERR" if r.get("error") else "OK")
        exa = "YES" if r.get("exa_enriched") else "no"
        written = r.get("rows_written", 0)
        total_written += written
        logger.info(
            f"{r.get('company', '?')[:30]:<30} "
            f"{str(r.get('grok_score', '?')):>5} "
            f"{str(r.get('refined_score', '?')):>6} "
            f"{str(r.get('verdict', '?')):>7} "
            f"{exa:>5} {written:>7} "
            f"{r.get('bu', ''):>5} "
            f"{status:>7}"
        )
    logger.info(f"{'-'*80}")
    logger.info(f"Total rows written: {total_written}")
    logger.info(f"{'='*80}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="OTT Lead Gen — Frontier Edition")

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--query", "-q", type=str)
    mode.add_argument("--rotate", "-r", action="store_true")
    mode.add_argument("--prospect", "-p", type=str,
                      action="append", dest="prospects")
    mode.add_argument("--accounts", "-a", action="store_true",
                      help="Run account intelligence pipeline for the specified BU")

    parser.add_argument("--bu", type=str, default=config.BU_DEFAULT,
                        choices=config.BU_OPTIONS,
                        help=f"Business unit filter (default: {config.BU_DEFAULT})")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--debug", action="store_true", default=False)

    args = parser.parse_args()
    setup_logging(level=logging.DEBUG if args.debug else logging.INFO)

    if args.dry_run:
        logger.info(f"[DRY RUN — no Sheets writes] BU={args.bu}")

    missing = []
    if not config.XAI_API_KEY:
        missing.append("XAI_API_KEY")
    if not config.ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if not config.GOOGLE_SERVICE_ACCOUNT_JSON and not args.dry_run:
        missing.append("GOOGLE_SERVICE_ACCOUNT_JSON")
    if missing:
        logger.error(f"Missing required env vars: {', '.join(missing)}")
        sys.exit(1)

    all_results = []

    if args.query:
        all_results = run_pipeline(
            args.query, dry_run=args.dry_run, bu=args.bu)

    elif args.rotate:
        for i, query in enumerate(config.OTT_SIGNAL_QUERIES, 1):
            logger.info(
                f"\n--- Query {i}/{len(config.OTT_SIGNAL_QUERIES)} ---")
            all_results.extend(run_pipeline(
                query, dry_run=args.dry_run, bu=args.bu))

    elif args.prospects:
        all_results = run_prospect_mode(
            args.prospects, dry_run=args.dry_run, bu=args.bu)

    elif args.accounts:
        all_results = run_account_pipeline(bu=args.bu, dry_run=args.dry_run)

    print_report(all_results)


if __name__ == "__main__":
    main()