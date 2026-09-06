from datetime import datetime
from zoneinfo import ZoneInfo

from providers.rss_provider import RSSProvider


class NewsEngine:
    """Turns raw RSS headlines into market-aware news cards.

    Provider job: fetch headlines.
    Engine job: classify headlines, explain why they matter, and choose what to watch.
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
        ],
        "🏦 Fed / Rates": [
            "fed",
            "federal reserve",
            "powell",
            "rate",
            "rates",
            "yield",
            "treasury",
            "inflation",
            "cpi",
            "ppi",
            "jobs",
            "payroll",
        ],
        "🛢 Oil / Geopolitics": [
            "oil",
            "crude",
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
        ],
        "₿ Crypto": [
            "bitcoin",
            "crypto",
            "ethereum",
            "coinbase",
            "sec",
            "etf",
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
        ],
    }

    def __init__(self):
        self.provider = RSSProvider()

    def get_top_news(self, limit=5):
        raw_items = self.provider.get_latest_news(limit=20)
        classified_items = [self._classify(item) for item in raw_items]
        classified_items.sort(key=lambda item: item["importance_score"], reverse=True)

        return {
            "items": classified_items[:limit],
            "updated": self._timestamp(),
        }

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

        importance = self._importance(score)

        return {
            "source": item.get("source", "Unknown"),
            "title": item.get("title", "Untitled"),
            "link": item.get("link", ""),
            "summary": item.get("summary", ""),
            "published": item.get("published", ""),
            "tags": tags,
            "importance": importance,
            "importance_score": score,
            "why_it_matters": self._why_it_matters(tags),
            "watch": self._watch(tags),
        }

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
