"""
tools/grok.py — Grok-4-1 Agentic Research (2026 Deep-Nesting Edition).
"""

import json
import logging
import re
from datetime import datetime
from typing import List

import requests

import config
from prompts.scout import build_scout_prompt
from utils.helpers import with_retries

logger = logging.getLogger("ott_lead_gen.grok")

_VALID_OPPORTUNITY_TYPES = config.VALID_OPPORTUNITY_TYPES

@with_retries(max_attempts=3, delay=15.0, exceptions=(Exception,))
def run_discovery_waterfall(brief: str, bu: str = "", signals: list = None, usage_tracker=None) -> dict:
    """
    Lightweight discovery sweep — uses discovery_scout.py as the system prompt.
    Dynamically injects targeted search instructions based on selected signals.
    Returns company names with evidence only — no deep research.
    """
    if not config.XAI_API_KEY:
        raise ValueError("XAI_API_KEY is not set.")

    from prompts.discovery_scout import build_discovery_system_prompt, build_discovery_user_prompt

    system_prompt = build_discovery_system_prompt()
    user_prompt   = build_discovery_user_prompt(brief, bu=bu, signals=signals or [])

    logger.info(f"Grok Discovery: scanning for companies | BU={bu} | brief={brief[:80]}...")

    url     = "https://api.x.ai/v1/responses"
    headers = {
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {config.XAI_API_KEY}",
    }

    payload = {
        "model": config.GROK_SCOUT_MODEL,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "tools": [
            {"type": "web_search"},
            {"type": "x_search"},
        ],
        "temperature": 0.1,
        "store_messages": True,
    }

    response = requests.post(url, headers=headers, json=payload, timeout=180)

    if response.status_code != 200:
        logger.error(f"Grok Discovery API Error {response.status_code}: {response.text}")
        response.raise_for_status()

    data = response.json()

    raw = ""
    for item in data.get("output", []):
        if item.get("type") == "message" and "content" in item:
            for part in item["content"]:
                if part.get("type") == "output_text":
                    raw = part.get("text", "")
                    break
        elif item.get("type") == "text":
            raw = item.get("text", "")
        if raw:
            break

    logger.info(f"Grok Discovery: response received — {len(raw)} chars")

    if usage_tracker is not None:
        usage_data = data.get("usage", {})
        usage_tracker.record_grok(
            input_tokens=usage_data.get("input_tokens", 0),
            output_tokens=usage_data.get("output_tokens", 0),
        )

    if not raw:
        raise ValueError("Grok Discovery returned empty response.")

    cleaned = raw.strip()
    if not cleaned.startswith("{"):
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            cleaned = m.group(0)

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error(f"Grok Discovery JSON parse failed: {exc}\nRaw:\n{raw[:500]}")
        raise

    companies = result.get("companies", [])
    logger.info(f"Grok Discovery: {len(companies)} companies found")
    for c in companies:
        logger.info(f"  · {c.get('name')} [{c.get('signal_type')}] — {c.get('evidence', '')[:80]}")

    return result


@with_retries(max_attempts=3, delay=15.0, exceptions=(Exception,))
def run_research_waterfall(query: str, usage_tracker=None) -> dict:
    if not config.XAI_API_KEY:
        raise ValueError("XAI_API_KEY is not set.")

    press_sources = []
    try:
        from core.sheets import SheetsClient
        sc = SheetsClient()
        press_sources = sc.get_press_sources()
    except Exception:
        pass  # degrade gracefully to hardcoded sources

    system_prompt = build_scout_prompt(
        max_prospects=config.MAX_PROSPECTS_PER_RUN,
        press_sources=press_sources or None,
    )

    user_prompt = (
        f"Execute the full OTT intelligence waterfall for: {query}\n\n"
        f"Return ONLY a JSON object following the Phase 3 schema."
    )

    logger.info(f"Grok: starting Agentic research waterfall for '{query}'")

    url = "https://api.x.ai/v1/responses"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.XAI_API_KEY}"
    }

    payload = {
        "model": config.GROK_SCOUT_MODEL,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "tools": [
            {"type": "web_search"},
            {"type": "x_search"}
        ],
        "temperature": 0.1,
        "store_messages": True
    }

    response = requests.post(url, headers=headers, json=payload, timeout=180)

    if response.status_code != 200:
        logger.error(f"Grok API Error {response.status_code}: {response.text}")
        response.raise_for_status()

    data = response.json()

    raw = ""
    for item in data.get("output", []):
        if item.get("type") == "message" and "content" in item:
            for part in item["content"]:
                if part.get("type") == "output_text":
                    raw = part.get("text", "")
                    break
        elif item.get("type") == "text":
            raw = item.get("text", "")
        if raw:
            break

    logger.info(f"Grok: Agentic response received — {len(raw)} chars")

    if usage_tracker is not None:
        usage_data = data.get("usage", {})
        usage_tracker.record_grok(
            input_tokens=usage_data.get("input_tokens", 0),
            output_tokens=usage_data.get("output_tokens", 0),
        )

    return _parse_response(raw, query, data.get("sources", []))


def _parse_response(raw: str, query: str, sources: List[dict] = None) -> dict:
    if not raw:
        raise ValueError("Grok returned an empty response. Verify model tool permissions.")

    cleaned = raw.strip()

    # Extract JSON object even if the model adds prose
    if not cleaned.startswith("{"):
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            cleaned = m.group(0)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error(f"Grok JSON parse failed: {exc}\nRaw:\n{raw[:500]}")
        raise

    # Normalise results
    if "prospects" not in data:
        data = {"prospects": [data] if isinstance(data, dict) else data}

    # Sanitise opportunity_type — must be one of the known labels
    for prospect in data.get("prospects", []):
        ot = prospect.get("opportunity_type", "")
        if not isinstance(ot, str) or ot not in _VALID_OPPORTUNITY_TYPES:
            logger.warning(
                "Invalid opportunity_type for '%s': %r — clearing field",
                prospect.get("name", "unknown"),
                ot[:80] if isinstance(ot, str) else ot,
            )
            prospect["opportunity_type"] = ""

    data.setdefault("run_metadata", {}).update({
        "query": query,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "prospects_found": len(data.get("prospects", [])),
        "citations": [s.get("url") for s in (sources or []) if s.get("url")]
    })

    return data