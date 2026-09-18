from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market.market_service import MarketService
from market.news_engine import NewsEngine


class TomorrowSetupEngine:
    def __init__(self):
        self.market = MarketService()
        self.news = NewsEngine()

    def build(self):
        dashboard = self.market.get_dashboard()
        score = int(dashboard["score"])
        if score >= 58:
            bias = "Bullish"
        elif score <= 42:
            bias = "Bearish"
        else:
            bias = "Mixed"
        probability = min(80, max(50, 50 + abs(score - 50)))
        raw = dashboard.get("raw", {})
        signals = {
            key: {
                "symbol": quote.get("symbol"),
                "price": quote.get("price"),
                "change_percent": quote.get("change_percent"),
                "status": quote.get("status"),
                "stale": quote.get("stale", False),
            }
            for key, quote in raw.items()
        }
        news = self.news.get_top_news(limit=5, category="all").get("items", [])
        catalysts = [item.get("title") for item in news if item.get("title")][:5]
        confirmation, invalidation = self._rules(bias)
        now = datetime.now(ZoneInfo("America/Los_Angeles"))
        session = self._next_session(now)
        return {
            "session_date": session.strftime("%Y-%m-%d"),
            "created_at": now.isoformat(timespec="seconds"),
            "bias": bias,
            "probability": probability,
            "risk_score": score,
            "signals": signals,
            "reasons": dashboard.get("reasons", [])[:6],
            "catalysts": catalysts,
            "confirmation": confirmation,
            "invalidation": invalidation,
            "priced_in_note": "Judge the reaction against expectations: good news can fall if already priced in, and bad news can rally if less severe than feared.",
        }

    @staticmethod
    def _rules(bias):
        if bias == "Bullish":
            return (["ES and NQ remain positive", "VIX stays flat or falls", "DXY and US10Y do not surge"],
                    ["ES turns below -0.5%", "VIX rises 5% or more", "yields and dollar rise together"])
        if bias == "Bearish":
            return (["ES and NQ remain negative", "VIX stays elevated", "defensive assets continue leading"],
                    ["ES recovers above +0.5%", "VIX reverses lower", "NQ begins leading higher"])
        return (["Wait for ES/NQ direction plus VIX confirmation", "Trade the reaction, not the headline"],
                ["A decisive move above +0.5% or below -0.5% replaces the mixed setup"])

    @staticmethod
    def _next_session(now):
        candidate = now.date() + timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        return candidate
