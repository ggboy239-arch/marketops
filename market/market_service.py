from datetime import datetime
from zoneinfo import ZoneInfo

from market.risk_engine import RiskEngine
from providers.finnhub_provider import FinnhubProvider


class MarketService:

    def __init__(self):
        self.provider = FinnhubProvider()
        self.risk_engine = RiskEngine()

    def get_dashboard(self):
        snapshot = self.provider.get_market_snapshot()

        market_change = self._change(snapshot, "market")
        tech_change = self._change(snapshot, "tech")
        fear_change = self._change(snapshot, "fear")
        oil_change = self._change(snapshot, "oil")
        dollar_change = self._change(snapshot, "dollar")
        rates_change = self._change(snapshot, "rates")
        bitcoin_change = self._change(snapshot, "bitcoin")

        risk = self.risk_engine.calculate(
            market_change,
            tech_change,
            fear_change,
            oil_change,
            bitcoin_change,
            dollar_change,
            rates_change,
        )

        risk_asset_leader = self._find_risk_asset_leader(snapshot)
        risk_asset_weakest = self._find_risk_asset_weakest(snapshot)
        warning_signal = self._find_warning_signal(snapshot)
        theme = self._detect_theme(
            market_change,
            tech_change,
            fear_change,
            oil_change,
            bitcoin_change,
        )

        return {
            "risk": risk["mood"],
            "score": risk["score"],
            "confidence": risk["confidence"],
            "reasons": risk["reasons"],
            "theme": theme,
            "leader": risk_asset_leader,
            "loser": risk_asset_weakest,
            "warning_signal": warning_signal,
            "updated": self._timestamp(),
            "assets": {
                "market": self._format_asset(snapshot["market"]),
                "tech": self._format_asset(snapshot["tech"]),
                "fear": self._format_asset(snapshot["fear"]),
                "oil": self._format_asset(snapshot["oil"]),
                "dollar": self._format_asset(snapshot["dollar"]),
                "rates": self._format_asset(snapshot["rates"]),
                "bitcoin": self._format_asset(snapshot["bitcoin"]),
            },
            "raw": snapshot,
        }

    def _change(self, snapshot, key):
        try:
            return float(snapshot[key]["change_percent"])
        except (KeyError, TypeError, ValueError):
            return 0

    def _format_asset(self, quote):
        if quote["status"] == "Unavailable":
            return f'{quote["symbol"]}\nUnavailable'

        price = self._format_price(quote["price"], quote["kind"])

        value = (
            f'{quote["symbol"]}\n'
            f'Price: **{price}**\n'
            f'Today: **{quote["change_percent"]:+.2f}%**\n'
            f'Status: {quote["status"]}'
        )

        if quote["status"] == "Futures":
            value += "\nOvernight: **Live futures price**"

        if quote["extended_price"] is not None:
            extended_label = quote["status"]
            extended_price = self._format_price(quote["extended_price"], quote["kind"])
            extended_change = quote["extended_change_percent"]

            if extended_change is None:
                value += f'\n{extended_label}: **{extended_price}**'
            else:
                value += (
                    f'\n{extended_label}: **{extended_price}** '
                    f'({extended_change:+.2f}%)'
                )

        return value

    def _format_price(self, price, kind):
        if kind == "crypto":
            return f"${price:,.0f}"

        if kind in ("money", "futures_money"):
            return f"${price:,.2f}"

        if kind == "futures":
            return f"{price:,.2f} pts"

        if kind == "yield":
            return f"{price:.2f}%"

        return f"{price:,.2f}"

    def _find_risk_asset_leader(self, snapshot):
        allowed = ["market", "tech", "oil", "bitcoin"]
        key, quote = max(
            ((key, snapshot[key]) for key in allowed),
            key=lambda item: item[1].get("change_percent", 0),
        )

        return f'{quote["label"]} ({quote["change_percent"]:+.2f}%)'

    def _find_risk_asset_weakest(self, snapshot):
        allowed = ["market", "tech", "oil", "bitcoin"]
        key, quote = min(
            ((key, snapshot[key]) for key in allowed),
            key=lambda item: item[1].get("change_percent", 0),
        )

        return f'{quote["label"]} ({quote["change_percent"]:+.2f}%)'

    def _find_warning_signal(self, snapshot):
        warning_keys = ["fear", "dollar", "rates"]
        key, quote = max(
            ((key, snapshot[key]) for key in warning_keys),
            key=lambda item: item[1].get("change_percent", 0),
        )

        return f'{quote["label"]} ({quote["change_percent"]:+.2f}%)'

    def _detect_theme(self, market, tech, fear, oil, bitcoin):
        if oil >= 2:
            return "🛢 Oil / Geopolitics"

        if fear >= 5:
            return "😨 Volatility / Fear"

        if tech > market + 0.30 and tech > 0:
            return "🤖 Tech / AI"

        if bitcoin >= 2:
            return "₿ Crypto"

        if market > 0 and fear < 0:
            return "📈 Risk-On Market"

        if market < 0 and fear > 0:
            return "📉 Defensive Market"

        return "📈 Live Market"

    def _timestamp(self):
        now = datetime.now(ZoneInfo("America/Los_Angeles"))
        return now.strftime("%I:%M %p PT").lstrip("0")
