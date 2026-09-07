import math
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

        equity_leader = self._find_equity_leader(snapshot)
        equity_weakest = self._find_equity_weakest(snapshot)
        warning_signal = self._find_warning_signal(snapshot)
        energy_signal = self._format_signal(snapshot, "oil")
        crypto_signal = self._format_signal(snapshot, "bitcoin")
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
            "leader": equity_leader,
            "loser": equity_weakest,
            "warning_signal": warning_signal,
            "energy_signal": energy_signal,
            "crypto_signal": crypto_signal,
            "after_market_note": self._after_market_note(snapshot),
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
        quote = snapshot.get(key, {})
        if quote.get("status") == "Unavailable":
            return 0

        value = self._safe_percent(quote.get("change_percent"))
        if value is None:
            return 0

        return value

    def _format_asset(self, quote):
        if quote["status"] == "Unavailable":
            return f'{quote["symbol"]}\nUnavailable / no fresh data'

        price = self._format_price(quote["price"], quote["kind"])
        change_text = self._format_change(quote)

        value = (
            f'{quote["symbol"]}\n'
            f'Price: **{price}**\n'
            f'Today: **{change_text}**\n'
            f'Status: {quote["status"]}'
        )

        if quote.get("stale"):
            value += "\nNote: **stale/no fresh intraday data**"
        elif quote["status"] == "Futures":
            value += "\nAfter Market: **Live futures / overnight price**"

        if quote["extended_price"] is not None:
            extended_label = quote["status"]
            extended_price = self._format_price(quote["extended_price"], quote["kind"])
            extended_change = self._safe_percent(quote["extended_change_percent"])

            if extended_change is None:
                value += f'\n{extended_label}: **{extended_price}**'
            else:
                value += f'\n{extended_label}: **{extended_price}** ({extended_change:+.2f}%)'

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

    def _find_equity_leader(self, snapshot):
        allowed = ["market", "tech"]
        valid = [(key, snapshot[key]) for key in allowed if self._safe_percent(snapshot[key].get("change_percent")) is not None]

        if not valid:
            return "No fresh S&P/Nasdaq data"

        key, quote = max(valid, key=lambda item: self._safe_percent(item[1].get("change_percent")) or 0)
        return f'{quote["label"]} ({self._format_change(quote)})'

    def _find_equity_weakest(self, snapshot):
        allowed = ["market", "tech"]
        valid = [(key, snapshot[key]) for key in allowed if self._safe_percent(snapshot[key].get("change_percent")) is not None]

        if not valid:
            return "No fresh S&P/Nasdaq data"

        key, quote = min(valid, key=lambda item: self._safe_percent(item[1].get("change_percent")) or 0)
        return f'{quote["label"]} ({self._format_change(quote)})'

    def _find_warning_signal(self, snapshot):
        warning_keys = ["fear", "dollar", "rates"]
        valid = [(key, snapshot[key]) for key in warning_keys if self._safe_percent(snapshot[key].get("change_percent")) is not None]

        if not valid:
            return "No fresh fear/rates/dollar data"

        key, quote = max(valid, key=lambda item: self._safe_percent(item[1].get("change_percent")) or 0)
        return f'{quote["label"]} ({self._format_change(quote)})'

    def _format_signal(self, snapshot, key):
        quote = snapshot[key]
        return f'{quote["label"]} ({self._format_change(quote)})'

    def _format_change(self, quote):
        if quote.get("status") == "Unavailable":
            return "unavailable"

        value = self._safe_percent(quote.get("change_percent"))
        if value is None:
            return "no fresh % data"

        if quote.get("stale") and abs(value) < 0.005:
            return "flat / no fresh move"

        return f"{value:+.2f}%"

    def _after_market_note(self, snapshot):
        futures = [snapshot["market"]["symbol"], snapshot["tech"]["symbol"], snapshot["oil"]["symbol"]]

        stale_keys = [quote["label"] for quote in snapshot.values() if quote.get("stale")]
        stale_note = ""
        if stale_keys:
            stale_note = " Some symbols may show stale/no fresh intraday data outside active sessions."

        return (
            f'{", ".join(futures)} show futures / overnight pricing when available. '
            "BTC trades 24/7. VIX, Dollar, and US10Y may stay closed outside regular market hours."
            f"{stale_note}"
        )

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

    def _safe_percent(self, value):
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None

        if math.isnan(result) or math.isinf(result):
            return None

        return result

    def _timestamp(self):
        now = datetime.now(ZoneInfo("America/Los_Angeles"))
        return now.strftime("%I:%M %p PT").lstrip("0")
