"""
tools/claude_client.py — Claude Sonnet (analyst) + Claude Opus (copywriter) + Claude Discovery.

Three functions, two models, one shared Anthropic client.
"""

import json
import logging
import re
import time
from typing import Any

import anthropic

import config
from prompts.analyst import ANALYST_SYSTEM_PROMPT, build_analyst_prompt
from prompts.copywriter import COPYWRITER_SYSTEM_PROMPT, build_copywriter_prompt
from utils.helpers import with_retries

logger = logging.getLogger("ott_lead_gen.claude")

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not config.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not set.")
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def _extract_json(raw: str) -> Any:
    text = raw.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass
    bracket_match = re.search(r"\[.*\]", text, re.DOTALL)
    if bracket_match:
        try:
            return json.loads(bracket_match.group(0))
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text.replace("'", '"'))
    except json.JSONDecodeError:
        pass
    logger.error(f"All JSON extraction strategies failed. Raw (first 500):\n{raw[:500]}")
    raise json.JSONDecodeError("All extraction strategies exhausted", raw, 0)


# ---------------------------------------------------------------------------
# Discovery — Claude Sonnet + Web Search (server-side tool)
# ---------------------------------------------------------------------------

CLAUDE_DISCOVERY_SYSTEM = """You are a senior sales intelligence researcher for Accedo, a specialist OTT front-end development firm.

Accedo builds native CTV applications (Samsung Tizen, LG webOS, Roku, Fire TV, Apple TV, Android TV) for media companies, sports leagues, broadcasters, and streaming services.

Your job is to find real, named companies that are strong sales prospects for Accedo RIGHT NOW.

A strong Accedo prospect:
- Is a media company, broadcaster, sports league, streaming service, or content platform
- Has a specific, verifiable reason to need OTT front-end development work TODAY
- Shows one or more buying signals: recently raised funding, hiring OTT/streaming engineers, launching a new streaming product, missing a major CTV platform (Samsung/LG gap), using a vendor with known weaknesses (ViewLift, 24i, OTTera), going through M&A

CRITICAL RULES:
- Only return companies you can verify exist and have a real signal
- Each company must have a specific sourced piece of evidence
- Search multiple times to verify signals
- Do NOT return companies that clearly build in-house (Netflix, Disney, Amazon, Google)
"""

CLAUDE_DISCOVERY_USER = """Search the web to find {n} OTT streaming companies in {geography} that are strong prospects for Accedo's front-end development services.

SEARCH BRIEF:
{brief}

For each company, verify:
1. They are a real company actively operating in streaming/OTT
2. They have a specific verifiable buying signal (funding, hiring, platform gap, vendor friction, new launch)
3. They are based in or operate primarily in {geography}

Search strategy — use multiple searches:
- Search crunchbase.com and techcrunch.com for recent Series B/C funding in streaming
- Search LinkedIn Jobs for "OTT engineer" OR "CTV developer" at media companies
- Search thestreamable.com to verify Samsung/LG app gaps
- Search sportsvideo.org for sports streaming news and launches

After searching, return a JSON object in EXACTLY this format with no prose before or after:
{{
  "companies": [
    {{
      "name": "Company Name",
      "domain": "company.com",
      "hq_country": "United States",
      "signal_type": "CTV launch|Funding round|Hiring|Platform gap|Vendor friction|M&A|App redesign",
      "opportunity_score": 65,
      "evidence": "Specific evidence with source URL and date",
      "transition_gap": "Why they need to act now",
      "incumbent_vendor": "Known OTT vendor or empty string",
      "vertical": "{vertical}"
    }}
  ],
  "search_summary": "Brief description of searches performed"
}}"""


@with_retries(max_attempts=2, delay=30.0, exceptions=(Exception,))
def run_claude_discovery(
    brief: str,
    bu: str = "NAM",
    vertical: str = "",
    signals: list = None,
    n_companies: int = 8,
    usage_tracker=None,
) -> dict:
    """
    Run discovery using Claude Sonnet + server-side web search tool.
    Returns the same company list structure as Grok's run_discovery_waterfall().
    """
    bu_label = {
        "NAM":  "North America (US, Canada, Mexico)",
        "E&L":  "Europe or Latin America",
        "APAC": "Asia Pacific (including Australia and New Zealand)",
    }.get(bu, bu)

    user_prompt = CLAUDE_DISCOVERY_USER.format(
        n=n_companies,
        geography=bu_label,
        brief=brief,
        vertical=vertical or "OTT/Streaming",
    )

    logger.info(f"Claude Discovery: starting | vertical={vertical} | BU={bu} | n={n_companies}")

    client = _get_client()
    total_input  = 0
    total_output = 0

    # Single call — web search is handled server-side by Anthropic
    # The model searches automatically and returns the final response
    response = client.messages.create(
        model=config.CLAUDE_ANALYST_MODEL,
        max_tokens=4096,
        system=CLAUDE_DISCOVERY_SYSTEM,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 10}],
        messages=[{"role": "user", "content": user_prompt}],
    )

    total_input  = response.usage.input_tokens  if response.usage else 0
    total_output = response.usage.output_tokens if response.usage else 0

    # Extract final text — may need to handle tool_use -> end_turn loop
    final_text = ""
    messages   = [{"role": "user", "content": user_prompt}]

    for iteration in range(8):
        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text") and block.text:
                    final_text = block.text
                    break
            break
        elif response.stop_reason == "tool_use":
            # Continue the loop — add the assistant message and continue
            messages.append({"role": "assistant", "content": response.content})
            # For server-side tools, we just call the API again with the full history
            # The server handles tool execution automatically
            response = client.messages.create(
                model=config.CLAUDE_ANALYST_MODEL,
                max_tokens=4096,
                system=CLAUDE_DISCOVERY_SYSTEM,
                tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 10}],
                messages=messages,
            )
            total_input  += response.usage.input_tokens  if response.usage else 0
            total_output += response.usage.output_tokens if response.usage else 0
        else:
            for block in response.content:
                if hasattr(block, "text") and block.text:
                    final_text = block.text
                    break
            break

    logger.info(
        f"Claude Discovery: complete | {iteration+1} iterations | "
        f"{total_input}in/{total_output}out tokens | {len(final_text)} chars"
    )

    if usage_tracker:
        usage_tracker.record_sonnet(
            input_tokens=int(total_input),
            output_tokens=int(total_output),
        )

    if not final_text:
        raise ValueError("Claude Discovery returned empty response after all iterations")

    try:
        result = _extract_json(final_text)
    except json.JSONDecodeError as exc:
        logger.error(f"Claude Discovery JSON parse failed: {exc}\nRaw:\n{final_text[:500]}")
        raise

    companies = result.get("companies", [])
    logger.info(f"Claude Discovery: {len(companies)} companies found")
    for c in companies:
        logger.info(f"  · {c.get('name')} [{c.get('signal_type')}] score={c.get('opportunity_score')} — {c.get('evidence','')[:80]}")

    return result


