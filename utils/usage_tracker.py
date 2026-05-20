"""
utils/usage_tracker.py — Per-run API usage and cost tracking
=============================================================
Accumulates token counts and API credits across a full pipeline run,
then produces a cost summary log line and GUI-ready dict.

Pricing constants reflect published rates as of May 2026:
  Grok grok-4-1-fast-reasoning: $3/1M input, $15/1M output  (xAI)
  Claude Sonnet 4-5:            $3/1M input, $15/1M output  (Anthropic)
  Claude Opus 4-5:              $15/1M input, $75/1M output (Anthropic)
  Exa standard search:          $0.005 per credit
  Apollo bulk enrich:           $0.49 per credit
  Apollo people search:         $0.00 (zero-credit endpoint)

Usage is written to usage_log.jsonl (one JSON object per run) so cost
can be tracked over time without opening each vendor's dashboard.

Thread-safe: each RunUsage instance is owned by one pipeline run.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger("ott_lead_gen.usage")

USAGE_LOG_FILE = "usage_log.jsonl"

# ---------------------------------------------------------------------------
# Pricing (per-unit costs in USD)
# ---------------------------------------------------------------------------

PRICE = {
    # LLM tokens — price per 1M tokens
    "grok_input_per_1m":    3.00,
    "grok_output_per_1m":  15.00,
    "sonnet_input_per_1m":  3.00,
    "sonnet_output_per_1m": 15.00,
    "opus_input_per_1m":   15.00,
    "opus_output_per_1m":  25.00,
    # API credits — price per credit
    "exa_per_credit":       0.005,
    "apollo_per_credit":    0.490,
    "gemini_input_per_1m":  0.075,
    "gemini_output_per_1m": 0.30,
}


def _token_cost(tokens: int, price_per_1m: float) -> float:
    return (tokens / 1_000_000) * price_per_1m


# ---------------------------------------------------------------------------
# Per-prospect usage snapshot
# ---------------------------------------------------------------------------

@dataclass
class ProspectUsage:
    """Usage snapshot for one prospect through the full pipeline."""
    company: str = ""

    # Grok
    grok_input_tokens:  int = 0
    grok_output_tokens: int = 0

    # Claude Sonnet (analyst)
    sonnet_input_tokens:  int = 0
    sonnet_output_tokens: int = 0

    # Claude Opus (copywriter)
    opus_input_tokens:  int = 0
    opus_output_tokens: int = 0

    # Exa — tracked by call count (no SDK-level credit field)
    exa_exec_searches:   int = 0   # LinkedIn + broad exec searches
    exa_jd_reads:        int = 0   # job description /contents fetches
    exa_verifications:   int = 0   # signal source verifications

    # Apollo
    apollo_search_calls: int = 0   # People Search — always 0 credits
    apollo_enrich_credits: int = 0  # Bulk Enrich — 1 credit per matched person

    #Gemini
    gemini_input_tokens:  int = 0
    gemini_output_tokens: int = 0

    @property
    def exa_credits(self) -> int:
        return self.exa_exec_searches + self.exa_jd_reads + self.exa_verifications

    @property
    def cost_usd(self) -> float:
        return (
            _token_cost(self.grok_input_tokens,   PRICE["grok_input_per_1m"])
          + _token_cost(self.grok_output_tokens,  PRICE["grok_output_per_1m"])
          + _token_cost(self.gemini_input_tokens, PRICE["gemini_input_per_1m"])
          + _token_cost(self.gemini_output_tokens,PRICE["gemini_output_per_1m"])
          + _token_cost(self.sonnet_input_tokens,  PRICE["sonnet_input_per_1m"])
          + _token_cost(self.sonnet_output_tokens, PRICE["sonnet_output_per_1m"])
          + _token_cost(self.opus_input_tokens,    PRICE["opus_input_per_1m"])
          + _token_cost(self.opus_output_tokens,   PRICE["opus_output_per_1m"])
          + self.exa_credits * PRICE["exa_per_credit"]
          + self.apollo_enrich_credits * PRICE["apollo_per_credit"]
        )

    def to_dict(self) -> dict:
        return {
            "company":               self.company,
            "grok_input_tokens":     self.grok_input_tokens,
            "grok_output_tokens":    self.grok_output_tokens,
            "gemini_input_tokens":   self.gemini_input_tokens,
            "gemini_output_tokens":  self.gemini_output_tokens,
            "sonnet_input_tokens":   self.sonnet_input_tokens,
            "sonnet_output_tokens":  self.sonnet_output_tokens,
            "opus_input_tokens":     self.opus_input_tokens,
            "opus_output_tokens":    self.opus_output_tokens,
            "exa_exec_searches":     self.exa_exec_searches,
            "exa_jd_reads":          self.exa_jd_reads,
            "exa_verifications":     self.exa_verifications,
            "exa_credits_total":     self.exa_credits,
            "apollo_search_calls":   self.apollo_search_calls,
            "apollo_enrich_credits": self.apollo_enrich_credits,
            "cost_usd":              round(self.cost_usd, 4),
        }


# ---------------------------------------------------------------------------
# Per-run accumulator
# ---------------------------------------------------------------------------

class RunUsage:
    """
    Accumulates usage across an entire pipeline run (one query → N prospects).
    One instance per run_pipeline() call.

    Usage:
        usage = RunUsage(query="sports broadcaster OTT...")
        usage.start_prospect("FuboTV")
        usage.record_grok(input_tokens=4821, output_tokens=1203)
        usage.record_sonnet(input_tokens=980, output_tokens=312)
        usage.record_opus(input_tokens=1420, output_tokens=580)
        usage.record_exa(exec_searches=2, jd_reads=1, verifications=2)
        usage.record_apollo(search_calls=2, enrich_credits=2)
        usage.end_prospect()
        usage.finish()
        usage.save()
        summary = usage.summary()   # → dict for GUI
    """

    def __init__(self, query: str) -> None:
        self.query       = query
        self.started_at  = datetime.now(timezone.utc).isoformat()
        self._start_time = time.monotonic()
        self._prospects: list[ProspectUsage] = []
        self._current: Optional[ProspectUsage] = None
        self._duration_s: float = 0.0

    # ------------------------------------------------------------------
    # Prospect lifecycle
    # ------------------------------------------------------------------

    def start_prospect(self, company: str) -> None:
        """Call at the start of process_prospect()."""
        self._current = ProspectUsage(company=company)

    def end_prospect(self) -> None:
        """Call at the end of process_prospect()."""
        if self._current:
            self._prospects.append(self._current)
            self._current = None

    # ------------------------------------------------------------------
    # Per-tool recording
    # ------------------------------------------------------------------

    def record_grok(self, input_tokens: int, output_tokens: int) -> None:
        if self._current:
            self._current.grok_input_tokens  += input_tokens
            self._current.grok_output_tokens += output_tokens
        logger.info(
            f"Usage | Grok    | in={input_tokens:,} out={output_tokens:,} "
            f"tokens | est ${_token_cost(input_tokens, PRICE['grok_input_per_1m']) + _token_cost(output_tokens, PRICE['grok_output_per_1m']):.4f}"
        )

    def record_gemini(self, input_tokens: int, output_tokens: int) -> None:
        if self._current:
            self._current.gemini_input_tokens  += input_tokens
            self._current.gemini_output_tokens += output_tokens
        logger.info(
            f"Usage | Gemini  | in={input_tokens:,} out={output_tokens:,} "
            f"tokens | est ${_token_cost(input_tokens, PRICE['gemini_input_per_1m']) + _token_cost(output_tokens, PRICE['gemini_output_per_1m']):.4f}"
        )

    def record_sonnet(self, input_tokens: int, output_tokens: int) -> None:
        if self._current:
            self._current.sonnet_input_tokens  += input_tokens
            self._current.sonnet_output_tokens += output_tokens
        logger.info(
            f"Usage | Sonnet  | in={input_tokens:,} out={output_tokens:,} "
            f"tokens | est ${_token_cost(input_tokens, PRICE['sonnet_input_per_1m']) + _token_cost(output_tokens, PRICE['sonnet_output_per_1m']):.4f}"
        )

    def record_opus(self, input_tokens: int, output_tokens: int) -> None:
        if self._current:
            self._current.opus_input_tokens  += input_tokens
            self._current.opus_output_tokens += output_tokens
        logger.info(
            f"Usage | Opus    | in={input_tokens:,} out={output_tokens:,} "
            f"tokens | est ${_token_cost(input_tokens, PRICE['opus_input_per_1m']) + _token_cost(output_tokens, PRICE['opus_output_per_1m']):.4f}"
        )

    def record_exa(
        self,
        exec_searches: int = 0,
        jd_reads: int = 0,
        verifications: int = 0,
    ) -> None:
        if self._current:
            self._current.exa_exec_searches  += exec_searches
            self._current.exa_jd_reads       += jd_reads
            self._current.exa_verifications  += verifications
        total = exec_searches + jd_reads + verifications
        logger.info(
            f"Usage | Exa     | exec={exec_searches} jd={jd_reads} verify={verifications} "
            f"credits={total} | est ${total * PRICE['exa_per_credit']:.4f}"
        )

    def record_apollo(self, search_calls: int = 0, enrich_credits: int = 0) -> None:
        if self._current:
            self._current.apollo_search_calls   += search_calls
            self._current.apollo_enrich_credits += enrich_credits
        logger.info(
            f"Usage | Apollo  | searches={search_calls} (free) enrich={enrich_credits} "
            f"credits | est ${enrich_credits * PRICE['apollo_per_credit']:.4f}"
        )

    # ------------------------------------------------------------------
    # Run totals
    # ------------------------------------------------------------------

    def finish(self) -> None:
        """Call after all prospects are processed."""
        if self._current:
            self.end_prospect()   # safety net if end_prospect wasn't called
        self._duration_s = time.monotonic() - self._start_time
        self._log_run_summary()

    def _totals(self) -> dict:
        t: Dict[str, int | float] = {
            "grok_input_tokens":     0,
            "grok_output_tokens":    0,
            "gemini_input_tokens":   0,
            "gemini_output_tokens":  0,
            "sonnet_input_tokens":   0,
            "sonnet_output_tokens":  0,
            "opus_input_tokens":     0,
            "opus_output_tokens":    0,
            "exa_credits":           0,
            "apollo_search_calls":   0,
            "apollo_enrich_credits": 0,
            "total_cost_usd":        0.0,
        }
        for p in self._prospects:
            t["grok_input_tokens"]     += p.grok_input_tokens
            t["grok_output_tokens"]    += p.grok_output_tokens
            t["gemini_input_tokens"]  += p.gemini_input_tokens
            t["gemini_output_tokens"] += p.gemini_output_tokens
            t["sonnet_input_tokens"]   += p.sonnet_input_tokens
            t["sonnet_output_tokens"]  += p.sonnet_output_tokens
            t["opus_input_tokens"]     += p.opus_input_tokens
            t["opus_output_tokens"]    += p.opus_output_tokens
            t["exa_credits"]           += p.exa_credits
            t["apollo_search_calls"]   += p.apollo_search_calls
            t["apollo_enrich_credits"] += p.apollo_enrich_credits
            t["total_cost_usd"]        += p.cost_usd
        t["total_cost_usd"] = round(t["total_cost_usd"], 4)
        return t

    def _log_run_summary(self) -> None:
        t = self._totals()
        n = len(self._prospects)
        per = round(t["total_cost_usd"] / n, 4) if n > 0 else 0

        logger.info(
            f"\n{'─'*60}\n"
            f"USAGE SUMMARY — {n} prospect(s) | {self._duration_s:.0f}s\n"
            f"  Grok    : {t['grok_input_tokens']:>7,} in / {t['grok_output_tokens']:>6,} out tokens"
            f"  est ${_token_cost(t['grok_input_tokens'], PRICE['grok_input_per_1m']) + _token_cost(t['grok_output_tokens'], PRICE['grok_output_per_1m']):.4f}\n"
            f"  Sonnet  : {t['sonnet_input_tokens']:>7,} in / {t['sonnet_output_tokens']:>6,} out tokens"
            f"  est ${_token_cost(t['sonnet_input_tokens'], PRICE['sonnet_input_per_1m']) + _token_cost(t['sonnet_output_tokens'], PRICE['sonnet_output_per_1m']):.4f}\n"
            f"  Opus    : {t['opus_input_tokens']:>7,} in / {t['opus_output_tokens']:>6,} out tokens"
            f"  est ${_token_cost(t['opus_input_tokens'], PRICE['opus_input_per_1m']) + _token_cost(t['opus_output_tokens'], PRICE['opus_output_per_1m']):.4f}\n"
            f"  Exa     : {t['exa_credits']:>3} credits (searches + JD reads + verifications)"
            f"  est ${t['exa_credits'] * PRICE['exa_per_credit']:.4f}\n"
            f"  Apollo  : {t['apollo_search_calls']:>2} searches (free) + {t['apollo_enrich_credits']:>2} enrich credits"
            f"  est ${t['apollo_enrich_credits'] * PRICE['apollo_per_credit']:.4f}\n"
            f"  {'─'*40}\n"
            f"  TOTAL   : ${t['total_cost_usd']:.4f}  (~${per:.4f}/prospect)\n"
            f"{'─'*60}"
        )

    def summary(self) -> dict:
        """Return a GUI-ready dict. Call after finish()."""
        t = self._totals()
        n = len(self._prospects)
        return {
            "query":            self.query,
            "prospects":        n,
            "duration_s":       round(self._duration_s, 1),
            "grok": {
                "input_tokens":  t["grok_input_tokens"],
                "output_tokens": t["grok_output_tokens"],
                "cost_usd":      round(
                    _token_cost(t["grok_input_tokens"],  PRICE["grok_input_per_1m"]) +
                    _token_cost(t["grok_output_tokens"], PRICE["grok_output_per_1m"]), 4
                ),
            },
            "gemini": {
                "input_tokens":  t["gemini_input_tokens"],
                "output_tokens": t["gemini_output_tokens"],
                "cost_usd": round(
                    _token_cost(t["gemini_input_tokens"],  PRICE["gemini_input_per_1m"]) +
                    _token_cost(t["gemini_output_tokens"], PRICE["gemini_output_per_1m"]), 4
                ),
            },
            "sonnet": {
                "input_tokens":  t["sonnet_input_tokens"],
                "output_tokens": t["sonnet_output_tokens"],
                "cost_usd":      round(
                    _token_cost(t["sonnet_input_tokens"],  PRICE["sonnet_input_per_1m"]) +
                    _token_cost(t["sonnet_output_tokens"], PRICE["sonnet_output_per_1m"]), 4
                ),
            },
            "opus": {
                "input_tokens":  t["opus_input_tokens"],
                "output_tokens": t["opus_output_tokens"],
                "cost_usd":      round(
                    _token_cost(t["opus_input_tokens"],  PRICE["opus_input_per_1m"]) +
                    _token_cost(t["opus_output_tokens"], PRICE["opus_output_per_1m"]), 4
                ),
            },
            "exa": {
                "credits": t["exa_credits"],
                "cost_usd": round(t["exa_credits"] * PRICE["exa_per_credit"], 4),
            },
            "apollo": {
                "search_calls":    t["apollo_search_calls"],
                "enrich_credits":  t["apollo_enrich_credits"],
                "cost_usd":        round(t["apollo_enrich_credits"] * PRICE["apollo_per_credit"], 4),
            },
            "total_cost_usd":   t["total_cost_usd"],
            "cost_per_prospect": round(t["total_cost_usd"] / n, 4) if n > 0 else 0,
            "per_prospect":     [p.to_dict() for p in self._prospects],
        }

    def save(self) -> None:
        """Append run summary to usage_log.jsonl for historical tracking."""
        record = {
            "timestamp":  self.started_at,
            "query":      self.query[:80],
            **self.summary(),
        }
        try:
            with open(USAGE_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
            logger.debug(f"Usage: appended to {USAGE_LOG_FILE}")
        except Exception as exc:
            logger.warning(f"Usage: could not write to {USAGE_LOG_FILE}: {exc}")


# ---------------------------------------------------------------------------
# Historical log reader (for GUI)
# ---------------------------------------------------------------------------

def load_usage_history(max_runs: int = 30) -> list:
    """Read the last N runs from usage_log.jsonl. Returns [] if file missing."""
    if not os.path.exists(USAGE_LOG_FILE):
        return []
    try:
        with open(USAGE_LOG_FILE, encoding="utf-8") as f:
            lines = f.readlines()
        records = []
        for line in reversed(lines):
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            if len(records) >= max_runs:
                break
        return records
    except Exception as exc:
        logger.warning(f"Usage: could not read {USAGE_LOG_FILE}: {exc}")
        return []
