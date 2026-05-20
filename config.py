"""
config.py — Central configuration for the OTT Lead Gen frontier pipeline.
All secrets are loaded from environment variables. Never hardcode here.

Required .env entries:
    XAI_API_KEY="xai-..."
    ANTHROPIC_API_KEY="sk-ant-..."
    GOOGLE_SERVICE_ACCOUNT_JSON="service_account.json"
    GOOGLE_SHEET_NAME="OTT Leads"

Optional .env entries (pipeline degrades gracefully without them):
    EXA_API_KEY="..."                  # LinkedIn post intelligence
    APOLLO_MASTER_API_KEY="..."        # Apollo People Search (zero credits)
    APOLLO_API_KEY="..."               # Apollo Bulk Enrichment (1 credit/person)
    GEMINI_API_KEY="..."               # Gemini Flash discovery + scoring
    SERPER_API_KEY="..."               # Job board mining
    JINA_API_KEY="..."                 # Universal URL reader
    BUILTWITH_API_KEY="..."            # Tech stack fingerprinting

Apollo key setup:
    APOLLO_MASTER_API_KEY — required for /mixed_people/api_search
        Generate at: app.apollo.io -> Settings -> Integrations -> API Keys
        Click "Create New Key" -> select type "Master"
    APOLLO_API_KEY — standard key for /people/bulk_match
        Same page, standard key type
"""

try:
    import streamlit as st
    # Mirror Streamlit secrets into os.environ so the rest of config.py works unchanged
    for key, value in st.secrets.items():
        import os
        os.environ.setdefault(key, str(value))
except Exception:
    pass  # Not running on Streamlit Cloud — .env handles it locally

import os
from typing import List
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Required API Keys
# ---------------------------------------------------------------------------
XAI_API_KEY: str = os.environ.get("XAI_API_KEY", "")
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")

# ---------------------------------------------------------------------------
# Google Sheets
# ---------------------------------------------------------------------------
GOOGLE_SERVICE_ACCOUNT_JSON: str = os.environ.get(
    "GOOGLE_SERVICE_ACCOUNT_JSON", "service_account.json"
)
GOOGLE_SHEET_NAME: str = os.environ.get("GOOGLE_SHEET_NAME", "OTT Leads")
GOOGLE_WORKSHEET_NAME: str = os.environ.get("GOOGLE_WORKSHEET_NAME", "Leads")
GOOGLE_COLD_WORKSHEET_NAME: str = os.environ.get("GOOGLE_COLD_WORKSHEET_NAME", "Cold Leads")
GOOGLE_LOGS_WORKSHEET_NAME: str = os.environ.get("GOOGLE_LOGS_WORKSHEET_NAME", "Logs")
GOOGLE_ACCOUNTS_WORKSHEET_NAME: str = os.environ.get("GOOGLE_ACCOUNTS_WORKSHEET_NAME", "Accounts")
GOOGLE_SIGNALS_WORKSHEET_NAME: str = os.environ.get("GOOGLE_SIGNALS_WORKSHEET_NAME", "Signals")

# External reference sheets (read-only config, editable by non-technical users)
# Set these to the Google Sheet/Doc IDs when ready to activate
GOOGLE_PRESS_SOURCES_SHEET_ID: str = os.environ.get("GOOGLE_PRESS_SOURCES_SHEET_ID", "Press Sources")
GOOGLE_SEMANTIC_GUIDE_DOC_ID: str = os.environ.get("GOOGLE_SEMANTIC_GUIDE_DOC_ID", "")

# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
GEMINI_DISCOVERY_MODEL: str = "gemini-2.5-flash"
GEMINI_DISCOVERY_MAX_TOKENS: int = 2048

# ---------------------------------------------------------------------------
# Model selection
# ---------------------------------------------------------------------------
GROK_SCOUT_MODEL: str = "grok-4.3"
GROK_SCOUT_MAX_TOKENS: int = 10000

CLAUDE_ANALYST_MODEL: str = "claude-sonnet-4-5"
CLAUDE_ANALYST_MAX_TOKENS: int = 2048

CLAUDE_COPYWRITER_MODEL: str = "claude-opus-4-5"
CLAUDE_COPYWRITER_MAX_TOKENS: int = 2048

