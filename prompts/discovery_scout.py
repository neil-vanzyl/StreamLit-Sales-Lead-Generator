"""
prompts/discovery_scout.py — Lightweight Grok SYSTEM prompt for discovery sweep.

Architecture:
- System prompt: aggregation-first search strategy, no static checklist
- User prompt: dynamically injects only the signal-relevant search instructions
- hq_country required for BU integrity, domain removed (Apollo resolves it)
"""

from datetime import datetime
from typing import List


# ---------------------------------------------------------------------------
# Signal → targeted search instruction map
# Covers all 31 signals across 5 groups
# ---------------------------------------------------------------------------

SIGNAL_SEARCH_INSTRUCTIONS = {

    # ── Platform & Technology ──────────────────────────────────────────────

    "Mobile-only": (
        "Search for streaming services or media companies that are currently "
        "mobile-only with no web, desktop, or CTV presence — strong candidates "
        "for platform expansion. Search: 'streaming app mobile only no CTV 2025 2026' "
        "and 'mobile video platform expanding beyond app store' and "
        "'media company mobile first CTV ambition'."
    ),
    "Youtube transition to OTT": (
        "Search for YouTube channels, YouTube-native creators, or YouTube-dependent "
        "media companies building their own owned OTT platform to reduce dependency "
        "on YouTube. Search: 'YouTube channel launches own streaming platform 2025 2026' "
        "and 'creator economy owned streaming platform' and "
        "'media brand leaving YouTube direct to consumer streaming'."
    ),
    "Web apps looking for native": (
        "Search for streaming services currently delivered as web apps or PWAs seeking "
        "native CTV applications. Search: 'streaming service web app native CTV launch "
        "2025 2026' and 'PWA to native streaming app development' and "
        "'web-based video platform native smart TV app'."
    ),
    "First CTV build": (
        "Search for companies that have never built a streaming TV app and are "
        "about to do so for the first time. Look for mobile-first or digital-only "
        "media companies announcing their first connected TV presence. "
        "Search: 'launches first streaming app Roku Apple TV 2025 2026' and "
        "'digital media company first CTV connected TV announcement'."
    ),
    "CTV ambition": (
        "Search for companies with strong mobile, social, or digital audiences "
        "that do NOT yet have a smart TV app — these are companies that should be "
        "on CTV but haven't built it yet. Look for signals of intent rather than "
        "completion. Search: 'expanding to connected TV living room 2025 2026' and "
        "'streaming service plans smart TV app launch' and 'OTT ambition CTV roadmap'."
    ),
    "Smart TV app launch": (
        "Search for companies launching or relaunching smart TV apps on Samsung "
        "Tizen, LG webOS, Vizio, or Hisense platforms specifically. "
        "Search: 'Samsung Tizen app launch 2025 2026' and 'LG webOS streaming "
        "app new' and 'Vizio streaming app launch announcement'."
    ),
    "Platform migration": (
        "Search for companies replacing or rebuilding their entire OTT streaming "
        "platform infrastructure — not a vendor switch but a ground-up rebuild. "
        "Search: 'streaming platform rebuild 2025 2026' and 'OTT infrastructure "
        "overhaul replacement' and 'streaming platform migration new architecture'."
    ),
    "Stranded vendor customer": (
        "Search specifically for companies affected by 24i bankruptcy or the "
        "ViewLift acquisition by Endeavor Streaming — these companies are actively "
        "looking for alternatives. Search: '24i bankruptcy customers streaming "
        "alternative 2024 2025' and 'ViewLift Endeavor streaming customers "
        "migration' and 'white-label OTT vendor shutdown replacement'."
    ),
    "Video player overhaul": (
        "Search for companies switching their video player, OVP, CDN, or DRM "
        "infrastructure. Search: 'OVP migration streaming 2025 2026' and 'video "
        "player replacement CDN switch streaming' and 'DRM platform migration OTT'."
    ),
    "App store complaints": (
        "Search for streaming apps with persistent user complaints about technical "
        "quality. Search app store reviews, Reddit, and Twitter: 'streaming app "
        "buffering complaints Roku Fire TV 2025' and '[vertical] streaming app "
        "DRM login broken' and 'worst streaming app complaints 2025'."
    ),
    "SSAI/DRM change": (
        "Search for companies changing their server-side ad insertion or DRM stack. "
        "Search: 'SSAI migration streaming 2025 2026' and 'DRM vendor switch OTT "
        "streaming' and 'ad insertion platform change broadcaster'."
    ),

    # ── Product & Design ──────────────────────────────────────────────────

    "App redesign": (
        "Search for companies announcing major streaming app redesigns or complete "
        "UX overhauls across platforms. Search: 'streaming app redesign 2025 2026' "
        "and 'OTT platform new interface launch' and 'streaming service UX overhaul "
        "cross-platform'."
    ),
    "Platform consolidation": (
        "Search for companies consolidating multiple streaming apps or services into "
        "one unified platform, typically post-merger. Search: 'streaming platform "
        "consolidation unified 2025 2026' and 'merger streaming apps single platform' "
        "and 'unified streaming experience post-acquisition'."
    ),
    "New product/UX leadership": (
        "Search for companies that recently appointed a new CPO, VP Product, Head "
        "of Product, VP UX, or Head of Design for their streaming/digital division. "
        "Search: 'appointed Chief Product Officer streaming media 2025' and 'new "
        "VP Product digital streaming 2025 2026' and 'hired Head of UX OTT'."
    ),
    "Rebrand with digital implications": (
        "Search for media and streaming companies undergoing rebrands that clearly "
        "imply digital platform updates — new name, new logo, new digital strategy. "
        "Search: 'streaming service rebrand new identity 2025 2026' and 'media "
        "company rebrands digital streaming pivot' and 'broadcaster new brand OTT'."
    ),

    # ── Hiring ────────────────────────────────────────────────────────────

    "Hiring: OTT/CTV engineers": (
        "Search LinkedIn Jobs, Greenhouse, and Lever for companies actively hiring "
        "OTT engineers, CTV developers, Roku channel developers, or Fire TV "
        "engineers with roles open more than 30 days. "
        "Search: site:linkedin.com/jobs 'OTT engineer' OR 'CTV developer' OR "
        "'Roku developer' OR 'streaming engineer' 2025 2026."
    ),
    "Hiring: Front-end engineers": (
        "Search for streaming companies hiring React, React Native, TypeScript, or "
        "JavaScript engineers specifically for video/streaming applications. "
        "Search: site:linkedin.com/jobs 'React Native streaming video' OR "
        "'frontend engineer OTT' OR 'TypeScript video platform' 2025."
    ),
    "Hiring: QA automation": (
        "Search for streaming companies hiring QA automation engineers with "
        "Cypress, Playwright, or Selenium for video/OTT platforms. "
        "Search: site:linkedin.com/jobs 'QA automation streaming OTT' OR "
        "'Cypress Playwright video platform' OR 'QA engineer CTV' 2025."
    ),
    "Hiring: UX/UI designers": (
        "Search for streaming companies hiring UX or product designers for "
        "connected TV or video applications. Search: site:linkedin.com/jobs "
        "'UX designer CTV streaming' OR 'product designer OTT video' OR "
        "'UI designer smart TV' 2025 2026."
    ),
    "Hiring: Product managers": (
        "Search for streaming and sports companies hiring product managers for "
        "OTT, streaming, or digital fan experience roles. "
        "Search: site:linkedin.com/jobs 'product manager streaming OTT' OR "
        "'PM connected TV' OR 'product manager sports digital fan' 2025 2026."
    ),
    "Hiring: TPMs / delivery leads": (
        "Search for streaming companies hiring Technical Program Managers or "
        "delivery leads focused on video platform delivery. "
        "Search: site:linkedin.com/jobs 'technical program manager streaming' OR "
        "'TPM OTT video platform' OR 'delivery lead streaming' 2025."
    ),

    # ── Commercial & Growth ───────────────────────────────────────────────

    "Rights without platform": (
        "Search for broadcasters, sports leagues, or content owners that recently "
        "secured exclusive streaming rights but do NOT have an established CTV "
        "platform to deliver them. The gap between rights and delivery is the "
        "opportunity. Search: 'exclusive streaming rights deal no app 2025 2026' "
        "and 'broadcast rights acquisition streaming platform needed' and "
        "'league secures streaming rights first time direct consumer'."
    ),
    "FAST/AVOD launch": (
        "Search for companies launching free ad-supported streaming channels or "
        "adding AVOD tiers to existing services. Search: 'FAST channel launch "
        "2025 2026 announcement' and 'free ad-supported streaming new channel' "
        "and 'AVOD tier launch streaming service'."
    ),
    "Funding round": (
        "Search Crunchbase and PR Newswire for Series A, B, or C funding rounds "
        "in media, streaming, or sports tech — the 12-18 months after closing is "
        "the prime window before they build in-house. "
        "Search: 'Series A streaming media funding raised 2025 2026' and "
        "'raised million OTT streaming platform investment round'."
    ),
    "Market expansion": (
        "Search for streaming services expanding into new geographic markets and "
        "needing localised CTV apps for those territories. "
        "Search: 'streaming service launches new country market 2025 2026' and "
        "'OTT platform international expansion new territory'."
    ),
    "New streaming partnership": (
        "Search for distribution partnerships, content licensing deals, or "
        "technology integrations recently announced in streaming. "
        "Search: 'streaming distribution partnership announced 2025 2026' and "
        "'OTT content deal technology integration streaming'."
    ),
    "DTC pivot": (
        "Search for traditional broadcasters or media companies pivoting away from "
        "pay TV distribution toward direct-to-consumer streaming. "
        "Search: 'broadcaster direct-to-consumer streaming pivot 2025 2026' and "
        "'cable network DTC streaming launch subscription' and 'linear TV to OTT "
        "streaming transition'."
    ),
    "M&A / platform unification": (
        "Search for acquisitions and mergers in the streaming space where the "
        "combined entity will need to unify two separate platforms. "
        "Search: 'streaming company acquisition merger 2025 2026 platform' and "
        "'media merger OTT unification integration challenge'."
    ),
    "Social-first publisher going owned OTT": (
        "Search for YouTube-native, TikTok-heavy, or social media publishers that "
        "are building or planning their own owned streaming platform to reduce "
        "dependency on social platforms. Search: 'YouTube creator launches own "
        "streaming platform 2025 2026' and 'social media publisher OTT direct' "
        "and 'digital media company leaves YouTube owned platform'."
    ),
    "Gaming company entering video": (
        "Search for gaming companies, esports organisations, or interactive "
        "entertainment companies expanding into video streaming or OTT. "
        "Search: 'gaming company launches streaming video platform 2025 2026' and "
        "'esports organisation OTT streaming service' and 'game publisher video "
        "streaming direct consumer'."
    ),
    "Post-acquisition integration": (
        "Search for companies that have recently been acquired and now need to "
        "integrate or replace streaming technology from either the acquirer or "
        "the acquired entity. Search: 'post-acquisition streaming platform "
        "integration 2025 2026' and 'acquired media company technology migration' "
        "and 'merger OTT platform consolidation'."
    ),

    # ── Risk & Distress ───────────────────────────────────────────────────

    "RFP activity": (
        "Search for companies issuing RFPs or publicly evaluating streaming "
        "technology vendors. Search: 'RFP streaming platform OTT technology "
        "2025 2026' and 'broadcaster evaluating streaming technology partners' "
        "and 'request for proposal video streaming platform'."
    ),
    "Leadership change in digital/streaming": (
        "Search for new CTO, CIO, CDO, VP Engineering, VP Digital, or Head of "
        "Streaming appointments at media, sports, or entertainment companies — "
        "new leadership almost always triggers a platform review. "
        "Search: 'new CTO media company streaming 2025' and 'appointed VP Digital "
        "broadcaster 2025 2026' and 'Head of Streaming new hire media'."
    ),
    "Competitor launched on CTV first": (
        "Search for cases where a company's direct competitor just launched on "
        "Roku, Fire TV, Apple TV, or Samsung before them — creating urgency. "
        "Search: 'competitor launches streaming app Roku 2025 2026' and "
        "'rival streaming service CTV launch ahead' and 'streaming competitor "
        "expands connected TV first'."
    ),
}


