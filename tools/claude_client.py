"""
tools/claude_client.py — Claude Sonnet (analyst) + Claude Opus (copywriter).

Two separate functions, two separate models, one shared Anthropic client.

The JSON parser uses a multi-strategy approach to handle the range of
output formats frontier models can produce — including partial JSON,
extra commentary, and nested code fences.
"""

import json
import logging
import re
from typing import Any

import anthropic

import config
from prompts.analyst import ANALYST_SYSTEM_PROMPT, build_analyst_prompt
from prompts.copywriter import COPYWRITER_SYSTEM_PROMPT, build_copywriter_prompt
from utils.helpers import with_retries

logger = logging.getLogger("ott_lead_gen.claude")

# Lazily initialised — avoids import-time crash if key is not yet set
_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not config.ANTHROPIC_API_KEY:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. Export it: export ANTHROPIC_API_KEY='sk-ant-...'"
            )
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


# ---------------------------------------------------------------------------
# Hardened JSON extractor
# ---------------------------------------------------------------------------

def _extract_json(raw: str) -> Any:
    """
    Multi-strategy JSON extractor. Handles the following Claude output patterns:
      1. Clean JSON (ideal case)
      2. JSON wrapped in ```json ... ``` fences
      3. JSON embedded in prose ("Here is the assessment: {...}")
      4. Partial commentary before/after the JSON object
      5. Single-quoted JSON (non-standard but occasionally produced)

    Raises json.JSONDecodeError only after all strategies are exhausted.
    """
    text = raw.strip()

    # Strategy 1: direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 2: strip ```json ... ``` fences
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Strategy 3: extract outermost { ... } object
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    # Strategy 4: extract outermost [ ... ] array
    bracket_match = re.search(r"\[.*\]", text, re.DOTALL)
    if bracket_match:
        try:
            return json.loads(bracket_match.group(0))
        except json.JSONDecodeError:
            pass

    # Strategy 5: replace single quotes (non-standard JSON from some models)
    try:
        return json.loads(text.replace("'", '"'))
    except json.JSONDecodeError:
        pass

    logger.error(f"All JSON extraction strategies failed. Raw (first 500):\n{raw[:500]}")
    raise json.JSONDecodeError("All extraction strategies exhausted", raw, 0)


# ---------------------------------------------------------------------------
# Analyst — Claude Sonnet
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Discovery — Claude Sonnet + Web Search
# ---------------------------------------------------------------------------

CLAUDE_DISCOVERY_SYSTEM = """You are a senior sales intelligence researcher for Accedo, a specialist OTT front-end development firm.

Accedo builds native CTV applications (Samsung Tizen, LG webOS, Roku, Fire TV, Apple TV, Android TV) and streaming platforms for media companies, sports leagues, broadcasters, and streaming services.

Your job is to find real, named companies that are strong sales prospects for Accedo right now.

A strong Accedo prospect:
- Is a media company, broadcaster, sports league, streaming service, or content platform
- Has a specific, verifiable reason to need OTT front-end development work TODAY (not hypothetically)
- Shows one or more of these buying signals: recently raised funding, hiring OTT/streaming engineers, launching a new streaming product, missing a major CTV platform (Samsung/LG gap), using a vendor with known weaknesses (ViewLift, 24i, OTTera), going through M&A, launching a new sports league or season

CRITICAL RULES:
- Only return companies you can verify exist and have a real signal — no hallucinations
- Each company must have a specific, sourced piece of evidence for why they are a prospect NOW
- Search thoroughly — use multiple searches to verify signals
- Do NOT return companies that clearly build everything in-house (Netflix, Disney, Amazon)
- Do NOT return companies already on major CTV platforms with no obvious gap
"""

CLAUDE_DISCOVERY_USER = """Search the web to find {n} OTT streaming companies in {geography} that are strong prospects for Accedo's front-end development services.

SEARCH BRIEF:
{brief}

For each company you find, verify:
1. They are a real company actively operating in streaming/OTT
2. They have a specific, verifiable buying signal (funding, hiring, platform gap, vendor friction, new launch)
3. They are headquartered in or operate primarily in {geography}

Search strategy:
- Search for companies matching the vertical and signals in the brief
- Use thestreamable.com, crunchbase.com, sportsvideo.org, techcrunch.com, and LinkedIn Jobs to verify signals
- Check if they are missing Samsung or LG apps (search "[company name] Samsung TV" or check thestreamable.com)
- Check for recent funding rounds (crunchbase, techcrunch)
- Check for OTT/streaming job postings (LinkedIn, Indeed)

Return a JSON object in exactly this format:
{{
  "companies": [
    {{
      "name": "Company Name",
      "domain": "company.com",
      "hq_country": "United States",
      "signal_type": "one of: CTV launch | Funding round | Hiring | Platform gap | Vendor friction | M&A | App redesign",
      "opportunity_score": 65,
      "evidence": "Specific verifiable evidence — include source URL and date",
      "transition_gap": "Why they need to act now — deadline or window",
      "incumbent_vendor": "Known OTT vendor or empty string",
      "vertical": "{vertical}"
    }}
  ],
  "search_summary": "Brief description of what you searched and found"
}}

Find exactly {n} companies. Only return companies you have verified evidence for."""


