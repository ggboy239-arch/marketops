import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from providers.rss_provider import RSSProvider


class NewsEngine:
    """Turns trusted RSS headlines into market-aware news cards.

    Provider job: fetch and verify headlines.
    Engine job: classify headlines, explain why they matter, choose what to watch,
    and decide which Discord channel should receive the headline.
    """

    KEYWORDS = {
        "🤖 AI / Tech": [
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
        ],
        "🏦 Fed / Rates": [
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
        ],
        "🛢 Oil / Geopolitics": [
            "oil",
            "crude",
            "brent",
            "wti",
            "opec",
            "iran",
            "israel",
            "hezbollah",
            "lebanon",
            "hormuz",
            "middle east",
            "russia",
            "ukraine",
            "china",
            "taiwan",
            "north korea",
            "nato",
            "war",
            "sanctions",
        ],
        "₿ Crypto": [
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
        ],
        "📊 Broad Market": [
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
        ],
    }

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
    }

    CHANNEL_MAP = {
        "🤖 AI / Tech": "ai-news",
        "🏦 Fed / Rates": "fed",
        "🛢 Oil / Geopolitics": "geopolitics",
        "₿ Crypto": "crypto",
        "📊 Broad Market": "breaking-news",
        "📰 General": "breaking-news",
    }

    CHANNEL_ORDER = [
        "breaking-news",
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
        "📰 General",
    ]

    def __init__(self):
        self.provider = RSSProvider()
        self.max_age_hours = float(os.getenv("NEWS_MAX_AGE_HOURS", "6"))

    def get_top_news(self, limit=5, category="all"):
        raw_items = self.provider.get_latest_news(limit=50)
        classified_items = [self._classify(item) for item in raw_items]
        classified_items = [item for item in classified_items if self._is_fresh(item)]

        tag_filter = self._resolve_category(category)
        if tag_filter is not None:
            classified_items = [
                item for item in classified_items if tag_filter in item["tags"]
            ]

        classified_items.sort(key=lambda item: item["importance_score"], reverse=True)

        return {
            "items": classified_items[:limit],
            "category": category or "all",
            "tag_filter": tag_filter,
            "updated": self._timestamp(),
            "source_policy": self.provider.source_policy(),
            "freshness_policy": self.freshness_policy(),
        }

    def get_channel_reports(self, limit_per_channel=3):
        raw_items = self.provider.get_latest_news(limit=75)
        classified_items = [self._classify(item) for item in raw_items]
        classified_items = [item for item in classified_items if self._is_fresh(item)]
        classified_items.sort(key=lambda item: item["importance_score"], reverse=True)

        reports = {channel: [] for channel in self.CHANNEL_ORDER}

        for item in classified_items:
            channel = item["channel"]

            if channel not in reports:
                reports[channel] = []

            if len(reports[channel]) < limit_per_channel:
                reports[channel].append(item)

        return {
            "channels": reports,
            "counts": {channel: len(items) for channel, items in reports.items()},
            "updated": self._timestamp(),
            "source_policy": self.provider.source_policy(),
            "freshness_policy": self.freshness_policy(),
        }

    def channel_map_text(self):
        lines = []

        for tag, channel in self.CHANNEL_MAP.items():
            lines.append(f"• {tag} → `#{channel}`")

        return "\n".join(lines)

    def source_policy(self):
        return self.provider.source_policy()

    def freshness_policy(self):
        return (
            f"MarketOps shows trusted headlines published within the last "
            f"{self.max_age_hours:g} hour(s)."
        )

    def category_help(self):
        return (
            "Use one of these:\n"
            "• `!news` — all trusted market news\n"
            "• `!news ai` — AI / tech\n"
            "• `!news fed` — Fed / rates / inflation\n"
            "• `!news geo` — oil / geopolitics\n"
            "• `!news crypto` — bitcoin / crypto\n"
            "• `!news market` — broad market\n"
            "• `!news channels` — show channel routing\n"
            "• `!news sources` — show trusted-source policy\n"
            "• `!news debug` — show how many fresh headlines each channel found\n"
            "• `!news post` — post fresh headlines into the matching channels"
        )

    def _classify(self, item):
        title_text = self._normalize_text(item.get("title", ""))
        tags = []
        score = 1

        category_hint = item.get("category_hint")
        if category_hint:
            tags.append(category_hint)
            score += 1

        for tag, keywords in self.KEYWORDS.items():
            if self._matches_any(title_text, keywords):
                tags.append(tag)
                score += 1

        tags = self._dedupe_tags(tags)

        if not tags:
            tags.append("📰 General")

        primary_tag = self._primary_tag(tags)
        channel = self.CHANNEL_MAP.get(primary_tag, "breaking-news")

        if item.get("source", "").lower().startswith("reuters"):
            score += 1

        published_dt = item.get("published_dt")
        importance = self._importance(score)

        return {
            "source": item.get("source", "Unknown"),
            "title": item.get("title", "Untitled"),
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
        }

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

        return "This may be useful context, but wait for market reaction before treating it as important."

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

        if not watch:
            watch.append("Market reaction")

        deduped = []
        for item in watch:
            if item not in deduped:
                deduped.append(item)

        return ", ".join(deduped[:5])

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

    def _timestamp(self):
        now = datetime.now(ZoneInfo("America/Los_Angeles"))
        return now.strftime("%I:%M %p PT").lstrip("0")
