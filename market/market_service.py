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
        theme = self._detect_theme(market_change, tech_change, fear_change, oil_change, bitcoin_change)

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
        if quote.get("status") == "Unavailable":
            return f'{quote.get("symbol", "Unknown")}\nUnavailable / no fresh data'

        price = self._format_price(quote.get("price", 0), quote.get("kind", "number"))
        change_text = self._format_change(quote)

        value = (
            f'{quote.get("symbol", "Unknown")}\n'
            f'Price: **{price}**\n'
            f'Today: **{change_text}**\n'
            f'Status: {quote.get("status", "Unknown")}'
        )

        if quote.get("stale"):
            value += "\nNote: **stale/no fresh intraday data**"
        elif quote.get("status") == "Futures":
            value += "\nAfter Market: **Live futures / overnight price**"

        if quote.get("extended_price") is not None:
            extended_label = quote.get("status", "Extended")
            extended_price = self._format_price(quote.get("extended_price"), quote.get("kind", "number"))
            extended_change = self._safe_percent(quote.get("extended_change_percent"))

            if extended_change is None:
                value += f'\n{extended_label}: **{extended_price}**'
            else:
                value += f'\n{extended_label}: **{extended_price}** ({extended_change:+.2f}%)'

        return value

    def _format_price(self, price, kind):
        value = self._safe_number(price)
        if value is None:
            return "no fresh price"

        if kind == "crypto":
            return f"${value:,.0f}"
        if kind in ("money", "futures_money"):
            return f"${value:,.2f}"
        if kind == "futures":
            return f"{value:,.2f} pts"
        if kind == "yield":
            return f"{value:.2f}%"
        return f"{value:,.2f}"

    def _find_equity_leader(self, snapshot):
        valid = self._fresh_quotes(snapshot, ["market", "tech"])
        if not valid:
            return "No fresh S&P/Nasdaq data"

        key, quote = max(valid, key=lambda item: self._safe_percent(item[1].get("change_percent")) or 0)
        return f'{quote["label"]} ({self._format_change(quote)})'

    def _find_equity_weakest(self, snapshot):
        valid = self._fresh_quotes(snapshot, ["market", "tech"])
        if not valid:
            return "No fresh S&P/Nasdaq data"

        key, quote = min(valid, key=lambda item: self._safe_percent(item[1].get("change_percent")) or 0)
        return f'{quote["label"]} ({self._format_change(quote)})'

    def _find_warning_signal(self, snapshot):
        valid = self._fresh_quotes(snapshot, ["fear", "dollar", "rates"])
        if not valid:
            return "No fresh fear/rates/dollar data"

        key, quote = max(valid, key=lambda item: self._safe_percent(item[1].get("change_percent")) or 0)
        return f'{quote["label"]} ({self._format_change(quote)})'

    def _fresh_quotes(self, snapshot, keys):
        valid = []
        for key in keys:
            quote = snapshot.get(key, {})
            if quote.get("status") == "Unavailable":
                continue
            if quote.get("stale"):
                continue
            if self._safe_percent(quote.get("change_percent")) is None:
                continue
            valid.append((key, quote))
        return valid

    def _format_signal(self, snapshot, key):
        quote = snapshot.get(key, {})
        if quote.get("status") == "Unavailable":
            return f'{quote.get("label", key)} (unavailable)'
        return f'{quote.get("label", key)} ({self._format_change(quote)})'

    def _format_change(self, quote):
        if quote.get("status") == "Unavailable":
            return "unavailable"

        value = self._safe_percent(quote.get("change_percent"))
        if value is None:
            return "no fresh % data"

        if quote.get("stale"):
            if abs(value) < 0.005:
                return "flat / no fresh move"
            return f"{value:+.2f}% stale"

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

    def _safe_number(self, value):
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None

        if math.isnan(result) or math.isinf(result):
            return None
        return result

    def _safe_percent(self, value):
        return self._safe_number(value)

    def _timestamp(self):
        now = datetime.now(ZoneInfo("America/Los_Angeles"))
        return now.strftime("%I:%M %p").lstrip("0")
