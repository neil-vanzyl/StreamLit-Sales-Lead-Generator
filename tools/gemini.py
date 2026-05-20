"""
tools/gemini.py — Gemini Flash client.

Single job: enrich_brief()
  Takes the auto-built brief and enriches it with industry-aware terminology,
  signal groupings, and an aggregation hint for Grok.
  Falls back gracefully to the auto-built brief if Gemini fails.
"""

import logging
import os
from typing import List

import requests

import config
from prompts.gemini_scorer import BRIEF_ENRICHMENT_PROMPT

logger = logging.getLogger("ott_lead_gen.gemini")

GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta/models"


def _call_gemini(prompt: str, max_tokens: int = 1024) -> tuple:
    api_key = config.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set.")
    api_url = f"{GEMINI_BASE_URL}/{config.GEMINI_DISCOVERY_MODEL}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.3},
    }
    resp = requests.post(f"{api_url}?key={api_key}", json=payload, timeout=30)
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

    prompt = (BRIEF_ENRICHMENT_PROMPT
        .replace("{verticals}", ", ".join(verticals))
        .replace("{signals}", ", ".join(signals))
        .replace("{bu_label}", bu_label)
        .replace("{auto_brief}", auto_brief)
    )

    try:
        raw, tokens_in, tokens_out = _call_gemini(prompt, max_tokens=512)
        if usage_tracker:
            usage_tracker.record_gemini(tokens_in, tokens_out)

        # Parse single-line response split by ||
        parts         = raw.strip().split("||")
        vertical_desc = ""
        signal_lines  = ""
        agg_hint      = ""

        for part in parts:
            part = part.strip()
            if part.upper().startswith("VERTICAL:"):
                vertical_desc = part[9:].strip()
            elif part.upper().startswith("SIGNALS:"):
                signal_lines = part[8:].strip()
            elif part.upper().startswith("AGGREGATION:"):
                agg_hint = part[12:].strip()

        if not vertical_desc:
            raise ValueError("Could not parse VERTICAL from Gemini response")

        enriched = (
            f"Find Tier 1, Tier 2, and ambitious Tier 3 {vertical_desc} "
            f"headquartered in {bu_label}.\n\n"
            f"SIGNAL FOCUS: {signal_lines}\n\n"
            f"AGGREGATION PRIORITY: {agg_hint}"
        )

        logger.info(f"Gemini enrichment OK — {len(enriched)} chars")
        return {"enriched_brief": enriched, "used_gemini": True}

    except Exception as exc:
        logger.warning(f"Gemini enrichment failed ({exc}) — using auto-built brief")
        return {"enriched_brief": auto_brief, "used_gemini": False}