# ---------------------------------------------------------------------------
# Model registry — used by GUI model selector
# Costs are per 1M tokens (input, output) in USD
# ---------------------------------------------------------------------------
MODEL_OPTIONS: dict = {
    "grok": [
        {
            "label": "Grok 4.3  ·  recommended",
            "model": "grok-4.3",
            "input_cost":  1.25,
            "output_cost": 2.50,
            "note": "Latest stable — web search + X search + reasoning",
        },
        {
            "label": "Grok 4.20  ·  flagship",
            "model": "grok-4.20",
            "input_cost":  1.25,
            "output_cost": 2.50,
            "note": "Highest reasoning depth — same price, slower",
        },
    ],
    "gemini": [
        {
            "label": "Gemini 3.5 Flash  ·  recommended",
            "model": "gemini-3.5-flash",
            "input_cost":  1.50,
            "output_cost": 9.00,
            "note": "Fast, cheap — used for query translation + company scoring",
        },
        {
            "label": "Gemini Pro  ·  deeper reasoning",
            "model": "gemini-2.5-pro",
            "input_cost":  1.25,
            "output_cost": 10.00,
            "note": "Better for ambiguous or complex discovery queries",
        },
        {
            "label": "Gemini 2.5 Flash  ·  stable",
            "model": "gemini-2.5-flash",
            "input_cost":  0.075,
            "output_cost": 2.50,
            "note": "Stable Flash — reliable multi-line output, brief enrichment",
        }
    ],
    "analyst": [
        {
            "label": "Claude Sonnet 4.5  ·  recommended",
            "model": "claude-sonnet-4-5",
            "input_cost":  3.00,
            "output_cost": 15.00,
            "note": "Cost-effective qualification scoring — runs per prospect",
        },
        {
            "label": "Claude Opus 4.5  ·  highest quality",
            "model": "claude-opus-4-5",
            "input_cost":  15.00,
            "output_cost": 75.00,
            "note": "Premium reasoning — use when score accuracy is critical",
        },
    ],
    "copywriter": [
        {
            "label": "Claude Opus 4.5  ·  recommended",
            "model": "claude-opus-4-5",
            "input_cost":  15.00,
            "output_cost": 75.00,
            "note": "Best email quality — runs per HOT/WARM prospect",
        },
        {
            "label": "Claude Sonnet 4.5  ·  faster & cheaper",
            "model": "claude-sonnet-4-5",
            "input_cost":  3.00,
            "output_cost": 15.00,
            "note": "Good quality at lower cost — useful for high-volume runs",
        },
    ],
}
# ---------------------------------------------------------------------------
# Exa — LinkedIn post intelligence
# ---------------------------------------------------------------------------
EXA_API_KEY: str = os.environ.get("EXA_API_KEY", "")
EXA_ENABLED: bool = bool(EXA_API_KEY)
EXA_DAYS_BACK: int = 90
EXA_MAX_RESULTS: int = 5

# ---------------------------------------------------------------------------
# Apollo.io — Power map validation + contact enrichment
# ---------------------------------------------------------------------------
APOLLO_MASTER_API_KEY: str = os.environ.get("APOLLO_MASTER_API_KEY", "")
APOLLO_API_KEY: str = os.environ.get("APOLLO_API_KEY", "")
APOLLO_ENABLED: bool = True
APOLLO_REQUESTS_PER_MINUTE: int = 10

# ---------------------------------------------------------------------------
# Optional enrichment keys
# ---------------------------------------------------------------------------
SERPER_API_KEY: str = os.environ.get("SERPER_API_KEY", "")
JINA_API_KEY: str = os.environ.get("JINA_API_KEY", "")
BUILTWITH_API_KEY: str = os.environ.get("BUILTWITH_API_KEY", "")

# ---------------------------------------------------------------------------
# Business Unit configuration
# ---------------------------------------------------------------------------
BU_OPTIONS: List[str] = ["NAM", "E&L", "APAC"]
BU_DEFAULT: str = "NAM"

# ---------------------------------------------------------------------------
# Sales Director configuration
# ---------------------------------------------------------------------------
SALES_DIRECTORS: List[str] = [
    "Select your name...",
    "Albert Lee",
    "Ashley Desatink",
    "Mrugesh Desai",
    "Pritesh Modi",
    "Neil van Zyl",
]

DIRECTOR_BUDGET_USD: float = 75.00   # monthly budget per director

