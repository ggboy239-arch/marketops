import os
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()


class FinlightProvider:
    """Fetches fresher market news from Finlight's REST API.

    This provider is optional. If FINLIGHT_API_KEY is missing, MarketOps will
    keep using the Reuters-focused RSS provider.
    """

    BASE_URL = "https://api.finlight.me/v2/articles"

    DEFAULT_SOURCES = [
        "www.reuters.com",
        "www.benzinga.com",
        "www.apnews.com",
        "www.cnbc.com",
        "www.marketwatch.com",
    ]

    DEFAULT_QUERY = (
        'markets OR futures OR stocks OR "S&P 500" OR Nasdaq OR Fed OR Powell '
        'OR inflation OR Treasury OR oil OR OPEC OR Iran OR Israel OR Ukraine '
        'OR China OR Taiwan OR Nvidia OR AMD OR Microsoft OR bitcoin OR crypto'
    )

    def __init__(self):
        self.api_key = os.getenv("FINLIGHT_API_KEY")
        self.query = os.getenv("FINLIGHT_QUERY", self.DEFAULT_QUERY)
        self.sources = self._load_sources()
        self.enabled = bool(self.api_key)
        self.timeout = int(os.getenv("FINLIGHT_TIMEOUT_SECONDS", "10"))

    def get_latest_news(self, limit=25):
        if not self.enabled:
            return []

        try:
            response = requests.post(
                self.BASE_URL,
                headers={
                    "accept": "application/json",
                    "Content-Type": "application/json",
                    "X-API-KEY": self.api_key,
                },
                json={
                    "query": self.query,
                    "sources": self.sources,
                    "language": "en",
                    "order": "DESC",
                    "pageSize": limit,
                    "page": 1,
                    "includeEntities": True,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            articles = self._extract_articles(payload)

            return [self._normalize_article(article) for article in articles]

        except Exception as error:
            print(f"❌ Finlight API error: {error}")
            return []

    def source_policy(self):
        if not self.enabled:
            return (
                "Finlight is OFF because FINLIGHT_API_KEY is missing. "
                "MarketOps is using Reuters-focused RSS fallback."
            )

        source_text = ", ".join(self.sources)
        return (
            "Finlight REST mode is ON. MarketOps is checking Finlight for fresh "
            f"market news from these sources: {source_text}."
        )

    def _load_sources(self):
        raw_sources = os.getenv("FINLIGHT_SOURCES")

        if not raw_sources:
            return self.DEFAULT_SOURCES

        sources = []
        for source in raw_sources.split(","):
            cleaned = source.strip()
            if cleaned:
                sources.append(cleaned)

        return sources or self.DEFAULT_SOURCES

    def _extract_articles(self, payload):
        if isinstance(payload, list):
            return payload

        if not isinstance(payload, dict):
            return []

        for key in ("articles", "data", "results", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value

        return []

    def _normalize_article(self, article):
        title = self._first_string(
            article,
            ["title", "headline", "name"],
            default="Untitled",
        )
        link = self._first_string(
            article,
            ["link", "url", "articleUrl", "article_url"],
        )
        summary = self._first_string(
            article,
            ["summary", "description", "snippet", "text"],
        )
        published_raw = self._first_string(
            article,
            [
                "publishedAt",
                "published_at",
                "publishedDate",
                "published_date",
                "published",
                "date",
                "createdAt",
                "created_at",
            ],
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
            "provider": "Finlight",
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

        for key in ("sourceName", "source_name", "publisher", "domain"):
            value = article.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        return "Finlight"

    def _first_string(self, article, keys, default=""):
        for key in keys:
            value = article.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        return default

    def _parse_date(self, value):
        if not value:
            return None

        value = value.strip()

        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None
