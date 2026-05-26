"""
tools/openai_client.py — OpenAI GPT-4o discovery with web search.

Uses GPT-4o with the responses API and web_search_preview tool.
Returns the same company list structure as Grok and Claude discovery
so nothing else in the pipeline needs to change.
"""

import json
import logging
import re
from typing import Any

from openai import OpenAI

import config
from utils.helpers import with_retries

logger = logging.getLogger("ott_lead_gen.openai")

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        import os
        try:
            import streamlit as st
            api_key = st.secrets.get("OPENAI_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
        except Exception:
            api_key = os.environ.get("OPENAI_API_KEY", "")
        
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set.")
        _client = OpenAI(api_key=api_key)
    return _client


def _extract_json(raw: str) -> Any:
    text = raw.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        try:
            return json.loads(brace.group(0))
        except json.JSONDecodeError:
            pass
    raise json.JSONDecodeError("JSON extraction failed", raw, 0)


OPENAI_DISCOVERY_SYSTEM = """You are a senior sales intelligence researcher for Accedo, a specialist OTT front-end development firm.

Accedo builds native CTV applications (Samsung Tizen, LG webOS, Roku, Fire TV, Apple TV, Android TV) for media companies, sports leagues, broadcasters, and streaming services.

Your job: find real, named companies that are strong sales prospects for Accedo RIGHT NOW.

A strong Accedo prospect:
- Is a media company, broadcaster, sports league, streaming service, or content platform
- Has a specific, verifiable reason to need OTT front-end development work TODAY
- Shows one or more buying signals: recently raised funding, hiring OTT/streaming engineers, launching a new streaming product, missing Samsung/LG CTV app, using a weak vendor (ViewLift, 24i, OTTera), going through M&A

RULES:
- Only return companies with verified, sourced evidence
- Do NOT return companies that build in-house (Netflix, Disney, Amazon, Google)
- Search thoroughly — verify Samsung/LG gaps, funding, and hiring signals
"""

OPENAI_DISCOVERY_USER = """Search the web to find {n} OTT streaming companies in {geography} that are strong prospects for Accedo.

SEARCH BRIEF:
{brief}

Search strategy:
- crunchbase.com / techcrunch.com for recent Series B/C funding in streaming
- LinkedIn Jobs for "OTT engineer" OR "CTV developer" at media companies  
- thestreamable.com to verify Samsung/LG app gaps
- sportsvideo.org for sports streaming launches and news

Return ONLY a JSON object — no prose before or after:
{{
  "companies": [
    {{
      "name": "Company Name",
      "domain": "company.com",
      "hq_country": "United States",
      "signal_type": "CTV launch|Funding round|Hiring|Platform gap|Vendor friction|M&A|App redesign",
      "opportunity_score": 65,
      "evidence": "Specific evidence with source URL and date",
      "source_url": "https://source.com/article",
      "transition_gap": "Why they need to act now",
      "incumbent_vendor": "Known OTT vendor or empty string",
      "vertical": "{vertical}"
    }}
  ],
  "search_summary": "2-3 sentences on what you searched and what patterns emerged"
}}"""


@with_retries(max_attempts=2, delay=15.0, exceptions=(Exception,))
def run_openai_discovery(
    brief: str,
    bu: str = "NAM",
    vertical: str = "",
    signals: list = None,
    n_companies: int = 8,
    usage_tracker=None,
) -> dict:
    """
    Run discovery using GPT-4o with web search.
    Returns same company list structure as Grok/Claude discovery.
    """
    bu_label = {
        "NAM":  "North America (US, Canada, Mexico)",
        "E&L":  "Europe or Latin America",
        "APAC": "Asia Pacific (including Australia and New Zealand)",
    }.get(bu, bu)

    user_prompt = OPENAI_DISCOVERY_USER.format(
        n=n_companies,
        geography=bu_label,
        brief=brief,
        vertical=vertical or "OTT/Streaming",
    )

    logger.info(f"OpenAI Discovery: starting | vertical={vertical} | BU={bu} | n={n_companies}")

    client = _get_client()

    response = client.responses.create(
        model=config.OPENAI_DISCOVERY_MODEL,
        instructions=OPENAI_DISCOVERY_SYSTEM,
        input=user_prompt,
        tools=[{"type": "web_search_2025_08_26"}],
    )

    # Extract text from response output
    final_text = ""
    for item in response.output:
        if hasattr(item, "type") and item.type == "message":
            for part in item.content:
                if hasattr(part, "type") and part.type == "output_text":
                    final_text = part.text
                    break
        if final_text:
            break

    # Track usage
    if usage_tracker and hasattr(response, "usage") and response.usage:
        # Record against Sonnet bucket — no dedicated OpenAI bucket yet
        usage_tracker.record_sonnet(
            input_tokens=int(getattr(response.usage, "input_tokens", 0)),
            output_tokens=int(getattr(response.usage, "output_tokens", 0)),
        )

    tokens_in  = getattr(response.usage, "input_tokens",  0) if response.usage else 0
    tokens_out = getattr(response.usage, "output_tokens", 0) if response.usage else 0
    logger.info(
        f"OpenAI Discovery: complete | "
        f"{tokens_in}in/{tokens_out}out tokens | {len(final_text)} chars"
    )

    if not final_text:
        raise ValueError("OpenAI Discovery returned empty response")

    try:
        result = _extract_json(final_text)
    except json.JSONDecodeError as exc:
        logger.error(f"OpenAI Discovery JSON parse failed: {exc}\nRaw:\n{final_text[:500]}")
        raise

    companies = result.get("companies", [])
    logger.info(f"OpenAI Discovery: {len(companies)} companies found")
    for c in companies:
        logger.info(
            f"  · {c.get('name')} [{c.get('signal_type')}] "
            f"score={c.get('opportunity_score')} — {c.get('evidence','')[:80]}"
        )

    return result