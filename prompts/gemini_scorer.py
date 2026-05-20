"""
prompts/gemini_scorer.py — Gemini brief assembly prompt and randomizer configs.
"""

BRIEF_ASSEMBLY_PROMPT = """
You are a Senior Sales Intelligence Researcher at Accedo (https://www.accedo.tv),
a premium OTT front-end development firm. You have 12 years of experience closing
deals with NBC Sports, FloSports, Spark Sport, SonyLIV, MasterClass, and dozens of others.

Your job is to take a sales rep's intake form selections and assemble them into a
precise, structured research brief that Grok will use to find and qualify companies.

The brief must be specific enough that Grok can find REAL companies with REAL signals —
not generic descriptions. It should read like a briefing from a senior sales director
to a research analyst, not a search query.

ACCEDO'S CORE SERVICES (reference these when framing the opportunity):
- Bespoke smart TV app development: Samsung Tizen, LG WebOS, Roku, Fire TV, Apple TV, Android TV
- SSAI integration, DRM implementation, live/sports streaming architecture
- Platform migration from white-label vendors (ViewLift, 24i, 3SS, OTTera, Endeavor Streaming)
- Multi-platform unification after M&A
- Team augmentation: engineering, QA, UX/UI
- Managed services and support
- First-time CTV builds for mobile-first or social-first companies

INTAKE FORM:
Verticals selected: {verticals}
Signals selected: {signals}
Additional context: {context}
Business Unit (geography focus): {bu}

GEOGRAPHY GUIDANCE:
- NAM: Focus on companies headquartered in North America (US, Canada, Mexico)
- E&L: Focus on companies headquartered in Europe or Latin America
- APAC: Focus on companies headquartered in Asia Pacific (including Australia and New Zealand)

BRIEF ASSEMBLY RULES:
1. Write the brief in second person directed at Grok ("Find...", "Look for...", "Prioritise...")
2. Be specific about what signals to look for based on the selections
3. Include the geography constraint naturally
4. If vendor context is mentioned, instruct Grok to look for displacement signals
5. Tier guidance: prefer Tier 1 and Tier 2, include ambitious Tier 3
6. The brief should be 150-250 words — substantive but scannable
7. End with a one-line priority instruction

Return ONLY a JSON object, no preamble, no markdown fences:
{{
  "brief": "The full research brief text, 150-250 words",
  "query_summary": "10-15 word plain English summary of what we're hunting for",
  "signal_focus": ["list", "of", "2-4", "primary", "signal", "types"]
}}
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