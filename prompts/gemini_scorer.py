"""
prompts/gemini_scorer.py — Gemini brief assembly prompt and randomizer configs.
"""

BRIEF_ENRICHMENT_PROMPT = """
You are a senior sales intelligence researcher at Accedo, an OTT front-end development firm.

A sales rep has selected verticals and signals from a form. Your job is to enrich their
auto-built brief with three specific improvements — nothing more:

1. VERTICAL EXPANSION: Replace generic vertical names with specific industry terminology,
   company types, and examples that Grok can actually search for.
   Examples:
   - "Faith" → "Faith-based and Christian media organisations, ministry streamers, CCM networks, prayer apps, religious broadcasters (e.g., NRB members)"
   - "Audio" → "Podcast networks, digital radio operators, audio streaming platforms, music streaming services expanding to video"
   - "Sports" → "Regional sports networks (RSNs), sports leagues, broadcast rights holders, sports streaming services"
   - "News" → "Digital news publishers, local broadcasters, news networks, OTT news services"
   - "Entertainment" → "SVOD/AVOD streaming services, studio-owned platforms, entertainment networks"
   - "Fitness" → "Digital fitness platforms, health and wellness streaming services, exercise video brands"
   - "Education" → "EdTech video platforms, e-learning streaming services, educational content providers"
   - "Gaming" → "Esports organisations, game publishers, interactive entertainment companies"
   - "In-Vehicle" → "Automotive entertainment providers, in-vehicle infotainment companies"
   - "Pay TV" → "Cable operators, telco TV providers, pay TV platform operators"
   - "Multi-Vertical" → "Multi-genre streaming services, media conglomerates with multiple content verticals"
   - "Micro-drama" → "Short-form episodic video platforms, vertical video drama series, mobile-first narrative content apps (e.g., ReelShort, DramaBox)"
   - "FAST" → "Free ad-supported streaming TV channels, FAST channel operators, linear streaming platforms, AVOD networks"

2. SIGNAL GROUPING: Group the selected signals into 2-3 thematic buckets with a one-line
   description per bucket. Use the format from the example below. Do NOT list every signal
   individually — group related ones together with industry context.

3. AGGREGATION HINT: One sentence pointing Grok at the single most relevant industry
   aggregation source for these verticals (conference, award, market report, association).

SELECTED VERTICALS: {verticals}
SELECTED SIGNALS: {signals}
GEOGRAPHY: {bu_label}
AUTO-BUILT BRIEF: {auto_brief}

Return your response on a SINGLE LINE in this exact format, with || separating each section:
VERTICAL: [description] || SIGNALS: [groups] || AGGREGATION: [hint]

Here is an example of a correct single-line response:
VERTICAL: Regional sports networks (RSNs), professional sports leagues, sports streaming services || SIGNALS: Platform Modernization: Companies replacing white-label vendor infrastructure | Talent Investment: Active hiring of OTT engineers || AGGREGATION: Search Sports Video Group (SVG) member directory and SportsPro OTT Awards shortlists.

Your response must be a single line like the example above. Do not use newlines.
"""

# ---------------------------------------------------------------------------
# Randomizer configurations
# ---------------------------------------------------------------------------

