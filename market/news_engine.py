import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from providers.finlight_provider import FinlightProvider
from providers.marketaux_provider import MarketauxProvider
from providers.rss_provider import RSSProvider


class NewsEngine:
    """Turns trusted headlines into MarketOps news cards.

    Provider job: fetch and verify headlines.
    Engine job: reject unrelated headlines, classify the remaining headlines,
    explain why they matter, and route them to the correct Discord channel.
    """

    AI_TECH_KEYWORDS = [
        "ai",
        "artificial intelligence",
        "nvidia",
        "nvda",
        "amd",
        "semiconductor",
        "semiconductors",
        "chip",
        "chips",
        "data center",
        "data centers",
        "microsoft",
        "amazon",
        "apple",
        "openai",
        "google",
        "meta",
    ]

    FED_RATES_KEYWORDS = [
        "fed",
        "federal reserve",
        "powell",
        "rate hike",
        "rate cut",
        "rates",
        "yield",
        "yields",
        "treasury",
        "treasuries",
        "inflation",
        "cpi",
        "ppi",
        "jobs report",
        "payroll",
        "payrolls",
        "gdp",
    ]

    GEO_STRONG_KEYWORDS = [
        "oil",
        "crude",
        "brent",
        "wti",
        "opec",
        "iran",
        "israel",
        "gaza",
        "west bank",
        "netanyahu",
        "hezbollah",
        "lebanon",
        "hormuz",
        "middle east",
        "russia",
        "ukraine",
        "kyiv",
        "taiwan",
        "north korea",
        "nato",
        "war",
        "sanctions",
        "missile",
        "attack",
        "ceasefire",
    ]

    CHINA_CONTEXT_KEYWORDS = [
        "tariff",
        "tariffs",
        "trade",
        "exports",
        "export controls",
        "sanctions",
        "taiwan",
        "military",
        "economy",
        "economic",
        "markets",
        "stocks",
        "shares",
        "chips",
        "semiconductor",
    ]

    CRYPTO_KEYWORDS = [
        "bitcoin",
        "btc",
        "crypto",
        "cryptocurrency",
        "ethereum",
        "ether",
        "coinbase",
        "spot bitcoin etf",
        "bitcoin etf",
        "ethereum etf",
        "ether etf",
        "crypto etf",
    ]

    BROAD_MARKET_KEYWORDS = [
        "stocks",
        "shares",
        "wall street",
        "s&p",
        "s&p 500",
        "nasdaq",
        "dow",
        "futures",
        "global markets",
        "investors",
        "markets",
        "market wrap",
    ]

    GENERAL_NEWS_KEYWORDS = [
        "white house",
        "congress",
        "senate",
        "house votes",
        "supreme court",
        "court",
        "judge",
        "lawsuit",
        "president",
        "administration",
        "government shutdown",
        "national emergency",
        "cyberattack",
        "cyber attack",
        "data breach",
        "election",
        "vote",
        "immigration",
        "border",
        "protest",
        "strike",
        "hurricane",
        "wildfire",
        "earthquake",
        "public health",
        "fema",
        "national guard",
    ]

    KEYWORDS = {
        "🤖 AI / Tech": AI_TECH_KEYWORDS,
        "🏦 Fed / Rates": FED_RATES_KEYWORDS,
        "🛢 Oil / Geopolitics": GEO_STRONG_KEYWORDS,
        "₿ Crypto": CRYPTO_KEYWORDS,
        "📊 Broad Market": BROAD_MARKET_KEYWORDS,
        "🗞 General News": GENERAL_NEWS_KEYWORDS,
    }

    IRRELEVANT_KEYWORDS = [
        "world cup",
        "soccer",
        "football",
        "basketball",
        "baseball",
        "tennis",
        "golf",
        "cricket",
        "rugby",
        "fifa",
        "uefa",
        "nba",
        "nfl",
        "mlb",
        "nhl",
        "olympics",
        "olympic",
        "tournament",
        "match",
        "movie",
        "film",
        "celebrity",
        "music",
        "fashion",
        "recipe",
    ]

    OVERRIDE_KEEP_KEYWORDS = [
        "stocks",
        "shares",
        "market",
        "markets",
        "futures",
        "oil",
        "crude",
        "fed",
        "inflation",
        "rate",
        "rates",
        "yield",
        "treasury",
        "war",
        "attack",
        "sanctions",
        "tariff",
        "ceasefire",
        "missile",
        "cyberattack",
        "cyber attack",
    ]

    CATEGORY_ALIASES = {
        "all": None,
        "market": "📊 Broad Market",
        "markets": "📊 Broad Market",
        "broad": "📊 Broad Market",
        "breaking": "📊 Broad Market",
        "ai": "🤖 AI / Tech",
        "tech": "🤖 AI / Tech",
        "fed": "🏦 Fed / Rates",
        "rates": "🏦 Fed / Rates",
        "calendar": "🏦 Fed / Rates",
        "geo": "🛢 Oil / Geopolitics",
        "geopolitics": "🛢 Oil / Geopolitics",
        "oil": "🛢 Oil / Geopolitics",
        "crypto": "₿ Crypto",
        "bitcoin": "₿ Crypto",
        "general": "🗞 General News",
        "national": "🗞 General News",
        "nationwide": "🗞 General News",
        "world": "🗞 General News",
    }

    CHANNEL_MAP = {
        "🤖 AI / Tech": "ai-news",
        "🏦 Fed / Rates": "fed",
        "🛢 Oil / Geopolitics": "geopolitics",
        "₿ Crypto": "crypto",
        "📊 Broad Market": "breaking-news",
        "🗞 General News": "general-news",
    }

    CHANNEL_ORDER = [
        "breaking-news",
        "general-news",
        "ai-news",
        "fed",
        "geopolitics",
        "crypto",
    ]

    TAG_PRIORITY = [
        "🏦 Fed / Rates",
        "🛢 Oil / Geopolitics",
        "🤖 AI / Tech",
        "₿ Crypto",
        "📊 Broad Market",
        "🗞 General News",
    ]

    def __init__(self):
        self.marketaux_provider = MarketauxProvider()
        self.finlight_provider = FinlightProvider()
        self.rss_provider = RSSProvider()
        self.fallback_to_rss = self._env_bool("NEWS_FALLBACK_RSS", default=True)
        self.use_finlight = self._env_bool("NEWS_USE_FINLIGHT", default=False)
        self.max_age_hours = float(os.getenv("NEWS_MAX_AGE_HOURS", "0.25"))
        self.last_provider_used = "Not checked yet"

    def get_top_news(self, limit=5, category="all"):
        raw_items = self._get_raw_items(limit=50)
        classified_items = self._classify_items(raw_items)
        classified_items = [item for item in classified_items if self._is_fresh(item)]

        tag_filter = self._resolve_category(category)
        if tag_filter is not None:
            classified_items = [item for item in classified_items if tag_filter in item["tags"]]

        classified_items.sort(key=lambda item: item["importance_score"], reverse=True)

        return {
            "items": classified_items[:limit],
            "category": category or "all",
            "tag_filter": tag_filter,
            "updated": self._timestamp(),
            "source_policy": self.source_policy(),
            "freshness_policy": self.freshness_policy(),
            "provider_used": self.last_provider_used,
        }

    def get_channel_reports(self, limit_per_channel=3):
        raw_items = self._get_raw_items(limit=75)
        classified_items = self._classify_items(raw_items)
        classified_items = [item for item in classified_items if self._is_fresh(item)]
        classified_items.sort(key=lambda item: item["importance_score"], reverse=True)

        reports = {channel: [] for channel in self.CHANNEL_ORDER}

        for item in classified_items:
            channel = item["channel"]
            if len(reports[channel]) < limit_per_channel:
                reports[channel].append(item)

        return {
            "channels": reports,
            "counts": {channel: len(items) for channel, items in reports.items()},
            "updated": self._timestamp(),
            "source_policy": self.source_policy(),
            "freshness_policy": self.freshness_policy(),
            "provider_used": self.last_provider_used,
        }

    def channel_map_text(self):
        lines = []
        for tag, channel in self.CHANNEL_MAP.items():
            lines.append(f"• {tag} → `#{channel}`")
        return "\n".join(lines)

    def source_policy(self):
        if self.marketaux_provider.enabled:
            return (
                "Marketaux mode is ON. MarketOps checks Marketaux first for free market-news API coverage. "
                "Reuters-focused RSS remains available as the backup when NEWS_FALLBACK_RSS=true."
            )

        if self.use_finlight and self.finlight_provider.enabled:
            return (
                "Finlight mode is ON. MarketOps checks Finlight REST for fresher trusted financial news. "
                "If Finlight returns nothing and NEWS_FALLBACK_RSS=true, it falls back to Reuters-focused RSS."
            )

        return (
            "Marketaux is OFF because MARKETAUX_API_KEY is missing. "
            "MarketOps is using Reuters-focused RSS fallback."
        )

    def freshness_policy(self):
        max_minutes = round(self.max_age_hours * 60)
        if max_minutes < 60:
            return f"MarketOps shows trusted headlines published within the last {max_minutes} minutes."
        return f"MarketOps shows trusted headlines published within the last {self.max_age_hours:g} hour(s)."

    def category_help(self):
        return (
            "Use one of these:\n"
            "• `!news` — all trusted MarketOps news\n"
            "• `!news market` — market-moving / broad market\n"
            "• `!news general` — important national/world news, not directly market-related\n"
            "• `!news ai` — AI / tech\n"
            "• `!news fed` — Fed / rates / inflation\n"
            "• `!news geo` — oil / geopolitics\n"
            "• `!news crypto` — bitcoin / crypto\n"
            "• `!news channels` — show channel routing\n"
            "• `!news sources` — show trusted-source policy\n"
            "• `!news debug` — show how many fresh headlines each channel found\n"
            "• `!news post` — post fresh headlines into the matching channels"
        )

    def _get_raw_items(self, limit):
        items = []
        providers_used = []

        if self.marketaux_provider.enabled:
            marketaux_items = self.marketaux_provider.get_latest_news(limit=limit)
            if marketaux_items:
                items.extend(marketaux_items)
                providers_used.append("Marketaux")

        if self.use_finlight and self.finlight_provider.enabled:
            finlight_items = self.finlight_provider.get_latest_news(limit=limit)
            if finlight_items:
                items.extend(finlight_items)
                providers_used.append("Finlight REST")

        if self.fallback_to_rss:
            rss_items = self.rss_provider.get_latest_news(limit=limit)
            if rss_items:
                items.extend(rss_items)
                providers_used.append("Reuters RSS fallback")

        if not items and not providers_used:
            providers_used.append("No provider returned articles")

        self.last_provider_used = " + ".join(providers_used)
        return self._deduplicate_items(items)[:limit]

    def _deduplicate_items(self, items):
        seen = set()
        unique = []

        for item in items:
            title = self._normalize_text(item.get("title", ""))
            link = item.get("link", "")
            key = link or title

            if key in seen:
                continue

            seen.add(key)
            unique.append(item)

        return unique

    def _classify_items(self, raw_items):
        classified = []
        for item in raw_items:
            result = self._classify(item)
            if result is not None:
                classified.append(result)
        return classified

    def _classify(self, item):
        title = item.get("title", "Untitled")
        title_text = self._normalize_text(title)

        if self._should_ignore(title_text):
            return None

        tags = self._detect_tags(title_text)

        if not tags:
            return None

        primary_tag = self._primary_tag(tags)
        channel = self.CHANNEL_MAP[primary_tag]

        source = item.get("source", "")
        provider = item.get("provider", "RSS")
        score = len(tags) + 1

        if provider in ("Marketaux", "Finlight"):
            score += 1
        if "reuters" in source.lower():
            score += 1

        published_dt = item.get("published_dt")
        importance = self._importance(score)

        return {
            "source": source or provider or "Unknown",
            "title": title,
            "link": item.get("link", ""),
            "summary": item.get("summary", ""),
            "published": item.get("published", ""),
            "published_dt": published_dt,
            "published_label": self._published_label(published_dt),
            "age_label": self._age_label(published_dt),
            "age_minutes": self._age_minutes(published_dt),
            "tags": tags,
            "primary_tag": primary_tag,
            "channel": channel,
            "importance": importance,
            "importance_score": score,
            "why_it_matters": self._why_it_matters(tags),
            "watch": self._watch(tags),
            "trusted": item.get("trusted", False),
            "provider": provider,
        }

    def _detect_tags(self, title_text):
        tags = []

        if self._matches_any(title_text, self.FED_RATES_KEYWORDS):
            tags.append("🏦 Fed / Rates")

        if self._matches_any(title_text, self.GEO_STRONG_KEYWORDS) or self._china_market_context(title_text):
            tags.append("🛢 Oil / Geopolitics")

        if self._matches_any(title_text, self.AI_TECH_KEYWORDS):
            tags.append("🤖 AI / Tech")

        if self._matches_any(title_text, self.CRYPTO_KEYWORDS):
            tags.append("₿ Crypto")

        if self._matches_any(title_text, self.BROAD_MARKET_KEYWORDS):
            tags.append("📊 Broad Market")

        if not tags and self._matches_any(title_text, self.GENERAL_NEWS_KEYWORDS):
            tags.append("🗞 General News")

        return self._dedupe_tags(tags)

    def _should_ignore(self, title_text):
        if not self._matches_any(title_text, self.IRRELEVANT_KEYWORDS):
            return False
        return not self._matches_any(title_text, self.OVERRIDE_KEEP_KEYWORDS)

    def _china_market_context(self, title_text):
        if not self._keyword_match(title_text, "china") and not self._keyword_match(title_text, "beijing"):
            return False
        return self._matches_any(title_text, self.CHINA_CONTEXT_KEYWORDS)

    def _is_fresh(self, item):
        age_minutes = item.get("age_minutes")
        if age_minutes is None:
            return False
        return age_minutes <= self.max_age_hours * 60

    def _resolve_category(self, category):
        if category is None:
            return None
        normalized = category.strip().lower()
        return self.CATEGORY_ALIASES.get(normalized)

    def _primary_tag(self, tags):
        for tag in self.TAG_PRIORITY:
            if tag in tags:
                return tag
        return tags[0]

    def _dedupe_tags(self, tags):
        deduped = []
        for tag in tags:
            if tag not in deduped:
                deduped.append(tag)
        return deduped

    def _matches_any(self, text, keywords):
        return any(self._keyword_match(text, keyword) for keyword in keywords)

    def _keyword_match(self, text, keyword):
        normalized_keyword = self._normalize_text(keyword)
        if not normalized_keyword:
            return False
        pattern = rf"(?<![a-z0-9]){re.escape(normalized_keyword)}(?![a-z0-9])"
        return re.search(pattern, text) is not None

    def _normalize_text(self, text):
        text = (text or "").lower()
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _importance(self, score):
        if score >= 4:
            return "★★★★★"
        if score == 3:
            return "★★★★☆"
        if score == 2:
            return "★★★☆☆"
        return "★★☆☆☆"

    def _why_it_matters(self, tags):
        if "🏦 Fed / Rates" in tags:
            return "Rates and inflation can move the whole market, especially tech and growth stocks."
        if "🛢 Oil / Geopolitics" in tags:
            return "Oil and geopolitical headlines can affect inflation, energy stocks, defense, and risk appetite."
        if "🤖 AI / Tech" in tags:
            return "AI and tech headlines can drive Nasdaq futures, QQQ, NVDA, AMD, and related names."
        if "₿ Crypto" in tags:
            return "Crypto headlines may move Bitcoin even when the broader stock market is quiet."
        if "📊 Broad Market" in tags:
            return "Broad market headlines can explain moves in S&P futures, Nasdaq futures, and VIX."
        if "🗞 General News" in tags:
            return "Important national/world news. Watch whether markets start reacting after the headline spreads."
        return "Watch market reaction before treating this as important."

    def _watch(self, tags):
        watch = []
        if "🏦 Fed / Rates" in tags:
            watch.extend(["US10Y", "DXY", "Nasdaq Futures", "VIX"])
        if "🛢 Oil / Geopolitics" in tags:
            watch.extend(["Oil", "VIX", "S&P Futures", "Defense"])
        if "🤖 AI / Tech" in tags:
            watch.extend(["Nasdaq Futures", "NVDA", "AMD", "QQQ"])
        if "₿ Crypto" in tags:
            watch.extend(["Bitcoin", "Coinbase", "Crypto ETFs"])
        if "📊 Broad Market" in tags:
            watch.extend(["S&P Futures", "Nasdaq Futures", "VIX"])
        if "🗞 General News" in tags:
            watch.extend(["S&P Futures", "VIX", "Dollar", "Market reaction"])

        deduped = []
        for item in watch:
            if item not in deduped:
                deduped.append(item)
        return ", ".join(deduped[:5]) or "Market reaction"

    def _published_label(self, published_dt):
        if published_dt is None:
            return "Unknown"
        try:
            local_time = published_dt.astimezone(ZoneInfo("America/Los_Angeles"))
            return local_time.strftime("%I:%M %p PT").lstrip("0")
        except Exception:
            return "Unknown"

    def _age_label(self, published_dt):
        minutes = self._age_minutes(published_dt)
        if minutes is None:
            return "Unknown"
        if minutes < 1:
            return "just now"
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        remaining_minutes = minutes % 60
        if remaining_minutes == 0:
            return f"{hours}h ago"
        return f"{hours}h {remaining_minutes}m ago"

    def _age_minutes(self, published_dt):
        if published_dt is None:
            return None
        try:
            now = datetime.now(ZoneInfo("UTC"))
            if published_dt.tzinfo is None:
                published_dt = published_dt.replace(tzinfo=ZoneInfo("UTC"))
            published_utc = published_dt.astimezone(ZoneInfo("UTC"))
            seconds = (now - published_utc).total_seconds()
            return max(0, int(seconds // 60))
        except Exception:
            return None

    def _env_bool(self, name, default=False):
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in ("1", "true", "yes", "y", "on")

    def _timestamp(self):
        now = datetime.now(ZoneInfo("America/Los_Angeles"))
        return now.strftime("%I:%M %p PT").lstrip("0")
