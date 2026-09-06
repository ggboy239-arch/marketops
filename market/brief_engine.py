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

        reports = {
            "market": self.news_engine.get_top_news(limit=1, category="market"),
            "general": self.news_engine.get_top_news(limit=1, category="general"),
            "ai": self.news_engine.get_top_news(limit=1, category="ai"),
            "fed": self.news_engine.get_top_news(limit=1, category="fed"),
            "geo": self.news_engine.get_top_news(limit=1, category="geo"),
            "crypto": self.news_engine.get_top_news(limit=1, category="crypto"),
            "reddit": self.news_engine.get_top_news(limit=1, category="reddit"),
        }

        return {
            "dashboard": dashboard,
            "top_items": {
                "market": self._first_item(reports["market"]),
                "general": self._first_item(reports["general"]),
                "ai": self._first_item(reports["ai"]),
                "fed": self._first_item(reports["fed"]),
                "geo": self._first_item(reports["geo"]),
                "crypto": self._first_item(reports["crypto"]),
                "reddit": self._first_item(reports["reddit"]),
            },
            "provider_used": self._brief_provider_text(reports),
            "updated": dashboard.get("updated", "Unknown"),
            "watch_list": self._build_watch_list(dashboard),
        }

    def _first_item(self, report):
        items = report.get("items", [])
        if not items:
            return None
        return items[0]

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