RANDOM_CONFIGS = [
    {
        "verticals": ["Sports"],
        "signals": ["Rights without platform", "First CTV build", "Hiring: OTT/CTV engineers"],
        "context": "Regional sports networks that recently secured new broadcast rights and need to launch a CTV experience before the season starts",
    },
    {
        "verticals": ["News"],
        "signals": ["CTV ambition", "Hiring: Product managers", "Platform consolidation"],
        "context": "Digital-first news publishers with strong mobile audiences that have not yet built a connected TV presence",
    },
    {
        "verticals": ["Sports", "Entertainment"],
        "signals": ["Stranded vendor customer", "App store complaints", "Hiring: OTT/CTV engineers"],
        "context": "Broadcasters on 24i or ViewLift/Endeavor platforms showing frustration — slow releases, poor OEM support, platform uncertainty",
    },
    {
        "verticals": ["Entertainment"],
        "signals": ["FAST/AVOD launch", "Funding round", "First CTV build"],
        "context": "Streaming services that recently closed a funding round and are launching or expanding FAST channels to new platforms",
    },
    {
        "verticals": ["Faith"],
        "signals": ["First CTV build", "App redesign", "Hiring: UX/UI designers"],
        "context": "Faith-based media organisations with loyal mobile audiences evaluating their first bespoke smart TV app",
    },
    {
        "verticals": ["Sports"],
        "signals": ["M&A / platform unification", "Post-acquisition integration", "Hiring: TPMs / delivery leads"],
        "context": "Sports media companies that have gone through an acquisition and are now running two separate streaming platforms that need unification",
    },
    {
        "verticals": ["Education"],
        "signals": ["CTV ambition", "Funding round", "Hiring: Front-end engineers"],
        "context": "EdTech video platforms that closed Series B or later and are expanding from mobile to connected TV devices",
    },
    {
        "verticals": ["Fitness"],
        "signals": ["App redesign", "CTV ambition", "Hiring: OTT/CTV engineers"],
        "context": "Fitness streaming services with strong mobile subscriptions that need to improve or rebuild their smart TV experience",
    },
    {
        "verticals": ["Multi-Vertical"],
        "signals": ["DTC pivot", "Leadership change in digital/streaming", "Hiring: Product managers"],
        "context": "Traditional media companies announcing a direct-to-consumer streaming pivot with new digital leadership in place",
    },
    {
        "verticals": ["News", "Sports"],
        "signals": ["Rights without platform", "Market expansion", "First CTV build"],
        "context": "News or sports broadcasters expanding into new territories and needing CTV apps for markets where they have no existing platform",
    },
    {
        "verticals": ["Audio"],
        "signals": ["CTV ambition", "First CTV build", "Funding round"],
        "context": "Audio-first platforms (podcasts, music, radio) that are adding video content and need their first CTV application",
    },
    {
        "verticals": ["Pay TV"],
        "signals": ["Stranded vendor customer", "Platform migration", "App store complaints"],
        "context": "Pay TV operators whose legacy middleware or white-label OTT stack is showing its age — poor app ratings, slow feature delivery",
    },
    {
        "verticals": ["Sports"],
        "signals": ["Hiring: OTT/CTV engineers", "Hiring: QA automation", "App store complaints"],
        "context": "Sports streaming services with consistently poor app store ratings for Roku or Fire TV — buffering, DRM, or login issues cited in reviews",
    },
    {
        "verticals": ["Entertainment", "Faith"],
        "signals": ["FAST/AVOD launch", "First CTV build", "SSAI/DRM change"],
        "context": "SVOD services pivoting to add a free ad-supported tier and needing SSAI integration across their smart TV apps",
    },
    {
        "verticals": ["In-Vehicle"],
        "signals": ["First CTV build", "Funding round", "Hiring: Front-end engineers"],
        "context": "Auto or in-vehicle entertainment companies building video streaming experiences for next-generation vehicle platforms",
    },
    {
        "verticals": ["Entertainment", "Sports"],
        "signals": ["Social-first publisher going owned OTT", "CTV ambition", "DTC pivot"],
        "context": "YouTube-native or social-first sports and entertainment publishers building their first owned streaming platform",
    },
    {
        "verticals": ["Sports"],
        "signals": ["Competitor launched on CTV first", "CTV ambition", "Rights without platform"],
        "context": "Regional sports networks whose closest competitor just launched on Roku or Apple TV — urgency signal for Accedo outreach",
    },
    {
        "verticals": ["Entertainment"],
        "signals": ["Gaming company entering video", "First CTV build", "Hiring: OTT/CTV engineers"],
        "context": "Gaming companies or esports organisations expanding into video streaming and needing their first OTT platform",
    },
]