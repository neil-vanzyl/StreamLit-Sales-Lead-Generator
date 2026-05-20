"""
prompts/discovery_scout.py — Lightweight Grok SYSTEM prompt for discovery sweep.

Architecture:
- System prompt: aggregation-first search strategy, no static checklist
- User prompt: dynamically injects only the signal-relevant search instructions
- Domain removed from schema (Apollo resolves it during deep research)
- hq_country kept as strict requirement for BU integrity
"""

from datetime import datetime
from typing import List


# ---------------------------------------------------------------------------
# Signal → targeted search instruction map
# Only the instructions matching selected signals are injected.
# ---------------------------------------------------------------------------

SIGNAL_SEARCH_INSTRUCTIONS = {
    # OTT / CTV signals
    "First CTV build": (
        "Search for companies with strong mobile or social audiences that have "
        "publicly announced plans to launch on Roku, Fire TV, Apple TV, or Samsung Tizen "
        "for the first time. Search: 'first connected TV app launch 2025 2026' and "
        "'expanding from mobile to living room streaming'."
    ),
    "CTV expansion": (
        "Search for companies announcing expansion to additional CTV platforms or new "
        "territories. Search: 'streaming service new platform launch 2025 2026' and "
        "'OTT app expansion connected TV'."
    ),
    "Smart TV app launch": (
        "Search for companies launching or relaunching smart TV applications on Samsung "
        "Tizen, LG webOS, Vizio, or Hisense. Search: 'smart TV app launch 2025 2026' "
        "and 'Samsung Tizen LG webOS streaming app announcement'."
    ),
    "Platform migration": (
        "Search for companies migrating streaming platforms or replacing their OTT "
        "infrastructure. Search: 'streaming platform migration 2025 2026' and "
        "'OTT infrastructure overhaul rebuild'."
    ),
    "Vendor migration": (
        "Search specifically for companies currently running on or departing from "
        "white-label vendors: ViewLift, 24i, 3SS, OTTera, Endeavor Streaming. "
        "Search: 'ViewLift customer migration alternative' and '24i OTT platform "
        "replacement 2025 2026' and 'streaming platform vendor switch'."
    ),
    "Video player overhaul": (
        "Search for companies replacing their video player, switching OVP, or "
        "migrating CDN or DRM infrastructure. Search: 'video player migration OVP "
        "switch 2025' and 'streaming CDN DRM infrastructure overhaul'."
    ),
    "App store complaints": (
        "Search for streaming apps with persistent quality issues. Search app store "
        "reviews and complaints: 'streaming app buffering Roku Fire TV 1 star 2025' "
        "and '[vertical] streaming app DRM login issues complaints'."
    ),
    "RFP activity": (
        "Search for companies issuing RFPs or actively evaluating streaming technology "
        "vendors. Search: 'RFP streaming platform OTT 2025 2026' and 'broadcaster "
        "evaluating streaming technology partners'."
    ),
    "SSAI/DRM change": (
        "Search for companies changing their ad insertion, SSAI, or DRM stack. "
        "Search: 'SSAI migration streaming 2025' and 'DRM platform switch OTT'."
    ),
    # Product / UX signals
    "App redesign": (
        "Search for companies announcing major app redesigns or UX overhauls. "
        "Search: 'streaming app redesign 2025 2026' and 'OTT platform UX overhaul "
        "new interface launch'."
    ),
    "Rebrand": (
        "Search for media and streaming companies undergoing rebrands that imply "
        "digital platform updates. Search: 'streaming service rebrand 2025 2026' "
        "and 'media company new brand identity digital'."
    ),
    "Platform consolidation": (
        "Search for companies consolidating multiple streaming services or apps into "
        "one unified platform. Search: 'streaming platform consolidation unified app "
        "2025 2026' and 'merger streaming service single platform'."
    ),
    "Leadership change": (
        "Search for new CTO, CPO, VP Engineering, VP Digital, or Head of Streaming "
        "appointments at media and sports companies. Search: 'appointed CTO streaming "
        "media 2025' and 'new VP digital sports broadcaster 2025 2026'."
    ),
    "New product/UX leadership": (
        "Search for companies hiring or recently appointing product and design "
        "leadership for streaming. Search: 'hired Chief Product Officer streaming "
        "2025' and 'new Head of Product OTT media company'."
    ),
    # Hiring signals
    "Hiring: OTT/CTV engineers": (
        "Search LinkedIn Jobs, Greenhouse, and Lever for companies actively hiring "
        "OTT engineers, CTV developers, Roku developers, or Fire TV engineers. "
        "Search: site:linkedin.com/jobs 'OTT engineer' OR 'CTV developer' OR "
        "'Roku developer' streaming 2025 2026."
    ),
    "Hiring: Front-end engineers": (
        "Search for streaming companies hiring React, React Native, or TypeScript "
        "engineers for video applications. Search: site:linkedin.com/jobs "
        "'React Native streaming' OR 'frontend engineer OTT' OR 'TypeScript video'."
    ),
    "Hiring: QA automation": (
        "Search for streaming companies hiring QA automation engineers with Cypress, "
        "Playwright, or Selenium experience. Search: site:linkedin.com/jobs "
        "'QA automation streaming' OR 'Cypress Playwright OTT' 2025 2026."
    ),
    "Hiring: UX/UI designers": (
        "Search for streaming companies hiring UX or UI designers for CTV or mobile "
        "video applications. Search: site:linkedin.com/jobs 'UX designer CTV' OR "
        "'UI designer streaming' OR 'product designer OTT' 2025."
    ),
    "Hiring: Product managers": (
        "Search for streaming companies hiring product managers for OTT, streaming, "
        "or sports fan experience. Search: site:linkedin.com/jobs 'product manager "
        "streaming' OR 'PM OTT' OR 'product manager sports digital' 2025 2026."
    ),
    "Hiring: TPMs": (
        "Search for streaming companies hiring Technical Program Managers focused on "
        "video or platform delivery. Search: site:linkedin.com/jobs 'technical program "
        "manager streaming' OR 'TPM OTT video platform' 2025."
    ),
    # Commercial signals
    "Rights deal": (
        "Search for broadcasters and streaming services securing new exclusive content "
        "or sports rights that require platform expansion. Search: 'exclusive streaming "
        "rights deal 2025 2026' and 'broadcast rights OTT platform launch deadline'."
    ),
    "FAST/AVOD launch": (
        "Search for companies launching free ad-supported streaming channels or adding "
        "AVOD tiers. Search: 'FAST channel launch 2025 2026' and 'AVOD tier free "
        "ad-supported streaming new'."
    ),
    "Funding round": (
        "Search Crunchbase and PR Newswire for Series A, B, or C funding rounds in "
        "media, streaming, or sports tech over the last 18 months. Search: "
        "'Series A streaming media funding 2025' and 'raised million streaming "
        "platform OTT investment'."
    ),
    "Market expansion": (
        "Search for streaming services expanding into new geographic markets or "
        "launching in new territories. Search: 'streaming service launches in 2025 "
        "2026 new market' and 'OTT platform international expansion'."
    ),
    "New streaming partnership": (
        "Search for distribution partnerships, content deals, or technology "
        "integrations announced in streaming. Search: 'streaming partnership "
        "announced 2025 2026' and 'OTT distribution deal content agreement'."
    ),
    "DTC pivot": (
        "Search for media companies pivoting to direct-to-consumer streaming models. "
        "Search: 'direct-to-consumer streaming pivot 2025 2026' and 'broadcaster "
        "DTC streaming launch subscription'."
    ),
    "M&A / platform unification": (
        "Search for acquisitions and mergers in the streaming space requiring platform "
        "integration. Search: 'streaming company acquisition merger 2025 2026' and "
        "'OTT platform unification post-merger integration'."
    ),
}

