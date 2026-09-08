"""Strict routing patch for MarketOps news.

This keeps one primary topic channel per story, uses #breaking-news as an
urgency layer, and rejects common feed noise that previously leaked into AI,
Fed, crypto, and general news.
"""

from market.news_engine import NewsEngine


FED_STRONG = [
    "federal reserve", "fomc", "fed chair", "fed governor", "powell",
    "rate cut", "rate cuts", "rate hike", "rate hikes", "interest rate",
    "interest rates", "treasury yield", "treasury yields", "bond yields",
    "cpi", "pce", "ppi", "jobs report", "nonfarm payrolls", "payrolls",
    "jobless claims", "unemployment rate", "monetary policy",
]

GEO_STRONG = [
    "iran", "israel", "gaza", "hezbollah", "lebanon", "hormuz",
    "russia", "ukraine", "kyiv", "nato", "taiwan", "north korea",
    "missile", "military strike", "airstrike", "air strike", "ceasefire",
    "sanctions", "tariff", "tariffs", "trade war", "red sea", "opec",
    "brent", "wti", "crude oil", "oil supply", "oil output", "lng",
    "venezuela", "south china sea", "defense pact", "peace talks",
]

CRYPTO_STRONG = [
    "bitcoin", "btc", "ethereum", "ether", "eth", "solana", "crypto",
    "cryptocurrency", "coinbase", "stablecoin", "stablecoins", "blockchain",
    "bitcoin etf", "ethereum etf", "crypto etf", "crypto exchange",
]

AI_STRONG = [
    "artificial intelligence", "generative ai", "openai", "chatgpt",
    "large language model", "llm", "ai model", "ai models", "ai chip",
    "ai chips", "ai infrastructure", "ai data center", "ai data centre",
    "ai training", "ai inference", "machine learning", "deep learning",
    "blackwell", "h100", "groq",
]

AI_INFRA = [
    "semiconductor", "semiconductors", "gpu", "gpus", "chipmaker",
    "chipmakers", "data center", "data centers", "data centre",
    "data centres", "foundry", "wafer", "lithography", "memory chip",
    "memory chips",
]

AI_COMPANIES = [
    "nvidia", "nvda", "amd", "tsmc", "asml", "broadcom", "avgo",
    "micron", "intel", "qualcomm", "arm", "super micro", "smci",
]

GENERAL_HARD = [
    "white house", "congress", "senate", "supreme court", "president",
    "administration", "government shutdown", "national emergency",
    "cyberattack", "ransomware", "data breach", "major outage",
    "bank failure", "bankruptcy", "antitrust", "doj", "ftc", "sec",
    "fda", "recall", "investigation", "indictment", "settlement",
    "layoffs", "job cuts", "factory shutdown", "plant shutdown",
    "supply chain", "port strike", "union strike", "defense contract",
    "plane crash", "cargo plane", "ntsb", "earthquake", "hurricane",
    "wildfire", "election", "elections",
]

MARKET_WIDE = [
    "stock futures", "s&p futures", "nasdaq futures", "dow futures",
    "s&p 500", "nasdaq composite", "dow jones", "wall street",
    "market selloff", "market sell-off", "market rout", "market rally",
    "global markets", "trading halt", "halts trading", "bank failure",
]

BREAKING_SEVERE = [
    "breaking", "urgent", "emergency", "surprise rate", "unexpected rate",
    "trading halt", "halts trading", "bank failure", "default",
    "government shutdown", "major cyberattack", "ransomware attack",
    "missile attack", "military strike", "airstrike", "air strike",
    "invasion", "ceasefire", "opec", "oil supply", "sanctions",
    "tariff", "tariffs", "factory shutdown", "plant shutdown",
    "earnings warning", "cuts outlook", "bankruptcy", "deadly crash",
]

GENERIC_TITLES = {
    "archaeology", "autism", "books", "falkirk", "lincoln",
    "maintenance and repair", "latest news", "news",
}

LOCAL_NOISE = [
    "road closed after crash", "closed after crash", "stabbing",
    "pre-loved uniforms", "charity", "school year starts",
]


def _has(self, text, words):
    return self._matches_any(text, words)


def _topic_scores(self, text):
    scores = {
        "🏦 Fed / Rates": 0,
        "🛢 Oil / Geopolitics": 0,
        "🤖 AI / Tech": 0,
        "₿ Crypto": 0,
        "🗞 General News": 0,
    }

    if _has(self, text, FED_STRONG):
        scores["🏦 Fed / Rates"] += 6
    elif _has(self, text, ["inflation", "treasury", "yield", "central bank"]):
        scores["🏦 Fed / Rates"] += 2

    if _has(self, text, GEO_STRONG):
        scores["🛢 Oil / Geopolitics"] += 5
    if _has(self, text, ["war", "military", "attack", "sanctions", "tariff", "oil", "crude"]):
        scores["🛢 Oil / Geopolitics"] += 2

    if _has(self, text, CRYPTO_STRONG):
        scores["₿ Crypto"] += 7

    if _has(self, text, AI_STRONG):
        scores["🤖 AI / Tech"] += 7
    elif _has(self, text, AI_INFRA) and (_has(self, text, AI_COMPANIES) or _has(self, text, ["ai", "artificial intelligence"])):
        scores["🤖 AI / Tech"] += 6

    if _has(self, text, GENERAL_HARD):
        scores["🗞 General News"] += 3
    if _has(self, text, self.COMPANY_GENERAL_KEYWORDS) and _has(
        self,
        text,
        ["earnings", "revenue", "profit", "guidance", "layoffs", "job cuts", "recall", "lawsuit", "investigation", "contract", "acquisition", "merger", "launch"],
    ):
        scores["🗞 General News"] += 3

    return scores


