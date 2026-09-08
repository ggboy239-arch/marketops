import hashlib
import json
import math
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from providers.finnhub_provider import FinnhubProvider
from providers.marketaux_provider import MarketauxProvider
from providers.rss_provider import RSSProvider


class WatchlistEngine:
    """Checks watchlist prices/news and manages user settings.

    Plain English: this is the watchlist brain. Discord commands call this file.
    Price data comes from the free yfinance/Yahoo Finance path, so MarketOps now
    shows data health and skips stale price alerts by default.
    """

    DATA_PROVIDER_LABEL = "Yahoo Finance via yfinance"

    DEFAULT_SYMBOLS = [
        "NVDA", "AMD", "TSN", "RTX", "LMT", "XOM", "CVX", "SPY", "QQQ", "BTC-USD",
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
        "BTC": "Bitcoin",
        "ETH-USD": "Ethereum",
        "ETH": "Ethereum",
        "TSLA": "Tesla",
        "PLTR": "Palantir",
        "AAPL": "Apple",
        "MSFT": "Microsoft",
        "GOOGL": "Alphabet / Google",
        "META": "Meta",
        "AMZN": "Amazon",
    }

    NEWS_TERMS = {
        "NVDA": ["nvda", "nvidia"],
        "AMD": ["amd", "advanced micro devices"],
        "TSN": ["tsn", "tyson", "tyson foods"],
        "RTX": ["rtx", "rtx corp", "raytheon"],
        "LMT": ["lmt", "lockheed", "lockheed martin"],
        "XOM": ["xom", "exxon", "exxon mobil", "exxonmobil"],
        "CVX": ["cvx", "chevron"],
        "SPY": ["spy", "s&p 500", "spdr s&p"],
        "QQQ": ["qqq", "nasdaq", "nasdaq 100"],
        "BTC-USD": ["btc", "bitcoin", "crypto"],
        "BTC": ["btc", "bitcoin", "crypto"],
        "ETH-USD": ["eth", "ethereum", "ether", "crypto"],
        "ETH": ["eth", "ethereum", "ether", "crypto"],
        "TSLA": ["tsla", "tesla"],
        "PLTR": ["pltr", "palantir"],
        "AAPL": ["aapl", "apple"],
        "MSFT": ["msft", "microsoft"],
        "GOOGL": ["googl", "google", "alphabet"],
        "META": ["meta", "facebook", "instagram"],
        "AMZN": ["amzn", "amazon", "aws"],
    }

    HIGH_TRUST_SOURCES = [
        "reuters", "associated press", "ap news", "cnbc", "marketwatch",
        "yahoo finance", "wall street journal", "wsj", "bloomberg",
        "financial times", "ft.com",
    ]

    MEDIUM_TRUST_SOURCES = [
        "seeking alpha", "benzinga", "investorplace", "motley fool", "the fly",
        "zacks", "barron's", "barrons", "investing.com",
    ]

    LOW_TRUST_HINTS = [
        "blog", "substack", "rumor", "unconfirmed", "sponsored",
        "press release", "pr newswire", "globenewswire",
    ]

    ACTION_WORDS = [
        "earnings", "guidance", "forecast", "raises", "cuts", "upgrade",
        "downgrade", "target", "deal", "contract", "lawsuit", "investigation",
        "layoffs", "strike", "shutdown", "plant", "approval", "ban",
        "sanctions", "war", "oil", "opec", "inflation", "fed", "rates",
    ]

    def __init__(self):
        self.provider = FinnhubProvider()
        self.marketaux_provider = MarketauxProvider()
        self.rss_provider = RSSProvider()
        self.symbol_store_path = Path("data/watchlist_symbols.json")
        self.settings_store_path = Path("data/watchlist_settings.json")
        self.alert_store_path = Path("data/watchlist_alerts.json")
        self.settings = self._load_settings()
        self.enabled = self._setting_bool("enabled", "WATCHLIST_ENABLED", True)
        self.news_enabled = self._setting_bool("news_enabled", "WATCHLIST_NEWS_ALERTS", True)
        self.rss_news_fallback = self._env_bool("WATCHLIST_NEWS_RSS_FALLBACK", default=True)
        self.skip_stale_price_alerts = self._env_bool("WATCHLIST_SKIP_STALE_PRICE_ALERTS", default=True)
        self.symbols = self._load_symbols()
        self.move_threshold = self._setting_float("move_threshold", "WATCHLIST_MOVE_ALERT_PERCENT", 3.0)
        self.news_max_items = int(os.getenv("WATCHLIST_NEWS_MAX_ITEMS", "15"))
        self.alert_memory = self._load_alert_memory()
        self.last_news_provider = "Not checked yet"

    def get_watchlist_report(self):
        quotes = []
        health_counts = {"fresh": 0, "closed": 0, "stale": 0, "unavailable": 0}
        for symbol in self.symbols:
            quote = self._quote(symbol)
            formatted = self._format_quote(quote)
            quotes.append(formatted)
            health_counts[formatted["health_key"]] = health_counts.get(formatted["health_key"], 0) + 1

        return {
            "enabled": self.enabled,
            "symbols": self.symbols,
            "quotes": quotes,
            "move_threshold": self.move_threshold,
            "news_enabled": self.news_enabled,
            "skip_stale_price_alerts": self.skip_stale_price_alerts,
            "data_provider": self.DATA_PROVIDER_LABEL,
            "health_counts": health_counts,
            "storage": str(self.symbol_store_path),
            "updated": self._timestamp(),
        }

    def get_price_health_report(self, symbol=None):
        if symbol:
            symbols = [self._normalize_symbol(symbol)]
        else:
            symbols = list(self.symbols)

        checks = []
        summary = {"fresh": 0, "closed": 0, "stale": 0, "unavailable": 0}
        for item in symbols:
            if not item:
                continue
            quote = self._quote(item)
            check = self._format_quote_health(quote)
            checks.append(check)
            summary[check["health_key"]] = summary.get(check["health_key"], 0) + 1

        return {
            "checks": checks,
            "summary": summary,
            "data_provider": self.DATA_PROVIDER_LABEL,
            "skip_stale_price_alerts": self.skip_stale_price_alerts,
            "updated": self._timestamp(),
            "note": (
                "Free quote data can lag or fall back to daily data. Use !watchtest to check health, "
                "and use !chart or your broker before acting."
            ),
        }

    def get_status(self, auto_enabled=True, channel_name="watchlist", poll_minutes=15):
        return {
            "enabled": self.enabled,
            "auto_enabled": auto_enabled,
            "news_enabled": self.news_enabled,
            "channel_name": channel_name,
            "poll_minutes": poll_minutes,
            "move_threshold": self.move_threshold,
            "symbols": self.symbols,
            "last_news_provider": self.last_news_provider,
            "data_provider": self.DATA_PROVIDER_LABEL,
            "skip_stale_price_alerts": self.skip_stale_price_alerts,
            "updated": self._timestamp(),
        }

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        self.settings["enabled"] = self.enabled
        self._save_settings()
        return self.get_status()

    def set_news_enabled(self, enabled):
        self.news_enabled = bool(enabled)
        self.settings["news_enabled"] = self.news_enabled
        self._save_settings()
        return self.get_status()

    def set_threshold(self, value):
        try:
            threshold = float(value)
        except (TypeError, ValueError):
            return {"ok": False, "message": "Use a number like !threshold 2 or !threshold 5."}

        if threshold <= 0 or threshold > 25:
            return {"ok": False, "message": "Use a threshold from 0.1 to 25."}

        self.move_threshold = threshold
        self.settings["move_threshold"] = threshold
        self._save_settings()
        return {"ok": True, "message": f"Price alert threshold set to ±{threshold:g}%.", "status": self.get_status()}

    def add_symbol(self, symbol):
        clean_symbol = self._normalize_symbol(symbol)
        if not clean_symbol:
            return {"ok": False, "message": "Give me a ticker symbol, like !watch TSLA.", "symbols": self.symbols}
        if clean_symbol in self.symbols:
            return {"ok": True, "changed": False, "message": f"{clean_symbol} is already on your watchlist.", "symbols": self.symbols}
        self.symbols.append(clean_symbol)
        self._save_symbols()
        return {"ok": True, "changed": True, "message": f"Added {clean_symbol} to your watchlist.", "symbols": self.symbols}

    def remove_symbol(self, symbol):
        clean_symbol = self._normalize_symbol(symbol)
        if not clean_symbol:
            return {"ok": False, "message": "Give me a ticker symbol, like !unwatch CVX.", "symbols": self.symbols}
        if clean_symbol not in self.symbols:
            return {"ok": True, "changed": False, "message": f"{clean_symbol} was not on your watchlist.", "symbols": self.symbols}
        self.symbols = [item for item in self.symbols if item != clean_symbol]
        self._save_symbols()
        return {"ok": True, "changed": True, "message": f"Removed {clean_symbol} from your watchlist.", "symbols": self.symbols}

    def reset_symbols(self):
        self.symbols = self._env_symbols() or list(self.DEFAULT_SYMBOLS)
        self._save_symbols()
        return {"ok": True, "changed": True, "message": "Watchlist reset to your .env/default symbols.", "symbols": self.symbols}

    def scan_alerts(self, force=False):
        if not self.enabled:
            return {
                "enabled": False, "alerts": [], "updated": self._timestamp(),
                "move_threshold": self.move_threshold, "news_enabled": self.news_enabled,
                "news_provider": self.last_news_provider,
                "data_provider": self.DATA_PROVIDER_LABEL,
                "skip_stale_price_alerts": self.skip_stale_price_alerts,
            }

        alerts = []
        alerts.extend(self._scan_price_alerts(force=force))
        if self.news_enabled:
            alerts.extend(self._scan_news_alerts(force=force))
        if alerts:
            self._save_alert_memory()

        return {
            "enabled": True, "alerts": alerts, "updated": self._timestamp(),
            "move_threshold": self.move_threshold, "news_enabled": self.news_enabled,
            "news_provider": self.last_news_provider,
            "data_provider": self.DATA_PROVIDER_LABEL,
            "skip_stale_price_alerts": self.skip_stale_price_alerts,
        }

    def _scan_price_alerts(self, force=False):
        alerts = []
        today_key = self._today_key()
        for symbol in self.symbols:
            quote = self._quote(symbol)
            if quote.get("status") == "Unavailable":
                continue
            if self.skip_stale_price_alerts and quote.get("stale"):
                continue
            change_percent = self._safe_float(quote.get("change_percent"))
            if abs(change_percent) < self.move_threshold:
                continue
            alert_key = f"{today_key}:price:{symbol}:{'up' if change_percent >= 0 else 'down'}"
            if not force and alert_key in self.alert_memory:
                continue
            alert = self._build_price_alert(symbol, quote, change_percent)
            alerts.append(alert)
            self.alert_memory[alert_key] = {
                "type": "price",
                "symbol": symbol,
                "change_percent": change_percent,
                "data_confidence": alert.get("data_confidence"),
                "created": self._timestamp(),
            }
        return alerts

    def _scan_news_alerts(self, force=False):
        alerts = []
        today_key = self._today_key()
        items = self._get_news_items()
        for item in items:
            matched_symbols = self._match_symbols_to_headline(item)
            for symbol in matched_symbols:
                article_id = self._article_id(item)
                alert_key = f"{today_key}:news:{symbol}:{article_id}"
                if not force and alert_key in self.alert_memory:
                    continue
                alert = self._build_news_alert(symbol, item)
                alerts.append(alert)
                self.alert_memory[alert_key] = {
                    "type": "news", "symbol": symbol, "title": item.get("title", ""),
                    "quality": alert.get("quality_label"), "created": self._timestamp(),
                }
        return alerts

    def _get_news_items(self):
        items = []
        used = []
        if self.marketaux_provider.enabled:
            marketaux_items = self.marketaux_provider.get_latest_news(limit=self.news_max_items)
            if marketaux_items:
                items.extend(marketaux_items)
                used.append("Marketaux")
        if self.rss_news_fallback:
            rss_items = self.rss_provider.get_latest_news(limit=self.news_max_items)
            if rss_items:
                items.extend(rss_items)
                used.append("Trusted RSS")
        self.last_news_provider = " + ".join(used) if used else "No news provider returned items"
        return self._dedupe_news_items(items)

    def _match_symbols_to_headline(self, item):
        text = f'{item.get("title", "")} {item.get("summary", "")}'.lower()
        matches = []
        for symbol in self.symbols:
            terms = self.NEWS_TERMS.get(symbol.upper(), [symbol.lower()])
            if self._matches_any(text, terms):
                matches.append(symbol)
        return matches

    def _quote(self, symbol):
        kind = self._quote_kind(symbol)
        return self.provider.get_quote(symbol=symbol, label=self.LABELS.get(symbol, symbol), kind=kind)

    def _quote_kind(self, symbol):
        upper = (symbol or "").upper()
        if "BTC" in upper or "ETH" in upper:
            return "crypto"
        if upper.endswith("=F"):
            return "futures_money"
        if upper == "^TNX":
            return "yield"
        if upper.startswith("^") or upper in ("DX-Y.NYB", "DXY"):
            return "number"
        return "money"

    def _format_quote(self, quote):
        symbol = quote.get("symbol", "Unknown")
        label = quote.get("label", symbol)
        status = quote.get("status", "Unknown")
        confidence = self._data_confidence(quote)
        health_key = self._health_key(quote)

        if status == "Unavailable":
            return {
                "symbol": symbol,
                "label": label,
                "status": status,
                "price": "Unavailable",
                "change_percent": 0,
                "health_key": health_key,
                "confidence": confidence,
                "line": f"⚪ **{symbol}** ({label}) — unavailable / Data: {confidence}",
            }

        price = quote.get("price", 0)
        change_percent = self._safe_float(quote.get("change_percent"))
        direction = "🟢" if change_percent >= 0 else "🔴"
        price_text = self._price_text(price, quote.get("kind"))
        return {
            "symbol": symbol,
            "label": label,
            "status": status,
            "price": price_text,
            "change_percent": change_percent,
            "health_key": health_key,
            "confidence": confidence,
            "line": f"{direction} **{symbol}** ({label}) — {price_text} / {change_percent:+.2f}% / {status} / Data: {confidence}",
        }

    def _format_quote_health(self, quote):
        formatted = self._format_quote(quote)
        return {
            "symbol": formatted["symbol"],
            "label": formatted["label"],
            "status": formatted["status"],
            "price": formatted["price"],
            "change_percent": formatted["change_percent"],
            "health_key": formatted["health_key"],
            "confidence": formatted["confidence"],
            "stale": bool(quote.get("stale")),
            "error": quote.get("error"),
            "source": quote.get("source") or self.DATA_PROVIDER_LABEL,
            "line": formatted["line"],
        }

    def _build_price_alert(self, symbol, quote, change_percent):
        label = quote.get("label", symbol)
        price = quote.get("price", 0)
        status = quote.get("status", "Unknown")
        direction = "up" if change_percent >= 0 else "down"
        emoji = "🟢" if change_percent >= 0 else "🔴"
        price_text = self._price_text(price, quote.get("kind"))
        confidence = self._data_confidence(quote)
        return {
            "type": "price", "symbol": symbol, "label": label, "price": price_text,
            "change_percent": change_percent, "direction": direction, "status": status,
            "emoji": emoji, "quality_label": "Price Move",
            "quality_reason": "Triggered by percent move threshold. Confirm with chart/broker before acting.",
            "data_confidence": confidence,
            "message": f"{emoji} **{symbol}** ({label}) is {direction} **{change_percent:+.2f}%** at **{price_text}**. Status: {status}. Data: {confidence}.",
            "watch": self._watch_note(symbol, change_percent),
        }

    def _build_news_alert(self, symbol, item):
        label = self.LABELS.get(symbol, symbol)
        title = item.get("title", "Untitled")
        source = item.get("source", "Unknown")
        provider = item.get("provider", "Unknown")
        link = item.get("link", "")
        quality = self._score_news_quality(item)
        return {
            "type": "news", "symbol": symbol, "label": label, "emoji": quality["emoji"],
            "message": f"📰 **{symbol}** ({label}) has a fresh headline: **{title}**",
            "watch": self._news_watch_note(symbol), "title": title, "source": source,
            "provider": provider, "link": link, "age": self._age_label(item.get("published_dt")),
            "quality_label": quality["label"], "quality_reason": quality["reason"],
            "quality_score": quality["score"],
        }

    def _score_news_quality(self, item):
        title = (item.get("title") or "").lower()
        source = (item.get("source") or "").lower()
        provider = (item.get("provider") or "").lower()
        link = (item.get("link") or "").lower()
        combined = f"{title} {source} {provider} {link}"
        if self._contains_any(combined, self.HIGH_TRUST_SOURCES):
            return {"label": "High Trust", "emoji": "🟢", "score": 3, "reason": "Major news/market source. Still confirm price reaction before acting."}
        if self._contains_any(combined, self.LOW_TRUST_HINTS):
            return {"label": "Low Trust", "emoji": "🔴", "score": 1, "reason": "May be a press release, blog, rumor, or promotional source. Verify first."}
        if self._contains_any(combined, self.MEDIUM_TRUST_SOURCES):
            return {"label": "Medium Trust", "emoji": "🟡", "score": 2, "reason": "Useful market commentary, but often opinion/analyst based. Confirm elsewhere."}
        if self._contains_any(title, self.ACTION_WORDS):
            return {"label": "Medium Trust", "emoji": "🟡", "score": 2, "reason": "Headline contains market-moving words, but source still needs confirmation."}
        return {"label": "Needs Confirmation", "emoji": "⚪", "score": 0, "reason": "Unknown source quality. Treat as a lead, not a trade signal."}

    def _data_confidence(self, quote):
        status = quote.get("status", "Unknown")
        if status == "Unavailable":
            return "No quote"
        if quote.get("stale"):
            return "Stale/daily fallback"
        if status in ("Open", "Pre-Market", "After Hours", "Futures", "24/7"):
            return "Fresh free quote"
        if status == "Closed":
            return "Last close"
        return "Free quote"

    def _health_key(self, quote):
        status = quote.get("status", "Unknown")
        if status == "Unavailable":
            return "unavailable"
        if quote.get("stale"):
            return "stale"
        if status == "Closed":
            return "closed"
        return "fresh"

    def _watch_note(self, symbol, change_percent):
        upper = symbol.upper()
        if upper in ("NVDA", "AMD", "QQQ", "TSLA", "PLTR"):
            return "Watch Nasdaq futures, AI headlines, chip news, and volume."
        if upper in ("RTX", "LMT"):
            return "Watch geopolitics, defense headlines, and broad market risk."
        if upper in ("XOM", "CVX"):
            return "Watch oil, OPEC, Iran/Russia headlines, and energy sector moves."
        if upper == "TSN":
            return "Watch Tyson news, food inflation, labor/plant headlines, and abnormal volume."
        if "BTC" in upper or "ETH" in upper:
            return "Watch crypto headlines, ETF flows, Coinbase, and risk appetite."
        if upper in ("SPY", "DIA", "IWM"):
            return "Watch VIX, rates, Fed headlines, and broad market breadth."
        return "Check the headline reason and confirm price/volume before acting."

    def _news_watch_note(self, symbol):
        upper = symbol.upper()
        if upper in ("NVDA", "AMD"):
            return "Confirm if this is AI/chip demand, earnings, guidance, export controls, or analyst news."
        if upper in ("TSLA", "PLTR"):
            return "Confirm if this is contracts, demand, deliveries, AI, government work, or analyst news."
        if upper in ("RTX", "LMT"):
            return "Confirm if this connects to defense spending, war, missiles, contracts, or Congress."
        if upper in ("XOM", "CVX"):
            return "Confirm if oil prices, OPEC, sanctions, or geopolitical supply risk are moving."
        if upper == "TSN":
            return "Confirm if this is Tyson-specific, food inflation, labor, plant, demand, or guidance news."
        if upper in ("SPY", "QQQ"):
            return "Check futures, VIX, rates, and whether this is broad market-moving news."
        if "BTC" in upper or "ETH" in upper:
            return "Check crypto price, ETF flows, Coinbase, and broader risk appetite."
        return "Verify the headline and check price/volume reaction before acting."

    def _load_symbols(self):
        saved_symbols = self._saved_symbols()
        if saved_symbols:
            return saved_symbols
        return self._env_symbols() or list(self.DEFAULT_SYMBOLS)

    def _env_symbols(self):
        raw = os.getenv("WATCHLIST_SYMBOLS")
        if not raw:
            return []
        symbols = []
        for item in raw.split(","):
            symbol = self._normalize_symbol(item)
            if symbol and symbol not in symbols:
                symbols.append(symbol)
        return symbols

    def _saved_symbols(self):
        if not self.symbol_store_path.exists():
            return []
        try:
            with self.symbol_store_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except Exception:
            return []
        raw_symbols = data.get("symbols", []) if isinstance(data, dict) else []
        symbols = []
        for item in raw_symbols:
            symbol = self._normalize_symbol(item)
            if symbol and symbol not in symbols:
                symbols.append(symbol)
        return symbols

    def _save_symbols(self):
        self.symbol_store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"symbols": self.symbols, "updated": self._timestamp(), "note": "Created by MarketOps !watch / !unwatch commands."}
        with self.symbol_store_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2)

    def _normalize_symbol(self, symbol):
        clean = (symbol or "").strip().upper().replace("$", "").replace(" ", "")
        aliases = {
            "BTCUSD": "BTC-USD",
            "BITCOIN": "BTC-USD",
            "ETHUSD": "ETH-USD",
            "ETHEREUM": "ETH-USD",
            "GOLD": "GC=F",
            "GC": "GC=F",
            "OIL": "CL=F",
            "WTI": "CL=F",
            "ES": "ES=F",
            "NQ": "NQ=F",
            "VIX": "^VIX",
            "US10Y": "^TNX",
            "10Y": "^TNX",
        }
        return aliases.get(clean, clean)

    def _load_settings(self):
        if not self.settings_store_path.exists():
            return {}
        try:
            with self.settings_store_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_settings(self):
        self.settings_store_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings["updated"] = self._timestamp()
        with self.settings_store_path.open("w", encoding="utf-8") as file:
            json.dump(self.settings, file, indent=2)

    def _setting_bool(self, key, env_name, default):
        if key in self.settings:
            return bool(self.settings[key])
        return self._env_bool(env_name, default=default)

    def _setting_float(self, key, env_name, default):
        if key in self.settings:
            return self._safe_float(self.settings[key]) or default
        return self._safe_float(os.getenv(env_name, default)) or default

    def _load_alert_memory(self):
        if not self.alert_store_path.exists():
            return {}
        try:
            with self.alert_store_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_alert_memory(self):
        self.alert_store_path.parent.mkdir(parents=True, exist_ok=True)
        with self.alert_store_path.open("w", encoding="utf-8") as file:
            json.dump(self.alert_memory, file, indent=2)

    def _safe_float(self, value):
        try:
            result = float(value)
        except (TypeError, ValueError):
            return 0.0
        if math.isnan(result) or math.isinf(result):
            return 0.0
        return result

    def _price_text(self, price, kind):
        if kind == "crypto":
            return f"${price:,.0f}"
        return f"${price:,.2f}"

    def _matches_any(self, text, terms):
        return any(self._term_match(text, term) for term in terms)

    def _term_match(self, text, term):
        clean = (term or "").strip().lower()
        if not clean:
            return False
        if " " in clean or "-" in clean or "&" in clean:
            return clean in text
        return f" {clean} " in f" {text} "

    def _contains_any(self, text, terms):
        value = text or ""
        return any(term in value for term in terms)

    def _dedupe_news_items(self, items):
        seen = set()
        deduped = []
        for item in items:
            key = self._article_id(item)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _article_id(self, item):
        value = item.get("link") or item.get("title", "")
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]

    def _age_label(self, published_dt):
        if published_dt is None:
            return "Unknown"
        try:
            now = datetime.now(ZoneInfo("UTC"))
            if published_dt.tzinfo is None:
                published_dt = published_dt.replace(tzinfo=ZoneInfo("UTC"))
            minutes = max(0, int((now - published_dt.astimezone(ZoneInfo("UTC"))).total_seconds() // 60))
        except Exception:
            return "Unknown"
        if minutes < 1:
            return "just now"
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        remaining = minutes % 60
        return f"{hours}h ago" if remaining == 0 else f"{hours}h {remaining}m ago"

    def _today_key(self):
        return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")

    def _timestamp(self):
        return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%I:%M %p PT").lstrip("0")

    def _env_bool(self, name, default=False):
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in ("1", "true", "yes", "y", "on")
