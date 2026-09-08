import html
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests
from dotenv import load_dotenv

load_dotenv()


class RSSProvider:
    """Fetches trusted public RSS feeds for MarketOps news.

    Reuters stays the main source. Major AP/NPR/CNBC/BBC feeds are second
    data points. Yahoo Finance direct feed is off by default because it can
    flood #breaking-news with stock-pick articles and stock-price pages.
    """

    REUTERS_ENV_FEEDS = [
        ("Reuters Markets", "REUTERS_MARKETS_RSS", "📊 Broad Market"),
        ("Reuters Business", "REUTERS_BUSINESS_RSS", "🗞 General News"),
        ("Reuters General", "REUTERS_GENERAL_RSS", "🗞 General News"),
        ("Reuters US", "REUTERS_US_RSS", "🗞 General News"),
        ("Reuters Technology", "REUTERS_TECH_RSS", "🤖 AI / Tech"),
        ("Reuters World", "REUTERS_WORLD_RSS", "🛢 Oil / Geopolitics"),
        ("Reuters Crypto", "REUTERS_CRYPTO_RSS", "₿ Crypto"),
        ("Reuters Fed / Rates", "REUTERS_FED_RSS", "🏦 Fed / Rates"),
    ]

    REUTERS_SEARCH_FEEDS = [
        {
            "name": "Reuters Markets",
            "query": 'site:reuters.com/markets ("stock futures" OR "Wall Street" OR "S&P 500" OR "Nasdaq" OR "Dow" OR "global markets" OR yields OR "oil prices" OR "market wrap")',
            "category_hint": "📊 Broad Market",
            "trusted_source": "Reuters",
            "trusted_aliases": ["reuters"],
        },
        {
            "name": "Reuters General News",
            "query": 'site:reuters.com ("White House" OR Congress OR "Supreme Court" OR election OR cyberattack OR hurricane OR wildfire OR strike OR "national emergency" OR tariff OR sanctions OR "supply chain" OR antitrust OR lawsuit OR regulation OR layoffs OR "job cuts")',
            "category_hint": "🗞 General News",
            "trusted_source": "Reuters",
            "trusted_aliases": ["reuters"],
        },
        {
            "name": "Reuters AI / Tech",
            "query": 'site:reuters.com (AI OR "artificial intelligence" OR Nvidia OR AMD OR semiconductor OR chips OR GPU OR "data center" OR OpenAI)',
            "category_hint": "🤖 AI / Tech",
            "trusted_source": "Reuters",
            "trusted_aliases": ["reuters"],
        },
        {
            "name": "Reuters Fed / Rates",
            "query": 'site:reuters.com (Fed OR "Federal Reserve" OR Powell OR inflation OR CPI OR PPI OR PCE OR yields OR Treasury OR jobs OR payroll OR "rate cut" OR "rate hike" OR "jobless claims")',
            "category_hint": "🏦 Fed / Rates",
            "trusted_source": "Reuters",
            "trusted_aliases": ["reuters"],
        },
        {
            "name": "Reuters Oil / Geopolitics",
            "query": 'site:reuters.com (oil OR crude OR OPEC OR Iran OR Israel OR Lebanon OR Hezbollah OR Hormuz OR Ukraine OR Russia OR China OR Taiwan OR NATO OR sanctions OR missile OR attack OR tariff)',
            "category_hint": "🛢 Oil / Geopolitics",
            "trusted_source": "Reuters",
            "trusted_aliases": ["reuters"],
        },
        {
            "name": "Reuters Crypto",
            "query": 'site:reuters.com (bitcoin OR crypto OR ethereum OR Coinbase OR "spot bitcoin ETF" OR "ether ETF")',
            "category_hint": "₿ Crypto",
            "trusted_source": "Reuters",
            "trusted_aliases": ["reuters"],
        },
    ]

    MAJOR_SEARCH_FEEDS = [
        {
            "name": "AP Major News",
            "query": 'site:apnews.com ("White House" OR Congress OR "Supreme Court" OR Fed OR inflation OR jobs OR oil OR Iran OR Israel OR Russia OR Ukraine OR China OR Taiwan OR tariff OR sanctions OR cyberattack OR strike OR lawsuit OR antitrust OR "supply chain" OR banking OR "data breach" OR layoffs OR "job cuts")',
            "category_hint": "🗞 General News",
            "trusted_source": "AP News",
            "trusted_aliases": ["ap news", "associated press", "apnews"],
        },
        {
            "name": "NPR Major News",
            "query": 'site:npr.org (economy OR politics OR "White House" OR Congress OR "Supreme Court" OR Fed OR inflation OR jobs OR oil OR tariff OR sanctions OR cyberattack OR strike OR lawsuit OR "supply chain")',
            "category_hint": "🗞 General News",
            "trusted_source": "NPR",
            "trusted_aliases": ["npr", "npr.org"],
        },
        {
            "name": "CNBC Market/Major News",
            "query": 'site:cnbc.com ("stock futures" OR "Wall Street" OR "S&P 500" OR Nasdaq OR "Dow" OR Fed OR inflation OR oil OR tariff OR "White House" OR "Supreme Court" OR cyberattack OR strike OR layoffs OR "job cuts" OR "cuts outlook" OR "earnings warning")',
            "category_hint": "📊 Broad Market",
            "trusted_source": "CNBC",
            "trusted_aliases": ["cnbc"],
        },
        {
            "name": "BBC US/World News",
            "query": 'site:bbc.com/news OR site:bbc.co.uk/news (US OR "United States" OR China OR Russia OR Ukraine OR Iran OR Israel OR oil OR tariffs OR sanctions OR cyberattack)',
            "category_hint": "🗞 General News",
            "trusted_source": "BBC",
            "trusted_aliases": ["bbc"],
        },
    ]

    MAJOR_DIRECT_FEEDS = [
        {
            "name": "NPR Top Stories",
            "url": "https://feeds.npr.org/1001/rss.xml",
            "category_hint": "🗞 General News",
            "trusted_source": "NPR",
            "trusted_aliases": ["npr", "npr.org"],
        },
        {
            "name": "CNBC Top News",
            "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
            "category_hint": "🗞 General News",
            "trusted_source": "CNBC",
            "trusted_aliases": ["cnbc"],
        },
        {
            "name": "BBC US & Canada",
            "url": "https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml",
            "category_hint": "🗞 General News",
            "trusted_source": "BBC",
            "trusted_aliases": ["bbc", "bbc.co.uk", "bbc.com"],
        },
    ]

    YAHOO_DIRECT_FEED = {
        "name": "Yahoo Finance",
        "url": "https://finance.yahoo.com/news/rssindex",
        "category_hint": "🗞 General News",
        "trusted_source": "Yahoo Finance",
        "trusted_aliases": ["yahoo finance", "finance.yahoo"],
    }

    EXTRA_FEEDS = [
        {
            "name": "Yahoo Finance",
            "url": "https://finance.yahoo.com/news/rssindex",
            "category_hint": "🗞 General News",
            "trusted_source": "Yahoo Finance",
            "trusted_aliases": ["yahoo finance", "finance.yahoo"],
        },
    ]

    def __init__(self, feeds=None):
        self.reuters_only = self._env_bool("NEWS_REUTERS_ONLY", default=True)
        self.include_major_sources = self._env_bool("NEWS_INCLUDE_MAJOR_SOURCES", default=True)
        self.include_extra_sources = self._env_bool("NEWS_INCLUDE_EXTRA_SOURCES", default=False)
        self.include_yahoo_direct = self._env_bool("NEWS_INCLUDE_YAHOO_DIRECT", default=False)
        # This is NOT the delay. It is only the search window used to find fresh items.
        self.lookback = os.getenv("NEWS_LOOKBACK", "2h")
        self.feeds = feeds or self._load_feeds()
        self.headers = {
            "User-Agent": "MarketOps/0.7.8 (strict breaking-news RSS monitor)",
        }

    def get_latest_news(self, limit=10):
        items = []

        for feed in self.feeds:
            items.extend(self._fetch_feed(feed))

        items = self._deduplicate(items)
        items = self._sort_items(items)

        return items[:limit]

    def source_policy(self):
        reuters_mode = "ON" if self.reuters_only else "OFF"
        major_mode = "ON" if self.include_major_sources else "OFF"
        yahoo_mode = "ON" if self.include_yahoo_direct else "OFF"
        return (
            f"Reuters-only verification is {reuters_mode}. "
            f"Major-source mode is {major_mode}: Reuters/AP/NPR/CNBC/BBC are used as core feeds. "
            f"Yahoo Finance direct feed is {yahoo_mode}; it stays OFF by default to avoid stock-pick and stock-price-page noise. "
            f"Search lookback is {self.lookback}; this is a search window, not a delay."
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
                        "trusted_aliases": ["reuters"],
                    }
                )

        for feed in self.REUTERS_SEARCH_FEEDS:
            feeds.append(
                {
                    "name": feed["name"],
                    "url": self._google_news_rss(feed["query"]),
                    "category_hint": feed["category_hint"],
                    "trusted_source": feed["trusted_source"],
                    "trusted_aliases": feed.get("trusted_aliases", ["reuters"]),
                }
            )

        if self.include_major_sources:
            for feed in self.MAJOR_SEARCH_FEEDS:
                feeds.append(
                    {
                        "name": feed["name"],
                        "url": self._google_news_rss(feed["query"]),
                        "category_hint": feed["category_hint"],
                        "trusted_source": feed["trusted_source"],
                        "trusted_aliases": feed.get("trusted_aliases", []),
                    }
                )
            feeds.extend(self.MAJOR_DIRECT_FEEDS)

        if self.include_yahoo_direct:
            feeds.append(self.YAHOO_DIRECT_FEED)

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

            return self._parse_rss(feed=feed, text=response.text)

        except Exception as error:
            print(f"❌ RSS error from {feed['name']}: {error}")
            return []

    def _parse_rss(self, feed, text):
        root = ET.fromstring(text)
        items = []

        for item in root.findall(".//item"):
            parsed = self._parse_rss_item(feed, item)
            if parsed is not None:
                items.append(parsed)

        for item in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
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
            "feed_name": feed["name"],
            "title": self._clean_google_news_title(self._clean_text(raw_title)),
            "link": link or "",
            "summary": self._clean_text(description or ""),
            "published": published or "",
            "published_dt": self._parse_date(published),
            "category_hint": feed.get("category_hint"),
            "trusted": True,
            "provider": "RSS",
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
            "source": self._source_name(feed, ""),
            "feed_name": feed["name"],
            "title": self._clean_google_news_title(self._clean_text(raw_title)),
            "link": link,
            "summary": self._clean_text(summary or ""),
            "published": updated or "",
            "published_dt": self._parse_date(updated),
            "category_hint": feed.get("category_hint"),
            "trusted": True,
            "provider": "RSS",
        }

    def _is_trusted_item(self, feed, title, link, item_source):
        trusted_source = feed.get("trusted_source")
        aliases = [alias.lower() for alias in feed.get("trusted_aliases", []) if alias]

        if not trusted_source and not aliases:
            return not self.reuters_only

        text = f"{title} {link} {item_source} {feed.get('name', '')}".lower()
        if trusted_source:
            aliases.append(str(trusted_source).lower())

        return any(alias in text for alias in aliases)

    def _source_name(self, feed, item_source):
        if item_source:
            return item_source

        if feed.get("trusted_source"):
            return feed.get("trusted_source")

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
        title = re.sub(r"\s+-\s+Reuters$", "", title).strip()
        title = re.sub(r"\s+-\s+reuters\.com$", "", title, flags=re.IGNORECASE).strip()
        title = re.sub(r"\s+-\s+AP News$", "", title).strip()
        title = re.sub(r"\s+-\s+NPR$", "", title).strip()
        title = re.sub(r"\s+-\s+CNBC$", "", title).strip()
        title = re.sub(r"\s+-\s+cnbc\.com$", "", title, flags=re.IGNORECASE).strip()
        title = re.sub(r"\s+-\s+BBC$", "", title).strip()
        title = re.sub(r"\s+-\s+Yahoo Finance$", "", title).strip()
        return title

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
            title = self._title_key(item.get("title", ""))
            link = item.get("link", "")
            key = title or link

            if key in seen:
                continue

            seen.add(key)
            unique_items.append(item)

        return unique_items

    def _title_key(self, title):
        value = (title or "").lower()
        value = re.sub(r"\s+-\s+(reuters|reuters\.com|ap news|npr|cnbc|cnbc\.com|bbc|yahoo finance)$", "", value)
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    def _sort_items(self, items):
        def sort_key(item):
            value = item.get("published_dt")
            if value is None:
                return datetime.min.replace(tzinfo=timezone.utc)
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)

        return sorted(items, key=sort_key, reverse=True)

    def _env_bool(self, name, default=False):
        value = os.getenv(name)

        if value is None:
            return default

        return value.strip().lower() in ("1", "true", "yes", "y", "on")
