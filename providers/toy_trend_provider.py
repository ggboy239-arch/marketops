import html
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests


class ToyTrendProvider:
    """Public headline monitor for toy demand catalysts.

    Headlines are watch signals, not profit claims. Exact ASIN confirmation is
    deliberately left to the Keepa lead scanner.
    """

    QUERIES = (
        '(toy OR doll OR action figure OR collectible) ("new release" OR launch OR preorder OR exclusive)',
        '(toy OR doll OR collectible) (viral OR TikTok OR YouTube OR "Google Trends")',
        'site:toybook.com (licensing OR movie OR streaming OR toys OR "new products")',
        'site:licenseglobal.com (toys OR licensing OR movie OR streaming OR franchise)',
        '(Mattel OR Barbie OR "Hot Wheels" OR Hasbro OR Jazwares OR "Spin Master" OR Funko OR Loungefly) (launch OR exclusive OR movie OR viral)',
    )

    def __init__(self):
        self.timeout = int(os.getenv("TOY_TRENDS_TIMEOUT_SECONDS", "15"))
        self.lookback = os.getenv("TOY_TRENDS_LOOKBACK", "7d")
        self.youtube_feeds = [
            value.strip() for value in os.getenv("TOY_YOUTUBE_FEEDS", "").split(",") if value.strip()
        ]
        self.headers = {"User-Agent": "MarketOps/1.0 toy-trend monitor"}

    def latest(self, limit=20):
        items = []
        for query in self.QUERIES:
            items.extend(self._fetch(self._google_news_url(query), "Google News"))
        for url in self.youtube_feeds:
            items.extend(self._fetch(url, "YouTube"))
        unique = {}
        for item in items:
            key = re.sub(r"\W+", " ", item["title"].lower()).strip()
            if key and key not in unique:
                unique[key] = item
        return sorted(unique.values(), key=lambda item: item["published_dt"], reverse=True)[:limit]

    def _google_news_url(self, query):
        encoded = quote_plus(f"{query} when:{self.lookback}")
        return f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"

    def _fetch(self, url, source):
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return self._parse(response.text, source)
        except Exception as error:
            print(f"⚠️ Toy trend feed error ({source}): {error.__class__.__name__}")
            return []

    def _parse(self, text, source):
        root = ET.fromstring(text)
        items = []
        for entry in root.findall(".//item"):
            title = self._clean(entry.findtext("title") or "")
            link = (entry.findtext("link") or "").strip()
            published = entry.findtext("pubDate") or ""
            if title and link:
                items.append(self._item(title, link, published, source))
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//atom:entry", ns):
            title = self._clean(entry.findtext("atom:title", default="", namespaces=ns))
            link_node = entry.find("atom:link", ns)
            link = link_node.attrib.get("href", "") if link_node is not None else ""
            published = entry.findtext("atom:published", default="", namespaces=ns)
            if title and link:
                items.append(self._item(title, link, published, source))
        return items

    def _item(self, title, link, published, source):
        return {
            "title": title[:300],
            "link": link,
            "source": source,
            "published": published,
            "published_dt": self._date(published),
        }

    @staticmethod
    def _clean(value):
        return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()

    @staticmethod
    def _date(value):
        try:
            parsed = parsedate_to_datetime(value) if "," in value else datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc)
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)
