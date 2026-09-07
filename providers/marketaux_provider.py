import os
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv()


class MarketauxProvider:
    """Fetches optional market news from Marketaux.

    Marketaux is optional. If the API key is missing, timed out, over quota,
    or payment-required, MarketOps falls back to RSS instead of crashing.
    """

    BASE_URL = "https://api.marketaux.com/v1/news/all"

    DEFAULT_SYMBOLS = [
        "SPY",
        "QQQ",
        "DIA",
        "IWM",
        "AAPL",
        "MSFT",
        "NVDA",
        "AMD",
        "AMZN",
        "GOOGL",
        "META",
        "TSLA",
        "XOM",
        "CVX",
        "LMT",
        "RTX",
        "BTC",
        "ETH",
    ]

    DEFAULT_DOMAINS = []

    def __init__(self):
        self.api_key = os.getenv("MARKETAUX_API_KEY") or os.getenv("MARKETAUX_API_TOKEN")
        self.enabled = bool(self.api_key)
        self.disabled_reason = ""
        self.timeout = int(os.getenv("MARKETAUX_TIMEOUT_SECONDS", "10"))
        self.limit = int(os.getenv("MARKETAUX_LIMIT", "10"))
        self.countries = os.getenv("MARKETAUX_COUNTRIES", "us")
        self.language = os.getenv("MARKETAUX_LANGUAGE", "en")
        self.domains = self._load_csv("MARKETAUX_DOMAINS", self.DEFAULT_DOMAINS)
        self.symbols = self._load_csv("MARKETAUX_SYMBOLS", self.DEFAULT_SYMBOLS)
        self.lookback = os.getenv("NEWS_LOOKBACK", "2h")
        self.filter_entities = self._env_bool("MARKETAUX_FILTER_ENTITIES", default=False)
        self.last_status = "Not checked yet"
        self.last_count = 0

    def get_latest_news(self, limit=25):
        if not self.enabled:
            self.last_status = self.disabled_reason or "OFF: MARKETAUX_API_KEY missing"
            return []

        request_limit = min(max(1, limit), self.limit)

        params = {
            "api_token": self.api_key,
            "language": self.language,
            "countries": self.countries,
            "limit": request_limit,
            "published_after": self._published_after(),
        }

        if self.filter_entities:
            params["filter_entities"] = "true"

        if self.domains:
            params["domains"] = ",".join(self.domains)

        if self.symbols:
            params["symbols"] = ",".join(self.symbols)

        try:
            response = requests.get(self.BASE_URL, params=params, timeout=self.timeout)

            if response.status_code == 402:
                self.enabled = False
                self.disabled_reason = "OFF: Marketaux returned 402 Payment Required / quota issue"
                self.last_status = self.disabled_reason
                print("⚠️ Marketaux disabled: 402 Payment Required / quota issue. Using RSS fallback.")
                return []

            if response.status_code == 401:
                self.enabled = False
                self.disabled_reason = "OFF: Marketaux returned 401 Unauthorized / bad API key"
                self.last_status = self.disabled_reason
                print("⚠️ Marketaux disabled: 401 Unauthorized. Rotate/check MARKETAUX_API_KEY. Using RSS fallback.")
                return []

            response.raise_for_status()
            payload = response.json()
            articles = self._extract_articles(payload)
            self.last_count = len(articles)
            self.last_status = f"OK: {self.last_count} raw article(s) returned"

            return [self._normalize_article(article) for article in articles]

        except requests.exceptions.Timeout:
            self.last_status = "ERROR: timeout"
            print("⚠️ Marketaux timeout. Using RSS fallback.")
            return []

        except requests.exceptions.HTTPError as error:
            status_code = getattr(error.response, "status_code", "unknown")
            self.last_status = f"ERROR: HTTP {status_code}"
            print(f"⚠️ Marketaux HTTP error {status_code}. Using RSS fallback.")
            return []

        except requests.exceptions.RequestException as error:
            self.last_status = f"ERROR: {error.__class__.__name__}"
            print(f"⚠️ Marketaux connection error: {error.__class__.__name__}. Using RSS fallback.")
            return []

        except Exception as error:
            self.last_status = f"ERROR: {error.__class__.__name__}"
            print(f"⚠️ Marketaux unexpected error: {error.__class__.__name__}. Using RSS fallback.")
            return []

    def source_policy(self):
        if not self.enabled:
            return f"Marketaux is OFF. {self.disabled_reason or 'MARKETAUX_API_KEY missing.'}"

        return (
            "Marketaux mode is ON. MarketOps checks Marketaux first for market-news API coverage. "
            f"Last Marketaux status: {self.last_status}."
        )

    def _extract_articles(self, payload):
        if isinstance(payload, list):
            return payload

        if not isinstance(payload, dict):
            return []

        value = payload.get("data")
        if isinstance(value, list):
            return value

        for key in ("articles", "results", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value

        return []

    def _normalize_article(self, article):
        title = self._first_string(article, ["title", "headline", "name"], default="Untitled")
        link = self._first_string(article, ["url", "link", "article_url", "articleUrl"])
        summary = self._first_string(article, ["description", "snippet", "summary", "text"])
        published_raw = self._first_string(
            article,
            ["published_at", "publishedAt", "published", "published_date", "date"],
        )
        source = self._source_name(article)

        return {
            "source": source,
            "title": title,
            "link": link,
            "summary": summary,
            "published": published_raw,
            "published_dt": self._parse_date(published_raw),
            "category_hint": None,
            "trusted": True,
            "provider": "Marketaux",
        }

    def _source_name(self, article):
        source = article.get("source")

        if isinstance(source, str) and source.strip():
            return source.strip()

        if isinstance(source, dict):
            for key in ("name", "domain", "url", "site"):
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        for key in ("source_name", "sourceName", "publisher", "domain"):
            value = article.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        return "Marketaux"

    def _first_string(self, article, keys, default=""):
        for key in keys:
            value = article.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        return default

    def _parse_date(self, value):
        if not value:
            return None

        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except Exception:
            return None

    def _published_after(self):
        delta = self._lookback_delta(self.lookback)
        published_after = datetime.now(timezone.utc) - delta
        return published_after.strftime("%Y-%m-%dT%H:%M")

    def _lookback_delta(self, value):
        value = (value or "2h").strip().lower()

        try:
            if value.endswith("m"):
                return timedelta(minutes=int(value[:-1]))
            if value.endswith("h"):
                return timedelta(hours=int(value[:-1]))
            if value.endswith("d"):
                return timedelta(days=int(value[:-1]))
        except Exception:
            pass

        return timedelta(hours=2)

    def _load_csv(self, name, default):
        raw = os.getenv(name)

        if raw is None:
            return list(default)

        values = []
        for item in raw.split(","):
            cleaned = item.strip()
            if cleaned:
                values.append(cleaned)

        return values

    def _env_bool(self, name, default=False):
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in ("1", "true", "yes", "y", "on")