# Aggregation-first search targets — always appended regardless of signals
AGGREGATION_INSTRUCTIONS = """
AGGREGATION-FIRST SEARCH STRATEGY:
Do NOT search for individual company press releases one at a time.
Instead, hunt for documents where industry experts have already compiled lists of relevant companies.
Run searches against:

1. Conference exhibitor/attendee lists: "IBC 2025 streaming exhibitors", "NAB Show 2025 OTT", "Sportel regional broadcaster attendees", "StreamTV Show 2025 speakers"
2. Market maps and analyst reports: "2025 streaming video landscape market map", "top emerging sports OTT platforms", "FAST channel market map 2025"
3. Industry awards shortlists: "Streaming Media Global Industry Awards nominees 2025", "SportsPro OTT Awards shortlist", "CSI Awards streaming nominees"
4. Vendor customer lists: search for "[vendor name] customers" or "[vendor name] case studies" to find companies using white-label platforms

One exhibitor list or award shortlist can yield 8-10 qualified companies instantly.
Extract every relevant company name from each document you find.
"""


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def build_discovery_system_prompt() -> str:
    today = datetime.now().strftime("%B %d, %Y")
    return f"""Today's date: {today}

You are a B2B sales intelligence researcher for Accedo (https://www.accedo.tv),
a premium OTT front-end development firm.

YOUR ONLY JOB IS DISCOVERY — not deep research.

Scan the open web for company names that match the research brief.
Use your live web search. Return ALL candidates you find — do not pre-filter.
The sales rep will review and select which companies to research deeply.

WHAT YOU ARE NOT DOING:
- Do NOT build power maps or identify contacts
- Do NOT score companies or produce opportunity assessments
- Do NOT research tech stacks, app ratings, or financial details
- Do NOT produce outreach or email drafts
- Do NOT pre-filter results — return everything you find

{AGGREGATION_INSTRUCTIONS}

SIGNAL QUALITY:
PREFER signals that indicate transition readiness:
- Companies on white-label vendors (ViewLift, 24i, 3SS, OTTera) for 2+ years
- Active job postings for OTT/CTV engineering roles open >30 days
- Leadership changes in digital/streaming (new exec = platform review)
- Rights expansions that likely exceed current vendor capabilities
- M&A activity requiring platform unification

STILL INCLUDE (note in evidence):
- Companies that just launched on a vendor in the last 6 months
- Tier 3 companies if the signal is exceptionally strong

QUALITY RULES:
- Every company must be real and named in an actual source you found
- Evidence must include the source name and approximate date
- hq_country is REQUIRED for every company — do not return a company without it
- No duplicate parent/subsidiary pairs
- AIM FOR 10 COMPANIES — return all candidates, let the rep decide
- Never fabricate companies or evidence

Return ONLY this exact JSON, zero preamble, zero markdown:
{{
  "companies": [
    {{
      "name": "Company Name",
      "hq_country": "Country (REQUIRED)",
      "evidence": "Specific signal found, source name, and approximate date",
      "signal_type": "CTV launch | rights deal | vendor migration | hiring | funding | app redesign | FAST launch | M&A | DTC pivot | platform complaint | vendor customer | first time builder | other",
      "source_url": "https://... or empty string"
    }}
  ],
  "search_summary": "2-3 sentences: what aggregations you searched, what patterns emerged"
}}"""