def strict_detect_tags(self, text, category_hint=None):
    scores = _topic_scores(self, text)
    best_score = max(scores.values())

    if best_score <= 0:
        return []

    # Deterministic tie order: explicit specialist channels beat General.
    order = [
        "🏦 Fed / Rates",
        "🛢 Oil / Geopolitics",
        "₿ Crypto",
        "🤖 AI / Tech",
        "🗞 General News",
    ]
    primary = next(tag for tag in order if scores[tag] == best_score)
    tags = [primary]

    if strict_is_breaking_market(self, text):
        tags.append("📊 Broad Market")

    return tags


def strict_primary_tag(self, tags):
    # Broad Market is an urgency flag when a real topic exists, not a reason to
    # steal the story from its proper channel.
    for tag in [
        "🏦 Fed / Rates",
        "🛢 Oil / Geopolitics",
        "₿ Crypto",
        "🤖 AI / Tech",
        "🗞 General News",
        "🧵 Reddit Hot",
    ]:
        if tag in tags:
            return tag
    if "📊 Broad Market" in tags:
        return "📊 Broad Market"
    return tags[0]


def strict_is_breaking_market(self, text):
    if _has(self, text, MARKET_WIDE):
        return True

    severe = _has(self, text, BREAKING_SEVERE)
    consequential = (
        _has(self, text, FED_STRONG)
        or _has(self, text, GEO_STRONG)
        or _has(self, text, CRYPTO_STRONG)
        or _has(self, text, AI_STRONG)
        or _has(self, text, self.COMPANY_GENERAL_KEYWORDS)
    )
    return severe and consequential


def strict_should_ignore(self, text, source="", title=""):
    normalized_title = self._normalize_text(title)
    if normalized_title in GENERIC_TITLES:
        return True

    if self._looks_like_ticker_only(title):
        return True
    if self._low_value_finance(text, source):
        return True
    if self._sports_or_entertainment_noise(text):
        return True

    # Reject local/human-interest filler unless it has a real specialist or
    # market/company context.
    if _has(self, text, LOCAL_NOISE):
        scores = _topic_scores(self, text)
        if max(scores.values()) < 5:
            return True

    if _has(self, text, self.IRRELEVANT_KEYWORDS) and not _has(self, text, self.OVERRIDE_KEEP_KEYWORDS):
        return True

    # If none of the strict topic rules can explain why we want the story,
    # drop it instead of forcing it into General.
    if max(_topic_scores(self, text).values()) <= 0 and not strict_is_breaking_market(self, text):
        return True

    return False


def strict_get_channel_reports(self, limit_per_channel=3):
    raw_items = self._get_raw_items(limit=220, category="all")
    classified_items = self._classify_items(raw_items)
    classified_items = [item for item in classified_items if self._is_fresh(item)]
    classified_items.sort(key=lambda item: item["importance_score"], reverse=True)

    reports = {channel: [] for channel in self.CHANNEL_ORDER}
    seen_by_channel = {channel: set() for channel in self.CHANNEL_ORDER}

    def add(channel, item):
        if channel not in reports or len(reports[channel]) >= limit_per_channel:
            return
        key = self._clean_title_key(item.get("title", "")) or item.get("link", "")
        if not key or key in seen_by_channel[channel]:
            return
        reports[channel].append(item)
        seen_by_channel[channel].add(key)

    for item in classified_items:
        add(item["channel"], item)

        # Breaking is a second layer only for truly urgent stories. The story
        # still remains in its correct topical channel.
        if "📊 Broad Market" in item.get("tags", []) and item["channel"] != "breaking-news":
            add("breaking-news", item)

    return {
        "channels": reports,
        "counts": {channel: len(items) for channel, items in reports.items()},
        "updated": self._timestamp(),
        "source_policy": self.source_policy(),
        "freshness_policy": self.freshness_policy(),
        "provider_used": self.last_provider_used,
    }


def apply_news_routing_patch():
    NewsEngine._detect_tags = strict_detect_tags
    NewsEngine._primary_tag = strict_primary_tag
    NewsEngine._is_breaking_market = strict_is_breaking_market
    NewsEngine._should_ignore = strict_should_ignore
    NewsEngine.get_channel_reports = strict_get_channel_reports
