from market.market_service import MarketService
from market.news_engine import NewsEngine


class BriefEngine:
    """Builds one clean morning brief from market data + routed news.

    Think of this file as the "planner." It does not send Discord messages.
    It gathers the data and returns a simple Python dictionary that Discord can display.
    """

    def __init__(self):
        self.market_service = MarketService()
        self.news_engine = NewsEngine()

    def build_brief(self):
        dashboard = self.market_service.get_dashboard()

        market_news = self.news_engine.get_top_news(limit=1, category="market")
        general_news = self.news_engine.get_top_news(limit=1, category="general")
        ai_news = self.news_engine.get_top_news(limit=1, category="ai")
        fed_news = self.news_engine.get_top_news(limit=1, category="fed")
        geo_news = self.news_engine.get_top_news(limit=1, category="geo")
        crypto_news = self.news_engine.get_top_news(limit=1, category="crypto")
        reddit_news = self.news_engine.get_top_news(limit=1, category="reddit")

        return {
            "dashboard": dashboard,
            "top_items": {
                "market": self._first_item(market_news),
                "general": self._first_item(general_news),
                "ai": self._first_item(ai_news),
                "fed": self._first_item(fed_news),
                "geo": self._first_item(geo_news),
                "crypto": self._first_item(crypto_news),
                "reddit": self._first_item(reddit_news),
            },
            "provider_used": self.news_engine.last_provider_used,
            "updated": dashboard.get("updated", "Unknown"),
            "watch_list": self._build_watch_list(dashboard),
        }

    def _first_item(self, report):
        items = report.get("items", [])
        if not items:
            return None
        return items[0]

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
