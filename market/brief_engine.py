from market.market_service import MarketService
from market.news_engine import NewsEngine


class BriefEngine:
    """Builds one clean morning brief from market data + routed news.

    Think of this file as the "planner." It does not send Discord messages.
    It gathers the data and returns a simple Python dictionary that Discord can display.
    """

    CATEGORY_CHANNELS = {
        "market": {"breaking-news"},
        "general": {"general-news"},
        "ai": {"ai-news"},
        "fed": {"fed"},
        "geo": {"geopolitics"},
        "crypto": {"crypto"},
        "reddit": {"reddit-hot"},
    }

    def __init__(self):
        self.market_service = MarketService()
        self.news_engine = NewsEngine()

    def build_brief(self):
        dashboard = self.market_service.get_dashboard()

        reports = {
            "market": self.news_engine.get_top_news(limit=3, category="market"),
            "general": self.news_engine.get_top_news(limit=3, category="general"),
            "ai": self.news_engine.get_top_news(limit=3, category="ai"),
            "fed": self.news_engine.get_top_news(limit=3, category="fed"),
            "geo": self.news_engine.get_top_news(limit=3, category="geo"),
            "crypto": self.news_engine.get_top_news(limit=3, category="crypto"),
            "reddit": self.news_engine.get_top_news(limit=3, category="reddit"),
        }

        used_articles = set()
        top_items = {}
        for category, report in reports.items():
            top_items[category] = self._first_matching_item(category, report, used_articles)

        return {
            "dashboard": dashboard,
            "top_items": top_items,
            "provider_used": self._brief_provider_text(reports),
            "updated": dashboard.get("updated", "Unknown"),
            "watch_list": self._build_watch_list(dashboard),
        }

    def _first_matching_item(self, category, report, used_articles):
        """Pick the first item that belongs to the section and was not already used.

        Plain English: if a Fed headline gets routed to #fed, do not also show it
        under Geopolitics just because it has an oil word in the title.
        """
        items = report.get("items", [])
        allowed_channels = self.CATEGORY_CHANNELS.get(category)

        for item in items:
            channel = item.get("channel")
            if allowed_channels and channel not in allowed_channels:
                continue

            article_id = self._article_id(item)
            if article_id in used_articles:
                continue

            used_articles.add(article_id)
            return item

        return None

    def _article_id(self, item):
        return item.get("link") or item.get("title") or str(id(item))

    def _brief_provider_text(self, reports):
        """Show all providers checked instead of only the last category checked.

        The old version showed Reddit RSS in the footer because Reddit was checked
        last. That was confusing because the brief also checked Marketaux/Reuters.
        """
        providers = []

        for report in reports.values():
            provider_text = report.get("provider_used")
            if not provider_text:
                continue

            for provider in provider_text.split(" + "):
                provider = provider.strip()
                if provider and provider not in providers:
                    providers.append(provider)

        if not providers:
            return "No provider returned raw items"

        return " + ".join(providers)

    def _build_watch_list(self, dashboard):
        watch = []

        theme = dashboard.get("theme")
        warning_signal = dashboard.get("warning_signal")
        energy_signal = dashboard.get("energy_signal")
        crypto_signal = dashboard.get("crypto_signal")

        if theme:
            watch.append(f"Theme: {theme}")

        if warning_signal:
            watch.append(f"Warning: {warning_signal}")

        if energy_signal:
            watch.append(f"Energy/geo: {energy_signal}")

        if crypto_signal:
            watch.append(f"Crypto: {crypto_signal}")

        watch.append("Confirm headlines before making a trade decision")

        return watch[:5]
