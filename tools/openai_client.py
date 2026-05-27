"""
tools/openai_client.py — OpenAI Deep Research discovery.

Uses o4-mini-deep-research via the Responses API — the same engine
that powers ChatGPT's deep research mode. Multi-step agentic search
with reasoning, not a single-shot web search call.
"""

import json
import logging
import re
import time
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
        _client = OpenAI(api_key=api_key, max_retries=5, timeout=700)
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


DEEP_RESEARCH_SYSTEM = """You are a B2B sales intelligence researcher for Accedo, a specialist OTT front-end development firm.

Accedo builds native CTV applications (Samsung Tizen, LG webOS, Roku, Fire TV, Apple TV, Android TV) for media companies, sports leagues, broadcasters, and streaming services. Accedo does NOT build ad tech, measurement platforms, or backend infrastructure.

An Accedo prospect is a CONTENT OWNER that needs a CTV app built:
- Sports leagues, regional sports networks, broadcasters, rights holders
- Faith, fitness, entertainment, news streaming services
- Pay TV operators or telcos with a video product
- Any company that OWNS VIDEO CONTENT and needs a Samsung/LG/Roku/FireTV app to deliver it to viewers

NOT Accedo prospects — exclude entirely:
- CTV advertising platforms, ad tech, or measurement companies (tvScientific, Vibe, MNTN, StackAdapt)
- CDN, transcoding, or streaming infrastructure vendors
- Companies that clearly build all technology in-house at scale (Netflix, Disney+, Amazon Prime, Apple TV+, Google/YouTube)
- Recruiting or staffing firms

For each company you identify, verify:
1. They own video content — not just distribute or monetise it
2. They have a specific, dated, verifiable buying signal
3. They are headquartered or primarily operating in the requested geography"""

DEEP_RESEARCH_USER = """{brief}

Geography: {geography}

Research this thoroughly. Search for:
- Companies matching the criteria in the brief with verified recent signals
- Check thestreamable.com to verify which companies are missing Samsung or LG apps
- Check crunchbase.com and techcrunch.com for recent funding rounds
- Check LinkedIn Jobs and company career pages for OTT/streaming/CTV hiring
- Check sportsvideo.org, broadcastingcable.com, and streamingmediablog.com for recent launches and signals

After researching, return a JSON object:
{{
  "companies": [
    {{
      "name": "Company Name",
      "domain": "company.com",
      "hq_country": "United States",
      "signal_type": "CTV launch|Funding round|Hiring|Platform gap|Vendor friction|M&A|App redesign",
      "evidence": "Specific signal with source name and date",
      "source_url": "https://source.com or empty string"
    }}
  ],
  "search_summary": "2-3 sentences summarising what you found and what signals were most common"
}}"""


@with_retries(max_attempts=2, delay=30.0, exceptions=(Exception,))
def run_openai_discovery(
    brief: str,
    bu: str = "NAM",
    vertical: str = "",
    signals: list = None,
    n_companies: int = 8,
    usage_tracker=None,
    progress_callback=None,
) -> dict:
    """
    Run discovery using OpenAI Deep Research (o4-mini-deep-research).
    Uses streaming to keep the Streamlit WebSocket alive during the 3-5 min run.

    Args:
        progress_callback: optional callable(message: str) for live status updates
    """
    bu_label = {
        "NAM":  "North America (US, Canada, Mexico)",
        "E&L":  "Europe or Latin America",
        "APAC": "Asia Pacific (including Australia and New Zealand)",
    }.get(bu, bu)

    user_prompt = DEEP_RESEARCH_USER.format(
        brief=brief,
        geography=bu_label,
    )

    logger.info(f"OpenAI Discovery (gpt-5-mini): starting | vertical={vertical} | BU={bu}")

    client = _get_client()
    t0 = time.monotonic()

    final_text   = ""
    tokens_in    = 0
    tokens_out   = 0
    search_count = 0

    # Use streaming so the connection stays alive during the long research run
    with client.responses.stream(
        model="gpt-5-mini",
        input=[
            {
                "role": "developer",
                "content": [{"type": "input_text", "text": DEEP_RESEARCH_SYSTEM}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": user_prompt}],
            },
        ],
        tools=[{"type": "web_search_preview"}],
        timeout=600,
    ) as stream:
        for event in stream:
            event_type = getattr(event, "type", "")

            if event_type == "response.output_text.delta":
                delta = getattr(event, "delta", "")
                final_text += delta

            elif event_type == "response.web_search_call.searching":
                search_count += 1
                query = getattr(event, "query", "")
                logger.info(f"  Deep Research: search {search_count} — {query[:60]}")
                if progress_callback:
                    progress_callback(f"Searching... ({search_count} searches so far)")

            elif event_type == "response.completed":
                usage = getattr(event.response, "usage", None)
                if usage:
                    tokens_in  = getattr(usage, "input_tokens",  0)
                    tokens_out = getattr(usage, "output_tokens", 0)

    elapsed = time.monotonic() - t0

    if usage_tracker:
        usage_tracker.record_sonnet(
            input_tokens=int(tokens_in),
            output_tokens=int(tokens_out),
        )

    logger.info(
        f"OpenAI Deep Research: complete | {elapsed:.0f}s | "
        f"{search_count} searches | {tokens_in}in/{tokens_out}out | {len(final_text)} chars"
    )

    if not final_text:
        raise ValueError("OpenAI Deep Research returned empty response")

    try:
        result = _extract_json(final_text)
    except json.JSONDecodeError as exc:
        logger.error(f"OpenAI Deep Research JSON parse failed: {exc}\nRaw:\n{final_text[:500]}")
        raise

    companies = result.get("companies", [])
    logger.info(f"OpenAI Deep Research: {len(companies)} companies found")
    for c in companies:
        logger.info(
            f"  · {c.get('name')} [{c.get('signal_type')}] "
            f"— {c.get('evidence', '')[:80]}"
        )

    return result