from datetime import datetime
from zoneinfo import ZoneInfo

from providers.rss_provider import RSSProvider


class NewsEngine:
    """Turns raw RSS headlines into market-aware news cards.

    Provider job: fetch headlines.
    Engine job: classify headlines, explain why they matter, choose what to watch,
    and decide which Discord channel should receive the headline.
    """

    KEYWORDS = {
        "🤖 AI / Tech": [
            "ai",
            "artificial intelligence",
            "nvidia",
            "amd",
            "semiconductor",
            "chip",
            "chips",
            "data center",
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
            "rate",
            "rates",
            "yield",
            "yields",
            "treasury",
            "treasuries",
            "inflation",
            "cpi",
            "ppi",
            "jobs",
            "payroll",
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
        ],
        "₿ Crypto": [
            "bitcoin",
            "crypto",
            "cryptocurrency",
            "ethereum",
            "coinbase",
            "sec",
            "etf",
            "blackrock",
        ],
        "📊 Broad Market": [
            "stocks",
            "shares",
            "wall street",
            "s&p",
            "nasdaq",
            "dow",
            "futures",
            "market",
            "markets",
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

    def get_top_news(self, limit=5, category="all"):
        raw_items = self.provider.get_latest_news(limit=30)
        classified_items = [self._classify(item) for item in raw_items]

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
        }

    def get_channel_reports(self, limit_per_channel=3):
        raw_items = self.provider.get_latest_news(limit=40)
        classified_items = [self._classify(item) for item in raw_items]
        classified_items.sort(key=lambda item: item["importance_score"], reverse=True)

        reports = {}

        for item in classified_items:
            channel = item["channel"]

            if channel not in reports:
                reports[channel] = []

            if len(reports[channel]) < limit_per_channel:
                reports[channel].append(item)

        return {
            "channels": reports,
            "updated": self._timestamp(),
        }

    def channel_map_text(self):
        lines = []

        for tag, channel in self.CHANNEL_MAP.items():
            lines.append(f"• {tag} → `#{channel}`")

        return "\n".join(lines)

    def category_help(self):
        return (
            "Use one of these:\n"
            "• `!news` — all market news\n"
            "• `!news ai` — AI / tech\n"
            "• `!news fed` — Fed / rates / inflation\n"
            "• `!news geo` — oil / geopolitics\n"
            "• `!news crypto` — bitcoin / crypto\n"
            "• `!news market` — broad market\n"
            "• `!news channels` — show channel routing\n"
            "• `!news post` — post headlines into the matching channels"
        )

    def _classify(self, item):
        text = f'{item.get("title", "")} {item.get("summary", "")}'.lower()
        tags = []
        score = 1

        for tag, keywords in self.KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                tags.append(tag)
                score += 1

        if not tags:
            tags.append("📰 General")

        primary_tag = self._primary_tag(tags)
        channel = self.CHANNEL_MAP.get(primary_tag, "breaking-news")

        if item.get("source", "").lower().startswith("reuters"):
            score += 1

        importance = self._importance(score)

        return {
            "source": item.get("source", "Unknown"),
            "title": item.get("title", "Untitled"),
            "link": item.get("link", ""),
            "summary": item.get("summary", ""),
            "published": item.get("published", ""),
            "tags": tags,
            "primary_tag": primary_tag,
            "channel": channel,
            "importance": importance,
            "importance_score": score,
            "why_it_matters": self._why_it_matters(tags),
            "watch": self._watch(tags),
        }

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

    def _timestamp(self):
        now = datetime.now(ZoneInfo("America/Los_Angeles"))
        return now.strftime("%I:%M %p PT").lstrip("0")