# New worksheet names
GOOGLE_USAGE_TRACKER_WORKSHEET_NAME: str = os.environ.get(
    "GOOGLE_USAGE_TRACKER_WORKSHEET_NAME", "Usage Tracker"
)
GOOGLE_ENRICHMENT_WORKSHEET_NAME: str = os.environ.get(
    "GOOGLE_ENRICHMENT_WORKSHEET_NAME", "Company Enrichment"
)

# ---------------------------------------------------------------------------
# Pipeline behaviour
# ---------------------------------------------------------------------------
MIN_SCORE_TO_WRITE: int = 55

DEDUP_STRATEGY: str = "domain+contact"

MAX_PROSPECTS_PER_RUN: int = 5

# ---------------------------------------------------------------------------
# OTT Signal Query Library
# ---------------------------------------------------------------------------
OTT_SIGNAL_QUERIES: List[str] = [
    # SIGNAL 1: THE TALENT VOID
    "site:linkedin.com/jobs 'Director of OTT' OR 'VP Engineering' streaming 'Roku' OR 'Tizen' posted >60 days ago news sports",
# SIGNAL 2: COMMERCIAL INFLECTION / RIGHTS DEALS
    "Sports broadcaster 'exclusive rights' 2025 2026 launch deadline OTT infrastructure transition",
# SIGNAL 3: ACTIVE FRICTION / TECH DEBT
    "Tier 1 streaming app 'buffering' OR 'DRM' OR 'Roku' 1-star reviews news sports 2026",
# SIGNAL 4: COMPETITIVE DISPLACEMENT
    "Media company migration from ViewLift OR 24i OR OTTera OR 3SS infrastructure 2026",
# SIGNAL 5: M&A INTEGRATION DEBT
    "Streaming company merger OR acquisition 2025 2026 'platform unification' OR 'session-sync' challenges",
]

# ---------------------------------------------------------------------------
# Google Sheet columns — ORDER MATTERS, must match SheetsClient.append_lead()
# ---------------------------------------------------------------------------
SHEET_COLUMNS: List[str] = [
    # Identity
    "Timestamp",
    "Company",
    "Domain",
    "Priority",
    "Opportunity Score",
    "Opportunity Type",
    # Research intelligence
    "Transition Gap",
    "Causal Inflection",
    "Incumbent Vendor",
    "Tech Stack",
    "App Store Rating (iOS)",
    "App Store Rating (Android)",
    # Signals
    "Top Signal",
    "Signal Source",
    "Signal Confidence",
    "Adversarial Check",
    # Power map
    "Visionary Name",
    "Visionary Title",
    "Visionary LinkedIn",
    "Visionary Hook",
    "Operator Name",
    "Operator Title",
    "Operator LinkedIn",
    "Operator Hook",
    # Outreach
    "Visionary Subject Line",
    "Visionary Email",
    "Operator Subject Line",
    "Operator Email",
    "Objection: In-House",
    "Objection: Incumbent",
    "Objection: Budget",
    # Exa LinkedIn intelligence
    "Visionary LinkedIn Quote",
    "Visionary LinkedIn Pain",
    "Operator LinkedIn Quote",
    "Operator LinkedIn Pain",
    # Apollo enrichment
    "Apollo Contact Name",
    "Apollo Contact Title",
    "Apollo Email",
    "Apollo LinkedIn",
    # Meta
    "Salesforce Note",
    "Research Gaps",
    "Query",
    "Status",
    # Discovery pipeline
    "Exa Rejected Companies",
    "Gemini Selection Reasoning",
    # BU
    "BU",
]

# ---------------------------------------------------------------------------
# Accounts worksheet columns
# ---------------------------------------------------------------------------
ACCOUNTS_COLUMNS: List[str] = [
    "Company",
    "Domain",
    "LinkedIn URL",
    "BU",
    "Tier",
    "Region",
    "Last Run",
    "Status",
]

# ---------------------------------------------------------------------------
# Signals worksheet columns
# ---------------------------------------------------------------------------
SIGNALS_COLUMNS: List[str] = [
    "Timestamp",
    "Run ID",
    "Company",
    "Domain",
    "BU",
    "Signal Type",
    "Evidence",
    "Source URL",
    "Confidence",
    "Score at Time",
    "Track",
]
