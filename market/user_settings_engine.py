import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from providers.finnhub_provider import FinnhubProvider


class UserSettingsEngine:
    """Stores personal MarketOps settings by Discord user ID.

    Plain English: the shared server can have many people, but each Discord user
    gets their own watchlist, timezone, threshold, and brief times.
    """

    DEFAULT_TIMEZONE = "America/Los_Angeles"
    DEFAULT_BRIEF_TIMES = ["05:30", "09:30", "13:15"]
    DEFAULT_THRESHOLD = 3.0
    DEFAULT_SYMBOLS = ["NVDA", "AMD", "TSN", "RTX", "LMT", "SPY", "QQQ", "BTC-USD"]

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
        "TSLA": "Tesla",
        "PLTR": "Palantir",
        "BTC-USD": "Bitcoin",
        "ETH-USD": "Ethereum",
    }

    def __init__(self):
        self.provider = FinnhubProvider()
        self.base_path = Path("data/users")

    def get_settings(self, user_id, username="User"):
        settings = self._read_user(user_id)
        settings.setdefault("username", username)
        settings.setdefault("timezone", self.DEFAULT_TIMEZONE)
        settings.setdefault("brief_times", list(self.DEFAULT_BRIEF_TIMES))
        settings.setdefault("threshold", self.DEFAULT_THRESHOLD)
        settings.setdefault("symbols", self._default_symbols())
        settings.setdefault("alerts_enabled", True)
        settings.setdefault("news_alerts_enabled", True)
        settings.setdefault("updated", self._timestamp(settings["timezone"]))
        self._write_user(user_id, settings)
        return settings

    def set_timezone(self, user_id, username, timezone_name):
        timezone_name = (timezone_name or "").strip()
        if not timezone_name:
            return {"ok": False, "message": "Use a timezone like `America/Los_Angeles` or `America/New_York`."}

        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            return {"ok": False, "message": f"I do not recognize `{timezone_name}`. Try `America/Los_Angeles`, `America/New_York`, or `America/Chicago`."}

        settings = self.get_settings(user_id, username)
        settings["timezone"] = timezone_name
        settings["updated"] = self._timestamp(timezone_name)
        self._write_user(user_id, settings)
        return {"ok": True, "message": f"Timezone set to `{timezone_name}`.", "settings": settings}

    def set_brief_times(self, user_id, username, times_text):
        times = []
        for item in (times_text or "").split(","):
            cleaned = item.strip()
            if self._valid_time(cleaned):
                times.append(cleaned)

        if not times:
            return {"ok": False, "message": "Use 24-hour times like `05:30,09:30,13:15`."}

        settings = self.get_settings(user_id, username)
        settings["brief_times"] = times
        settings["updated"] = self._timestamp(settings["timezone"])
        self._write_user(user_id, settings)
        return {"ok": True, "message": f"Personal brief times set to `{', '.join(times)}`.", "settings": settings}

    def set_threshold(self, user_id, username, value):
        try:
            threshold = float(str(value).replace("%", "").strip())
        except (TypeError, ValueError):
            return {"ok": False, "message": "Use a number like `2`, `3`, or `5`."}

        if threshold <= 0 or threshold > 25:
            return {"ok": False, "message": "Use a threshold between 0 and 25."}

        settings = self.get_settings(user_id, username)
        settings["threshold"] = threshold
        settings["updated"] = self._timestamp(settings["timezone"])
        self._write_user(user_id, settings)
        return {"ok": True, "message": f"Personal alert threshold set to ±{threshold:g}%.", "settings": settings}

    def add_symbol(self, user_id, username, symbol):
        clean = self._normalize_symbol(symbol)
        if not clean:
            return {"ok": False, "message": "Use a ticker like `!mywatch TSLA`."}

        settings = self.get_settings(user_id, username)
        if clean not in settings["symbols"]:
            settings["symbols"].append(clean)
            settings["updated"] = self._timestamp(settings["timezone"])
            self._write_user(user_id, settings)
            return {"ok": True, "message": f"Added `{clean}` to your personal watchlist.", "settings": settings}

        return {"ok": True, "message": f"`{clean}` is already on your personal watchlist.", "settings": settings}

    def remove_symbol(self, user_id, username, symbol):
        clean = self._normalize_symbol(symbol)
        if not clean:
            return {"ok": False, "message": "Use a ticker like `!myunwatch TSLA`."}

        settings = self.get_settings(user_id, username)
        settings["symbols"] = [item for item in settings["symbols"] if item != clean]
        settings["updated"] = self._timestamp(settings["timezone"])
        self._write_user(user_id, settings)
        return {"ok": True, "message": f"Removed `{clean}` from your personal watchlist.", "settings": settings}

    def reset_user(self, user_id, username):
        settings = {
            "username": username,
            "timezone": self.DEFAULT_TIMEZONE,
            "brief_times": list(self.DEFAULT_BRIEF_TIMES),
            "threshold": self.DEFAULT_THRESHOLD,
            "symbols": self._default_symbols(),
            "alerts_enabled": True,
            "news_alerts_enabled": True,
            "updated": self._timestamp(self.DEFAULT_TIMEZONE),
        }
        self._write_user(user_id, settings)
        return {"ok": True, "message": "Personal settings reset to defaults.", "settings": settings}

    def watchlist_report(self, user_id, username):
        settings = self.get_settings(user_id, username)
        quotes = []

        for symbol in settings["symbols"]:
            quote = self._quote(symbol)
            quotes.append(self._format_quote(quote))

        return {"settings": settings, "quotes": quotes, "updated": self._timestamp(settings["timezone"])}

    def alerts_report(self, user_id, username):
        settings = self.get_settings(user_id, username)
        alerts = []
        threshold = float(settings.get("threshold", self.DEFAULT_THRESHOLD))

        for symbol in settings["symbols"]:
            quote = self._quote(symbol)
            change = self._safe_float(quote.get("change_percent"))
            if change is None or abs(change) < threshold:
                continue
            alerts.append(self._build_price_alert(symbol, quote, change))

        return {"settings": settings, "alerts": alerts, "updated": self._timestamp(settings["timezone"])}

    def _quote(self, symbol):
        kind = "crypto" if "BTC" in symbol or "ETH" in symbol else "money"
        return self.provider.get_quote(symbol=symbol, label=self.LABELS.get(symbol, symbol), kind=kind)

    def _format_quote(self, quote):
        symbol = quote.get("symbol", "Unknown")
        label = quote.get("label", symbol)
        status = quote.get("status", "Unknown")
        price = self._price_text(quote)
        change = self._change_text(quote)
        direction = "🟢" if (self._safe_float(quote.get("change_percent")) or 0) >= 0 else "🔴"
        return f"{direction} **{symbol}** ({label}) — {price} / {change} / {status}"

    def _build_price_alert(self, symbol, quote, change):
        label = quote.get("label", symbol)
        price = self._price_text(quote)
        direction = "up" if change >= 0 else "down"
        emoji = "🟢" if change >= 0 else "🔴"
        return f"{emoji} **{symbol}** ({label}) is {direction} **{change:+.2f}%** at **{price}**."

    def _price_text(self, quote):
        price = self._safe_float(quote.get("price"))
        if price is None:
            return "no fresh price"
        if quote.get("kind") == "crypto":
            return f"${price:,.0f}"
        return f"${price:,.2f}"

    def _change_text(self, quote):
        change = self._safe_float(quote.get("change_percent"))
        if change is None:
            return "no fresh % data"
        if quote.get("stale") and abs(change) < 0.005:
            return "flat / no fresh move"
        return f"{change:+.2f}%"

    def _default_symbols(self):
        raw = os.getenv("WATCHLIST_SYMBOLS")
        if not raw:
            return list(self.DEFAULT_SYMBOLS)
        symbols = []
        for item in raw.split(","):
            symbol = self._normalize_symbol(item)
            if symbol and symbol not in symbols:
                symbols.append(symbol)
        return symbols or list(self.DEFAULT_SYMBOLS)

    def _read_user(self, user_id):
        path = self._user_path(user_id)
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_user(self, user_id, settings):
        self.base_path.mkdir(parents=True, exist_ok=True)
        with self._user_path(user_id).open("w", encoding="utf-8") as file:
            json.dump(settings, file, indent=2)

    def _user_path(self, user_id):
        return self.base_path / f"{user_id}.json"

    def _normalize_symbol(self, symbol):
        clean = (symbol or "").strip().upper().replace("$", "").replace(" ", "")
        aliases = {"BTC": "BTC-USD", "BTCUSD": "BTC-USD", "BITCOIN": "BTC-USD", "ETH": "ETH-USD", "ETHUSD": "ETH-USD"}
        return aliases.get(clean, clean)

    def _valid_time(self, value):
        try:
            datetime.strptime(value, "%H:%M")
            return True
        except Exception:
            return False

    def _safe_float(self, value):
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        if result != result or result in (float("inf"), float("-inf")):
            return None
        return result

    def _timestamp(self, timezone_name):
        try:
            zone = ZoneInfo(timezone_name)
        except Exception:
            zone = ZoneInfo(self.DEFAULT_TIMEZONE)
        return datetime.now(zone).strftime("%I:%M %p").lstrip("0")
