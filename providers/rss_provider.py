import html
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests
from dotenv import load_dotenv

load_dotenv()


class RSSProvider:
    """Fetches trusted public RSS feeds for MarketOps news.

    Provider job: go outside the app, get raw news items, verify the source,
    and return clean data. It does not decide market impact. That job belongs
    to NewsEngine.
    """

    REUTERS_ENV_FEEDS = [
        ("Reuters Markets", "REUTERS_MARKETS_RSS", "📊 Broad Market"),
        ("Reuters Business", "REUTERS_BUSINESS_RSS", "📊 Broad Market"),
        ("Reuters Technology", "REUTERS_TECH_RSS", "🤖 AI / Tech"),
        ("Reuters World", "REUTERS_WORLD_RSS", "🛢 Oil / Geopolitics"),
        ("Reuters Crypto", "REUTERS_CRYPTO_RSS", "₿ Crypto"),
        ("Reuters Fed / Rates", "REUTERS_FED_RSS", "🏦 Fed / Rates"),
    ]

    REUTERS_SEARCH_FEEDS = [
        {
            "name": "Reuters Markets",
            "query": 'site:reuters.com/markets (stocks OR futures OR "Wall Street" OR Nasdaq OR "S&P 500" OR "global markets")',
            "category_hint": "📊 Broad Market",
        },
        {
            "name": "Reuters AI / Tech",
            "query": 'site:reuters.com (AI OR "artificial intelligence" OR Nvidia OR AMD OR semiconductor OR chips OR Microsoft OR Amazon OR Apple)',
            "category_hint": "🤖 AI / Tech",
        },
        {
            "name": "Reuters Fed / Rates",
            "query": 'site:reuters.com (Fed OR "Federal Reserve" OR Powell OR inflation OR CPI OR PPI OR yields OR Treasury OR jobs OR payroll)',
            "category_hint": "🏦 Fed / Rates",
        },
        {
            "name": "Reuters Oil / Geopolitics",
            "query": 'site:reuters.com (oil OR crude OR OPEC OR Iran OR Israel OR Lebanon OR Hezbollah OR Hormuz OR Ukraine OR China OR Taiwan OR NATO)',
            "category_hint": "🛢 Oil / Geopolitics",
        },
        {
            "name": "Reuters Crypto",
            "query": 'site:reuters.com (bitcoin OR crypto OR ethereum OR Coinbase OR "spot bitcoin ETF" OR "ether ETF")',
            "category_hint": "₿ Crypto",
        },
    ]

    EXTRA_FEEDS = [
        {
            "name": "Yahoo Finance",
            "url": "https://finance.yahoo.com/news/rssindex",
            "category_hint": "📊 Broad Market",
        },
        {
            "name": "CNBC Top News",
            "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
            "category_hint": "📊 Broad Market",
        },
    ]

    def __init__(self, feeds=None):
        self.reuters_only = self._env_bool("NEWS_REUTERS_ONLY", default=True)
        self.include_extra_sources = self._env_bool(
            "NEWS_INCLUDE_EXTRA_SOURCES",
            default=False,
        )
        self.lookback = os.getenv("NEWS_LOOKBACK", "6h")
        self.feeds = feeds or self._load_feeds()
        self.headers = {
            "User-Agent": "MarketOps/0.5.5 (trusted near-live market news monitor)",
        }

    def get_latest_news(self, limit=10):
        items = []

        for feed in self.feeds:
            items.extend(self._fetch_feed(feed))

        items = self._deduplicate(items)
        items = self._sort_items(items)

        return items[:limit]

    def source_policy(self):
        if self.reuters_only:
            return (
                "Reuters-only mode is ON. MarketOps keeps only headlines that "
                "can be verified as Reuters results from the RSS item source/title. "
                f"Current search lookback: {self.lookback}."
            )

        return (
            "Reuters-only mode is OFF. MarketOps also allows approved extra "
            "sources like Yahoo Finance and CNBC if NEWS_INCLUDE_EXTRA_SOURCES=true. "
            f"Current search lookback: {self.lookback}."
        )

    def _load_feeds(self):
        feeds = []

        for name, env_name, category_hint in self.REUTERS_ENV_FEEDS:
            url = os.getenv(env_name)

            if url:
                feeds.append(
                    {
                        "name": name,
                        "url": url,
                        "category_hint": category_hint,
                        "trusted_source": "Reuters",
                    }
                )

        for feed in self.REUTERS_SEARCH_FEEDS:
            feeds.append(
                {
                    "name": feed["name"],
                    "url": self._google_news_rss(feed["query"]),
                    "category_hint": feed["category_hint"],
                    "trusted_source": "Reuters",
                }
            )

        if self.include_extra_sources and not self.reuters_only:
            feeds.extend(self.EXTRA_FEEDS)

        return feeds

    def _google_news_rss(self, query):
        query_with_recency = f"{query} when:{self.lookback}"
        encoded_query = quote_plus(query_with_recency)
        return (
            "https://news.google.com/rss/search"
            f"?q={encoded_query}"
            "&hl=en-US&gl=US&ceid=US:en"
        )

    def _fetch_feed(self, feed):
        try:
            response = requests.get(
                feed["url"],
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()

            return self._parse_rss(
                feed=feed,
                text=response.text,
            )

        except Exception as error:
            print(f"❌ RSS error from {feed['name']}: {error}")
            return []

    def _parse_rss(self, feed, text):
        root = ET.fromstring(text)
        items = []

        rss_items = root.findall(".//item")

        if rss_items:
            for item in rss_items:
                parsed = self._parse_rss_item(feed, item)
                if parsed is not None:
                    items.append(parsed)

            return items

        atom_items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

        for item in atom_items:
            parsed = self._parse_atom_item(feed, item)
            if parsed is not None:
                items.append(parsed)

        return items

    def _parse_rss_item(self, feed, item):
        raw_title = self._find_text(item, "title")
        link = self._find_text(item, "link")
        description = self._find_text(item, "description")
        published = self._find_text(item, "pubDate")
        item_source = self._find_text(item, "source")

        if not raw_title:
            return None

        if not self._is_trusted_item(feed, raw_title, link, item_source):
            return None

        return {
            "source": self._source_name(feed, item_source),
            "title": self._clean_google_news_title(self._clean_text(raw_title)),
            "link": link or "",
            "summary": self._clean_text(description or ""),
            "published": published or "",
            "published_dt": self._parse_date(published),
            "category_hint": feed.get("category_hint"),
            "trusted": True,
        }

    def _parse_atom_item(self, feed, item):
        raw_title = self._find_text(item, "{http://www.w3.org/2005/Atom}title")
        summary = self._find_text(item, "{http://www.w3.org/2005/Atom}summary")
        updated = self._find_text(item, "{http://www.w3.org/2005/Atom}updated")
        link = ""

        link_element = item.find("{http://www.w3.org/2005/Atom}link")
        if link_element is not None:
            link = link_element.attrib.get("href", "")

        if not raw_title:
            return None

        if not self._is_trusted_item(feed, raw_title, link, ""):
            return None

        return {
            "source": feed["name"],
            "title": self._clean_google_news_title(self._clean_text(raw_title)),
            "link": link,
            "summary": self._clean_text(summary or ""),
            "published": updated or "",
            "published_dt": self._parse_date(updated),
            "category_hint": feed.get("category_hint"),
            "trusted": True,
        }

    def _is_trusted_item(self, feed, title, link, item_source):
        trusted_source = feed.get("trusted_source")

        if not trusted_source:
            return not self.reuters_only

        text = f"{title} {link} {item_source}".lower()

        if trusted_source.lower() == "reuters":
            return "reuters" in text

        return trusted_source.lower() in text

    def _source_name(self, feed, item_source):
        if item_source and "reuters" in item_source.lower():
            return feed["name"]

        return feed["name"]

    def _find_text(self, item, tag):
        element = item.find(tag)

        if element is None or element.text is None:
            return ""

        return element.text.strip()

    def _clean_text(self, value):
        value = html.unescape(value or "")
        value = re.sub(r"<[^>]+>", "", value)
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    def _clean_google_news_title(self, title):
        return re.sub(r"\s+-\s+Reuters$", "", title).strip()

    def _parse_date(self, value):
        if not value:
            return None

        try:
            return parsedate_to_datetime(value)
        except Exception:
            pass

        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None

    def _deduplicate(self, items):
        seen = set()
        unique_items = []

        for item in items:
            title = item.get("title", "").lower()
            link = item.get("link", "")
            key = (title, link)

            if key in seen:
                continue

            seen.add(key)
            unique_items.append(item)

        return unique_items

    def _sort_items(self, items):
        return sorted(
            items,
            key=lambda item: item.get("published_dt") or datetime.min,
            reverse=True,
        )

    def _env_bool(self, name, default=False):
        value = os.getenv(name)

        if value is None:
            return default

        return value.strip().lower() in ("1", "true", "yes", "y", "on")
