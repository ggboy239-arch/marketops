import html
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests
from dotenv import load_dotenv

load_dotenv()


class RedditProvider:
    """Fetches public Reddit RSS posts for market chatter.

    Reddit is not treated as confirmed news. MarketOps keeps these items separate
    in #reddit-hot so rumors/chatter do not pollute trusted news channels.
    """

    DEFAULT_SUBREDDITS = [
        "stocks",
        "investing",
        "wallstreetbets",
    ]

    OPTIONAL_SUBREDDITS = [
        "SecurityAnalysis",
        "StockMarket",
        "economics",
        "geopolitics",
        "worldnews",
        "CryptoCurrency",
        "Bitcoin",
    ]

    def __init__(self):
        self.enabled = self._env_bool("REDDIT_ENABLED", default=True)
        self.subreddits = self._load_csv("REDDIT_SUBREDDITS", self.DEFAULT_SUBREDDITS)
        self.limit_per_subreddit = int(os.getenv("REDDIT_LIMIT_PER_SUBREDDIT", "1"))
        self.timeout = int(os.getenv("REDDIT_TIMEOUT_SECONDS", "10"))
        self.request_delay_seconds = float(os.getenv("REDDIT_REQUEST_DELAY_SECONDS", "3"))
        self.cache_minutes = int(os.getenv("REDDIT_CACHE_MINUTES", "15"))
        self._cache_items = []
        self._cache_time = None
        self.headers = {
            "User-Agent": "MarketOpsRedditMonitor/0.7.2 by u/ggboy239",
            "Accept": "application/atom+xml, application/xml;q=0.9, */*;q=0.8",
        }

    def get_latest_news(self, limit=25):
        if not self.enabled:
            return []

        if self._cache_is_valid():
            return self._cache_items[:limit]

        items = []
        for index, subreddit in enumerate(self.subreddits):
            if index > 0:
                time.sleep(self.request_delay_seconds)

            items.extend(self._fetch_subreddit(subreddit))

        items = self._deduplicate(items)
        items = self._sort_items(items)
        self._cache_items = items
        self._cache_time = datetime.now(timezone.utc)
        return items[:limit]

    def source_policy(self):
        if not self.enabled:
            return "Reddit monitor is OFF because REDDIT_ENABLED=false."

        return (
            "Reddit monitor is ON. Reddit items are treated as chatter/watchlist leads, "
            "not confirmed news, and are routed to #reddit-hot. Reddit RSS is rate-limited, "
            "so MarketOps checks fewer subreddits and caches results."
        )

    def _fetch_subreddit(self, subreddit):
        url = f"https://www.reddit.com/r/{subreddit}/hot/.rss?limit={self.limit_per_subreddit}"

        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "unknown")
                print(
                    f"⚠️ Reddit rate limit from r/{subreddit}. "
                    f"Skipping for now. Retry-After: {retry_after}"
                )
                return []

            response.raise_for_status()
            return self._parse_feed(subreddit, response.text)

        except Exception as error:
            print(f"❌ Reddit RSS error from r/{subreddit}: {error}")
            return []

    def _parse_feed(self, subreddit, text):
        root = ET.fromstring(text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)
        items = []

        for entry in entries:
            title = self._find_text(entry, "atom:title", ns)
            updated = self._find_text(entry, "atom:updated", ns)
            summary = self._find_text(entry, "atom:content", ns) or self._find_text(entry, "atom:summary", ns)
            link = ""

            link_element = entry.find("atom:link", ns)
            if link_element is not None:
                link = link_element.attrib.get("href", "")

            if not title:
                continue

            items.append(
                {
                    "source": f"Reddit r/{subreddit}",
                    "title": self._clean_text(title),
                    "link": link,
                    "summary": self._clean_text(summary),
                    "published": updated,
                    "published_dt": self._parse_date(updated),
                    "category_hint": "🧵 Reddit Hot",
                    "trusted": False,
                    "provider": "Reddit RSS",
                }
            )

        return items

    def _cache_is_valid(self):
        if self._cache_time is None:
            return False

        age = datetime.now(timezone.utc) - self._cache_time
        return age < timedelta(minutes=self.cache_minutes)

    def _find_text(self, entry, tag, ns):
        element = entry.find(tag, ns)
        if element is None or element.text is None:
            return ""
        return element.text.strip()

    def _clean_text(self, value):
        value = html.unescape(value or "")
        value = re.sub(r"<[^>]+>", "", value)
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    def _parse_date(self, value):
        if not value:
            return None

        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except Exception:
            pass

        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except Exception:
            return None

    def _deduplicate(self, items):
        seen = set()
        unique = []

        for item in items:
            key = item.get("link") or item.get("title", "").lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)

        return unique

    def _sort_items(self, items):
        return sorted(
            items,
            key=lambda item: item.get("published_dt") or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

    def _load_csv(self, name, default):
        raw = os.getenv(name)
        if raw is None:
            return list(default)

        values = []
        for item in raw.split(","):
            cleaned = item.strip().strip("/")
            cleaned = cleaned.replace("r/", "")
            if cleaned:
                values.append(cleaned)
        return values

    def _env_bool(self, name, default=False):
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in ("1", "true", "yes", "y", "on")