@with_retries(max_attempts=2, delay=10.0, exceptions=(Exception,))
def run_claude_discovery(
    brief: str,
    bu: str = "NAM",
    vertical: str = "",
    signals: list = None,
    n_companies: int = 8,
    usage_tracker=None,
) -> dict:
    """
    Run discovery using Claude Sonnet + web search tool.
    Returns the same company list structure as Grok's run_discovery_waterfall().

    This is the alternative to Grok discovery — produces higher quality results
    by leveraging Claude's reasoning with iterative web search.

    Args:
        brief:    Gemini-enriched brief describing target companies and signals
        bu:       Business unit geography (NAM, E&L, APAC)
        vertical: Single vertical name (e.g. "Sports", "Faith")
        signals:  List of selected signal names
        n_companies: Target number of companies to find (default 8)
        usage_tracker: RunUsage instance for cost tracking
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

    # Agentic loop — Claude may search multiple times before returning final JSON
    messages = [{"role": "user", "content": user_prompt}]
    final_text = ""
    total_input  = 0
    total_output = 0
    max_iterations = 10

    for iteration in range(max_iterations):
        response = client.messages.create(
            model=config.CLAUDE_ANALYST_MODEL,
            max_tokens=4096,
            system=CLAUDE_DISCOVERY_SYSTEM,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 15}],
            messages=messages,
        )

        total_input  += response.usage.input_tokens  if response.usage else 0
        total_output += response.usage.output_tokens if response.usage else 0

        # Check stop reason
        if response.stop_reason == "end_turn":
            # Extract text from response
            for block in response.content:
                if hasattr(block, "text"):
                    final_text = block.text
                    break
            break
        elif response.stop_reason == "tool_use":
            # Claude wants to search — add assistant turn and tool results
            messages.append({"role": "assistant", "content": response.content})

            # Build tool results for all tool_use blocks
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    logger.info(f"Claude Discovery: searching — {str(getattr(block, 'input', {}))[:80]}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "",  # Anthropic handles web search results server-side
                    })

            if tool_results:
                messages.append({"role": "user", "content": tool_results})
        else:
            # Unexpected stop reason — try to extract any text
            for block in response.content:
                if hasattr(block, "text"):
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
        raise ValueError("Claude Discovery returned empty response")

    # Parse JSON
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

    """
    Run the qualification analysis on a single Grok prospect.

    Uses Claude Sonnet for cost-effective structured reasoning.
    Produces a refined score, verdict (HOT/WARM/COLD), and copywriter brief.

    Args:
        prospect: Single prospect dict from Grok's Phase 3 output.

    Returns:
        Analyst assessment dict. Always returns — defaults to COLD on failure.
    """
    company = prospect.get("name", "unknown")
    logger.info(f"Analyst: qualifying '{company}' (Grok score: {prospect.get('opportunity_score', '?')})")

    client = _get_client()

    response = client.messages.create(
        model=config.CLAUDE_ANALYST_MODEL,
        max_tokens=config.CLAUDE_ANALYST_MAX_TOKENS,
        system=ANALYST_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": build_analyst_prompt(prospect)}
        ],
    )

    raw = response.content[0].text
    tokens_in  = response.usage.input_tokens  if response.usage else 0
    tokens_out = response.usage.output_tokens if response.usage else 0
    logger.info(f"Analyst <<< Sonnet | {len(raw)} chars | tokens={tokens_in}in/{tokens_out}out")
    if usage_tracker is not None:
        usage_tracker.record_sonnet(input_tokens=int(tokens_in), output_tokens=int(tokens_out))
    logger.debug(f"Analyst raw response:\n{raw[:1200]}")

    try:
        result = _extract_json(raw)
    except json.JSONDecodeError:
        logger.error(
            f"Analyst PARSE FAILED for '{company}' — "
            f"Sonnet returned this instead of JSON:\n{raw[:600]}"
        )
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
    logger.debug(f"Analyst full JSON:\n{json.dumps(result, indent=2)[:1500]}")
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
        messages=[
            {"role": "user", "content": build_analyst_prompt(prospect)}
        ],
    )

    raw = response.content[0].text
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

    Uses Claude Opus — this is the output the Sales Director reads and sends.
    The quality delta between Opus and Sonnet is most visible in sales copy.

    Args:
        prospect: Full Grok prospect dict.
        analyst:  Assessment from qualify_prospect().

    Returns:
        Dict with "visionary_email" and "operator_email", each containing
        "subject_line" and "body". Returns empty strings on parse failure.
    """
    company = prospect.get("name", "unknown")
    logger.info(f"Copywriter: drafting outreach for '{company}' (Opus)")

    client = _get_client()

    response = client.messages.create(
        model=config.CLAUDE_COPYWRITER_MODEL,
        max_tokens=config.CLAUDE_COPYWRITER_MAX_TOKENS,
        system=COPYWRITER_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": build_copywriter_prompt(prospect, analyst)}
        ],
    )

    raw = response.content[0].text
    tokens_in  = response.usage.input_tokens  if response.usage else 0
    tokens_out = response.usage.output_tokens if response.usage else 0
    logger.info(f"Copywriter <<< Opus | {len(raw)} chars | tokens={tokens_in}in/{tokens_out}out")
    if usage_tracker is not None:
        usage_tracker.record_opus(input_tokens=int(tokens_in), output_tokens=int(tokens_out))
    logger.debug(f"Copywriter raw response:\n{raw[:1200]}")

    try:
        result = _extract_json(raw)
    except json.JSONDecodeError:
        logger.error(
            f"Copywriter PARSE FAILED for '{company}' — "
            f"Opus returned this instead of JSON:\n{raw[:600]}"
        )
        return {
            "visionary_email": {"subject_line": "", "body": "[Draft failed — manual write required]"},
            "operator_email":  {"subject_line": "", "body": "[Draft failed — manual write required]"},
        }

    vis_subj = result.get("visionary_email", {}).get("subject_line", "")
    ops_subj = result.get("operator_email",  {}).get("subject_line", "")
    logger.info(
        f"Copywriter OK '{company}' | "
        f"vis_subj='{vis_subj[:60]}' | ops_subj='{ops_subj[:60]}'"
    )
    return result