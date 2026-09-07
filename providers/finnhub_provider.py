import math
from datetime import datetime, time
from zoneinfo import ZoneInfo

import yfinance as yf


class FinnhubProvider:
    """Market data provider.

    The class name is still FinnhubProvider so the rest of the app keeps working.
    Under the hood, this provider now uses Yahoo Finance through yfinance.
    """

    SYMBOLS = {
        "market": {"symbol": "ES=F", "label": "🇺🇸 S&P Futures", "kind": "futures"},
        "tech": {"symbol": "NQ=F", "label": "🤖 Nasdaq Futures", "kind": "futures"},
        "fear": {"symbol": "^VIX", "label": "😨 Fear", "kind": "number"},
        "oil": {"symbol": "CL=F", "label": "🛢 Oil", "kind": "futures_money"},
        "gold": {"symbol": "GC=F", "label": "🥇 Gold", "kind": "futures_money"},
        "dollar": {"symbol": "DX-Y.NYB", "label": "💵 Dollar", "kind": "number"},
        "rates": {"symbol": "^TNX", "label": "🏦 US10Y", "kind": "yield"},
        "bitcoin": {"symbol": "BTC-USD", "label": "₿ Bitcoin", "kind": "crypto"},
    }

    def get_market_snapshot(self):
        snapshot = {}

        for key, details in self.SYMBOLS.items():
            snapshot[key] = self.get_quote(
                symbol=details["symbol"],
                label=details["label"],
                kind=details["kind"],
            )

        return snapshot

    def get_quote(self, symbol, label=None, kind="number"):
        try:
            ticker = yf.Ticker(symbol)

            fast_info = ticker.fast_info
            daily_history = ticker.history(period="5d", interval="1d", auto_adjust=False)
            intraday_history = ticker.history(
                period="1d",
                interval="1m",
                prepost=True,
                auto_adjust=False,
            )

            price = self._read_fast_info(fast_info, "last_price")
            if price is None:
                price = self._latest_close(intraday_history)
            if price is None:
                price = self._latest_close(daily_history)

            previous_close = self._read_fast_info(fast_info, "regular_market_previous_close")
            if previous_close is None:
                previous_close = self._read_fast_info(fast_info, "previous_close")
            if previous_close is None:
                previous_close = self._previous_close_from_history(daily_history)

            if price is None or previous_close in (None, 0):
                return self._empty_quote(symbol, label, kind, "Unavailable")

            change = price - previous_close
            change_percent = (change / previous_close) * 100

            price = self._safe_float(price)
            previous_close = self._safe_float(previous_close)
            change = self._safe_float(change)
            change_percent = self._safe_float(change_percent)

            if price is None or previous_close is None or change is None or change_percent is None:
                return self._empty_quote(symbol, label, kind, "Unavailable")

            status = self._market_status(kind)
            stale = self._is_stale_market_data(kind, intraday_history)

            extended_price = None
            extended_change_percent = None

            if status in ("Pre-Market", "After Hours"):
                extended_price = self._latest_close(intraday_history)

                if extended_price is not None and previous_close:
                    extended_change_percent = ((extended_price - previous_close) / previous_close) * 100

            return {
                "symbol": symbol,
                "label": label or symbol,
                "kind": kind,
                "price": round(price, 2),
                "change": round(change, 2),
                "change_percent": round(change_percent, 2),
                "extended_price": self._round_or_none(extended_price),
                "extended_change_percent": self._round_or_none(extended_change_percent),
                "status": status,
                "stale": stale,
                "error": None,
            }

        except Exception as error:
            return self._empty_quote(
                symbol=symbol,
                label=label,
                kind=kind,
                status="Unavailable",
                error=str(error),
            )

    def _read_fast_info(self, fast_info, key):
        try:
            value = fast_info[key]
        except Exception:
            value = None

        return self._safe_float(value)

    def _latest_close(self, history):
        if history is None or history.empty or "Close" not in history:
            return None

        closes = history["Close"].dropna()

        if closes.empty:
            return None

        return self._safe_float(closes.iloc[-1])

    def _previous_close_from_history(self, history):
        if history is None or history.empty or "Close" not in history:
            return None

        closes = history["Close"].dropna()

        if len(closes) >= 2:
            return self._safe_float(closes.iloc[-2])

        if len(closes) == 1:
            return self._safe_float(closes.iloc[0])

        return None

    def _market_status(self, kind):
        if kind == "crypto":
            return "24/7"

        if kind in ("futures", "futures_money"):
            return "Futures"

        now = datetime.now(ZoneInfo("America/New_York"))

        if now.weekday() >= 5:
            return "Closed"

        current_time = now.time()

        if time(4, 0) <= current_time < time(9, 30):
            return "Pre-Market"

        if time(9, 30) <= current_time < time(16, 0):
            return "Open"

        if time(16, 0) <= current_time < time(20, 0):
            return "After Hours"

        return "Closed"

    def _is_stale_market_data(self, kind, intraday_history):
        """Mark quotes that came from stale daily data instead of fresh intraday data."""
        if kind == "crypto":
            return False

        return intraday_history is None or intraday_history.empty

    def _safe_float(self, value):
        if value in (None, "N/A"):
            return None

        try:
            result = float(value)
        except (TypeError, ValueError):
            return None

        if math.isnan(result) or math.isinf(result):
            return None

        return result

    def _round_or_none(self, value):
        value = self._safe_float(value)
        if value is None:
            return None

        return round(value, 2)

    def _empty_quote(self, symbol, label=None, kind="number", status="Unavailable", error=None):
        return {
            "symbol": symbol,
            "label": label or symbol,
            "kind": kind,
            "price": 0,
            "change": 0,
            "change_percent": None,
            "extended_price": None,
            "extended_change_percent": None,
            "status": status,
            "stale": True,
            "error": error,
        }