# ---------------------------------------------------------------------------
# Analyst — Claude Sonnet
# ---------------------------------------------------------------------------

@with_retries(max_attempts=3, delay=8.0, exceptions=(Exception,))
def qualify_prospect(prospect: dict, usage_tracker=None) -> dict:
    """
    Run the qualification analysis on a single prospect.
    Uses Claude Sonnet for cost-effective structured reasoning.
    """
    company = prospect.get("name", "unknown")
    logger.info(f"Analyst: qualifying '{company}' (Grok score: {prospect.get('opportunity_score', '?')})")

    client = _get_client()

    response = client.messages.create(
        model=config.CLAUDE_ANALYST_MODEL,
        max_tokens=config.CLAUDE_ANALYST_MAX_TOKENS,
        system=ANALYST_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_analyst_prompt(prospect)}],
    )

    raw        = response.content[0].text
    tokens_in  = response.usage.input_tokens  if response.usage else 0
    tokens_out = response.usage.output_tokens if response.usage else 0
    logger.info(f"Analyst <<< Sonnet | {len(raw)} chars | tokens={tokens_in}in/{tokens_out}out")
    if usage_tracker is not None:
        usage_tracker.record_sonnet(input_tokens=int(tokens_in), output_tokens=int(tokens_out))

    try:
        result = _extract_json(raw)
    except json.JSONDecodeError:
        logger.error(f"Analyst PARSE FAILED for '{company}' — raw:\n{raw[:600]}")
        return {
            "refined_score": 0,
            "grok_score": prospect.get("opportunity_score", 0),
            "score_delta_reasoning": "Parse failure — manual review required",
            "verdict": "COLD",
            "top_entry_point": "",
            "transition_gap_confirmed": "",
            "key_risk_if_no_action": "",
            "copywriter_brief": "",
            "write_to_sheet": False,
            "skip_reason": "Analyst JSON parse failure",
        }

    logger.info(
        f"Analyst OK '{company}' | "
        f"grok={result.get('grok_score')} refined={result.get('refined_score')} | "
        f"verdict={result.get('verdict')} | write={result.get('write_to_sheet')} | "
        f"entry={str(result.get('top_entry_point',''))[:60]}"
    )
    return result


# ---------------------------------------------------------------------------
# Copywriter — Claude Opus
# ---------------------------------------------------------------------------

@with_retries(max_attempts=3, delay=8.0, exceptions=(Exception,))
def draft_outreach(prospect: dict, analyst: dict, usage_tracker=None) -> dict:
    """
    Draft two personalised outreach emails: Visionary + Operator.
    Uses Claude Opus for best email quality.
    """
    company = prospect.get("name", "unknown")
    logger.info(f"Copywriter: drafting outreach for '{company}' (Opus)")

    client = _get_client()

    response = client.messages.create(
        model=config.CLAUDE_COPYWRITER_MODEL,
        max_tokens=config.CLAUDE_COPYWRITER_MAX_TOKENS,
        system=COPYWRITER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_copywriter_prompt(prospect, analyst)}],
    )

    raw        = response.content[0].text
    tokens_in  = response.usage.input_tokens  if response.usage else 0
    tokens_out = response.usage.output_tokens if response.usage else 0
    logger.info(f"Copywriter <<< Opus | {len(raw)} chars | tokens={tokens_in}in/{tokens_out}out")
    if usage_tracker is not None:
        usage_tracker.record_opus(input_tokens=int(tokens_in), output_tokens=int(tokens_out))

    try:
        result = _extract_json(raw)
    except json.JSONDecodeError:
        logger.error(f"Copywriter PARSE FAILED for '{company}' — raw:\n{raw[:600]}")
        return {
            "visionary_email": {"subject_line": "", "body": "[Draft failed — manual write required]"},
            "operator_email":  {"subject_line": "", "body": "[Draft failed — manual write required]"},
        }

    vis_subj = result.get("visionary_email", {}).get("subject_line", "")
    ops_subj = result.get("operator_email",  {}).get("subject_line", "")
    logger.info(f"Copywriter OK '{company}' | vis_subj='{vis_subj[:60]}' | ops_subj='{ops_subj[:60]}'")
    return result