# ---------------------------------------------------------------------------
# User prompt — dynamic signal injection
# ---------------------------------------------------------------------------

def build_discovery_user_prompt(
    brief: str,
    bu: str = "",
    signals: List[str] = None,
    max_companies: int = 10,
) -> str:
    bu_context = {
        "NAM":  "North America (US, Canada, Mexico)",
        "E&L":  "Europe or Latin America",
        "APAC": "Asia Pacific (including Australia and New Zealand)",
    }.get(bu, "any region")

    # Dynamically inject only the search instructions matching selected signals
    injected = []
    if signals:
        for sig in signals:
            instruction = SIGNAL_SEARCH_INSTRUCTIONS.get(sig)
            if instruction and instruction not in injected:
                injected.append(instruction)

    # Cap at 3 instructions to keep focus sharp
    injected = injected[:3]

    signal_block = ""
    if injected:
        signal_block = (
            "\n\nTARGETED SEARCH INSTRUCTIONS — execute ONLY these searches "
            "(matched to the signals selected by the rep):\n"
            + "\n\n".join(f"{i+1}. {inst}" for i, inst in enumerate(injected))
        )

    return (
        f"RESEARCH BRIEF:\n{brief}\n\n"
        f"GEOGRAPHY: Focus on companies headquartered in {bu_context}. "
        f"hq_country is required for every result — skip any company whose "
        f"headquarters you cannot confirm."
        f"{signal_block}\n\n"
        f"TARGET: Return up to {max_companies} companies. "
        f"Prioritise aggregation sources (conference lists, award shortlists, "
        f"market maps) over individual press releases. "
        f"Include all candidates — the rep will filter.\n\n"
        f"Return only the JSON object."
    )