# ---------------------------------------------------------------------------
# Aggregation-first search targets — always appended
# ---------------------------------------------------------------------------

AGGREGATION_INSTRUCTIONS = """
AGGREGATION-FIRST SEARCH STRATEGY:
Do NOT search for individual company press releases one at a time.
Hunt for documents where industry experts have already compiled lists of target companies.
Run searches against:

1. Conference exhibitor/attendee lists: "IBC 2025 streaming exhibitors", "NAB Show 2025 OTT", "Sportel 2025 regional broadcaster attendees", "StreamTV Show 2025 speakers", "SVG Summit 2025 attendees"
2. Market maps and analyst reports: "2025 streaming video landscape market map", "top emerging sports OTT platforms 2025", "FAST channel market map 2025", "streaming industry report companies"
3. Industry awards shortlists: "Streaming Media Global Industry Awards nominees 2025", "SportsPro OTT Awards shortlist 2025", "CSI Awards streaming nominees", "Cynopsis Digital Awards streaming"
4. Vendor customer/case study pages: "[vendor name] customers case studies" to find companies using white-label platforms who may be migration candidates

One exhibitor list or award shortlist can yield 8-10 qualified companies instantly.
Extract every relevant company from each document you find.
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

Scan the open web for company names matching the research brief.
Use your live web search. Return ALL candidates you find — do not pre-filter.
The sales rep will review and select which companies to research deeply.

WHAT YOU ARE NOT DOING:
- Do NOT build power maps or identify contacts
- Do NOT score or qualify companies
- Do NOT research tech stacks, app ratings, or financial details
- Do NOT produce outreach or email drafts
- Do NOT pre-filter — return everything you find

{AGGREGATION_INSTRUCTIONS}

SIGNAL QUALITY — prefer but do not exclusively return:
- Companies showing clear intent to build or migrate (not just recently completed)
- Companies on stranded/distressed vendor platforms (24i, ViewLift/Endeavor)
- Active job postings open 30+ days for OTT/CTV roles
- Rights deals or funding events from the last 18 months

STRICT REQUIREMENT:
- hq_country is REQUIRED for every company — skip any company you cannot confirm HQ for
- No fabrication — every company must appear in a real source you found
- No duplicate parent/subsidiary pairs
- AIM FOR 10 COMPANIES — return all candidates, let the rep decide
- Tier 1, Tier 2, and ambitious Tier 3 are all acceptable

Return ONLY this JSON, zero preamble, zero markdown:
{{
  "companies": [
    {{
      "name": "Company Name",
      "hq_country": "Country (REQUIRED)",
      "evidence": "Specific signal, source name, approximate date",
      "signal_type": "CTV launch | rights deal | vendor migration | hiring | funding | app redesign | FAST launch | M&A | DTC pivot | platform complaint | vendor customer | first time builder | social publisher | gaming | stranded vendor | rights without platform | other",
      "source_url": "https://... or empty string"
    }}
  ],
  "search_summary": "2-3 sentences on what aggregations you searched and what patterns emerged"
}}"""


# ---------------------------------------------------------------------------
# User prompt — dynamic signal injection (max 3 instructions)
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

    injected = []
    if signals:
        for sig in signals:
            instruction = SIGNAL_SEARCH_INSTRUCTIONS.get(sig)
            if instruction and instruction not in injected:
                injected.append(instruction)

    injected = injected[:3]

    signal_block = ""
    if injected:
        signal_block = (
            "\n\nTARGETED SEARCH INSTRUCTIONS — execute ONLY these searches:\n"
            + "\n\n".join(f"{i+1}. {inst}" for i, inst in enumerate(injected))
        )

    return (
        f"RESEARCH BRIEF:\n{brief}\n\n"
        f"GEOGRAPHY: Focus on companies headquartered in {bu_context}. "
        f"hq_country is required — skip any company whose HQ you cannot confirm."
        f"{signal_block}\n\n"
        f"TARGET: Return up to {max_companies} companies. "
        f"Prioritise aggregation sources over individual press releases. "
        f"Include all candidates — the rep will filter.\n\n"
        f"Return only the JSON object."
    )