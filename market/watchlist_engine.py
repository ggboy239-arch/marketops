import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from providers.finnhub_provider import FinnhubProvider


class WatchlistEngine:
    """Checks the user's watchlist and creates simple price-move alerts.

    Think of this file as the "decision brain" for watchlist alerts.
    It does not talk to Discord directly. It only checks prices, decides what
    matters, and returns alert data that a Discord cog can display.
    """

    DEFAULT_SYMBOLS = [
        "NVDA",
        "AMD",
        "TSN",
        "RTX",
        "LMT",
        "XOM",
        "CVX",
        "SPY",
        "QQQ",
        "BTC-USD",
    ]

    LABELS = {
        "NVDA": "NVIDIA",
        "AMD": "AMD",
        "TSN": "Tyson Foods",
        "RTX": "RTX / Defense",
        "LMT": "Lockheed Martin",
        "XOM": "Exxon Mobil",
        "CVX": "Chevron",
        "SPY": "S&P 500 ETF",
        "QQQ": "Nasdaq 100 ETF",
        "BTC-USD": "Bitcoin",
    }

    def __init__(self):
        self.provider = FinnhubProvider()
        self.enabled = self._env_bool("WATCHLIST_ENABLED", default=True)
        self.symbols = self._load_symbols()
        self.move_threshold = float(os.getenv("WATCHLIST_MOVE_ALERT_PERCENT", "3"))
        self.alert_store_path = Path("data/watchlist_alerts.json")
        self.alert_memory = self._load_alert_memory()

    def get_watchlist_report(self):
        quotes = []

        for symbol in self.symbols:
            quote = self._quote(symbol)
            quotes.append(self._format_quote(quote))

        return {
            "enabled": self.enabled,
            "symbols": self.symbols,
            "quotes": quotes,
            "move_threshold": self.move_threshold,
            "updated": self._timestamp(),
        }

    def scan_alerts(self, force=False):
        """Scan the watchlist and return fresh alerts.

        force=False is used for automatic checks so the bot avoids reposting the
        same symbol alert repeatedly during the same day.
        force=True is used for manual !alerts testing.
        """
        if not self.enabled:
            return {
                "enabled": False,
                "alerts": [],
                "updated": self._timestamp(),
                "move_threshold": self.move_threshold,
            }

        alerts = []
        today_key = self._today_key()

        for symbol in self.symbols:
            quote = self._quote(symbol)

            if quote.get("status") == "Unavailable":
                continue

            change_percent = self._safe_float(quote.get("change_percent"))

            if abs(change_percent) < self.move_threshold:
                continue

            alert_key = f"{today_key}:{symbol}:{'up' if change_percent >= 0 else 'down'}"

            if not force and alert_key in self.alert_memory:
                continue

            alert = self._build_alert(symbol, quote, change_percent)
            alerts.append(alert)
            self.alert_memory[alert_key] = {
                "symbol": symbol,
                "change_percent": change_percent,
                "created": self._timestamp(),
            }

        if alerts:
            self._save_alert_memory()

        return {
            "enabled": True,
            "alerts": alerts,
            "updated": self._timestamp(),
            "move_threshold": self.move_threshold,
        }

    def _quote(self, symbol):
        kind = "crypto" if "BTC" in symbol.upper() or "ETH" in symbol.upper() else "money"
        return self.provider.get_quote(
            symbol=symbol,
            label=self.LABELS.get(symbol, symbol),
            kind=kind,
        )

    def _format_quote(self, quote):
        symbol = quote.get("symbol", "Unknown")
        label = quote.get("label", symbol)
        status = quote.get("status", "Unknown")

        if status == "Unavailable":
            return {
                "symbol": symbol,
                "label": label,
                "status": status,
                "price": "Unavailable",
                "change_percent": 0,
                "line": f"{symbol} — unavailable right now",
            }

        price = quote.get("price", 0)
        change_percent = self._safe_float(quote.get("change_percent"))
        direction = "🟢" if change_percent >= 0 else "🔴"

        if quote.get("kind") == "crypto":
            price_text = f"${price:,.0f}"
        else:
            price_text = f"${price:,.2f}"

        return {
            "symbol": symbol,
            "label": label,
            "status": status,
            "price": price_text,
            "change_percent": change_percent,
            "line": f"{direction} **{symbol}** ({label}) — {price_text} / {change_percent:+.2f}% / {status}",
        }

    def _build_alert(self, symbol, quote, change_percent):
        label = quote.get("label", symbol)
        price = quote.get("price", 0)
        status = quote.get("status", "Unknown")
        direction = "up" if change_percent >= 0 else "down"
        emoji = "🟢" if change_percent >= 0 else "🔴"

        if quote.get("kind") == "crypto":
            price_text = f"${price:,.0f}"
        else:
            price_text = f"${price:,.2f}"

        return {
            "symbol": symbol,
            "label": label,
            "price": price_text,
            "change_percent": change_percent,
            "direction": direction,
            "status": status,
            "emoji": emoji,
            "message": (
                f"{emoji} **{symbol}** ({label}) is {direction} **{change_percent:+.2f}%** "
                f"at **{price_text}**. Status: {status}."
            ),
            "watch": self._watch_note(symbol, change_percent),
        }

    def _watch_note(self, symbol, change_percent):
        upper = symbol.upper()

        if upper in ("NVDA", "AMD", "QQQ"):
            return "Watch Nasdaq futures, AI headlines, chip news, and volume."

        if upper in ("RTX", "LMT"):
            return "Watch geopolitics, defense headlines, and broad market risk."

        if upper in ("XOM", "CVX"):
            return "Watch oil, OPEC, Iran/Russia headlines, and energy sector moves."

        if upper == "TSN":
            return "Watch company news, food/labor headlines, and abnormal volume."

        if "BTC" in upper:
            return "Watch Bitcoin, crypto headlines, ETF flows, and risk appetite."

        if upper in ("SPY", "DIA", "IWM"):
            return "Watch VIX, rates, Fed headlines, and broad market breadth."

        return "Check the headline reason and confirm price/volume before acting."

    def _load_symbols(self):
        raw = os.getenv("WATCHLIST_SYMBOLS")

        if not raw:
            return list(self.DEFAULT_SYMBOLS)

        symbols = []
        for item in raw.split(","):
            symbol = item.strip().upper()
            if symbol and symbol not in symbols:
                symbols.append(symbol)

        return symbols or list(self.DEFAULT_SYMBOLS)

    def _load_alert_memory(self):
        if not self.alert_store_path.exists():
            return {}

        try:
            with self.alert_store_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass

        return {}

    def _save_alert_memory(self):
        self.alert_store_path.parent.mkdir(parents=True, exist_ok=True)

        with self.alert_store_path.open("w", encoding="utf-8") as file:
            json.dump(self.alert_memory, file, indent=2)

    def _safe_float(self, value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _today_key(self):
        now = datetime.now(ZoneInfo("America/Los_Angeles"))
        return now.strftime("%Y-%m-%d")

    def _timestamp(self):
        now = datetime.now(ZoneInfo("America/Los_Angeles"))
        return now.strftime("%I:%M %p PT").lstrip("0")

    def _env_bool(self, name, default=False):
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in ("1", "true", "yes", "y", "on")
