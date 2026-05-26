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
        if not config.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not set.")
        _client = OpenAI(api_key=config.OPENAI_API_KEY)
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


OPENAI_DISCOVERY_SYSTEM = """You are a B2B sales intelligence researcher for Accedo, a specialist OTT front-end development firm.

Accedo builds native CTV applications (Samsung Tizen, LG webOS, Roku, Fire TV, Apple TV, Android TV) for media companies, sports leagues, broadcasters, and streaming services.

An Accedo prospect is a CONTENT OWNER that needs a CTV app built:
- Sports leagues, regional sports networks, broadcasters
- Faith, fitness, entertainment, news streaming services  
- Pay TV operators or telcos with video products
- Any company that owns video content and needs a Samsung/LG/Roku app to deliver it

NOT Accedo prospects — exclude these entirely:
- CTV advertising or ad tech platforms (tvScientific, Vibe, MNTN)
- Measurement, analytics, or attribution companies
- CDN, infrastructure, or streaming technology vendors
- Companies that clearly build all technology in-house (Netflix, Disney, Amazon, Apple)

Search thoroughly. Verify each company is a real content owner with a genuine buying signal before including it. Quality over quantity — only include companies you can verify."""

OPENAI_DISCOVERY_USER = """Search the web to find {n} companies matching this brief:

{brief}

Geography: {geography}

Search multiple times using different queries. For each candidate verify:
1. They own content and need a CTV app built (not ad tech or infrastructure)
2. They have a real, sourced buying signal matching the brief
3. They are based in {geography}

After searching, return your findings as a JSON object:
{{
  "companies": [
    {{
      "name": "Company Name",
      "hq_country": "United States",
      "domain": "company.com",
      "signal_type": "CTV launch|Funding round|Hiring|Platform gap|Vendor friction|M&A|App redesign",
      "evidence": "Specific signal with source name and approximate date",
      "source_url": "https://source.com or empty string"
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