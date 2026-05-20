"""
tools/gemini.py — Gemini Flash client.

Single job: enrich_brief()
  Takes the auto-built brief and enriches it with industry-aware terminology,
  signal groupings, and an aggregation hint for Grok.
  Falls back gracefully to the auto-built brief if Gemini fails.
"""

import logging
import os
import re
import json
from typing import List

import requests

import config
from prompts.gemini_scorer import BRIEF_ENRICHMENT_PROMPT

logger = logging.getLogger("ott_lead_gen.gemini")

GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta/models"


def _call_gemini(prompt: str, max_tokens: int = 512) -> tuple:
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set.")
    api_url = f"{GEMINI_BASE_URL}/{config.GEMINI_DISCOVERY_MODEL}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.3},
    }
    resp = requests.post(f"{api_url}?key={GEMINI_API_KEY}", json=payload, timeout=30)
    if resp.status_code != 200:
        logger.error(f"Gemini API error {resp.status_code}: {resp.text[:300]}")
        resp.raise_for_status()
    data     = resp.json()
    raw_text = (
        data.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "")
    )
    if not raw_text:
        raise ValueError("Gemini returned empty content")
    usage = data.get("usageMetadata", {})
    return raw_text.strip(), usage.get("promptTokenCount", 0), usage.get("candidatesTokenCount", 0)


def _extract_json(raw: str):

    if not raw:
        raise ValueError("Empty response")
    text = raw.strip()
    
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        text = brace.group(0)
    return json.loads(text)


def enrich_brief(
    auto_brief: str,
    verticals: List[str],
    signals: List[str],
    bu: str,
    usage_tracker=None,
) -> dict:
    """
    Enrich an auto-built brief with industry-aware terminology, signal groupings,
    and an aggregation hint. Returns enriched_brief and used_gemini flag.
    Never raises — falls back to auto_brief on any failure.
    """
    bu_label = {
        "NAM":  "North America (US, Canada, Mexico)",
        "E&L":  "Europe or Latin America",
        "APAC": "Asia Pacific (including Australia and New Zealand)",
    }.get(bu, bu)

    prompt = BRIEF_ENRICHMENT_PROMPT.format(
        verticals=", ".join(verticals),
        signals=", ".join(signals),
        bu_label=bu_label,
        auto_brief=auto_brief,
    )

    try:
        raw, tokens_in, tokens_out = _call_gemini(prompt, max_tokens=512)
        if usage_tracker:
            usage_tracker.record_gemini(tokens_in, tokens_out)

        result        = _extract_json(raw)
        vertical_desc = result.get("vertical_description", "").strip()
        signal_groups = result.get("signal_groups", [])
        agg_hint      = result.get("aggregation_hint", "").strip()

        if not vertical_desc or not signal_groups:
            raise ValueError("Incomplete enrichment response")

        signal_lines = "\n".join(
            f"- [{g.get('label', '')}]: {g.get('description', '')}"
            for g in signal_groups
        )

        enriched = (
            f"Find Tier 1, Tier 2, and ambitious Tier 3 {vertical_desc} "
            f"headquartered in {bu_label}.\n\n"
            f"SIGNAL FOCUS:\n{signal_lines}\n\n"
            f"AGGREGATION PRIORITY: {agg_hint}"
        )

        logger.info(f"Gemini enrichment OK — {len(enriched)} chars")
        return {"enriched_brief": enriched, "used_gemini": True}

    except Exception as exc:
        logger.warning(f"Gemini enrichment failed ({exc}) — using auto-built brief")
        return {"enriched_brief": auto_brief, "used_gemini": False}