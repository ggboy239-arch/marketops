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
        self.request_delay_seconds = float(os.getenv("REDDIT_REQUEST_DELAY_SECONDS", "4"))
        self.cache_minutes = int(os.getenv("REDDIT_CACHE_MINUTES", "30"))
        self.rate_limit_minutes = int(os.getenv("REDDIT_RATE_LIMIT_BACKOFF_MINUTES", "60"))
        self._cache_items = []
        self._cache_time = None
        self._blocked_until = {}
        self._last_success_at = None
        self._last_status = "Not checked yet"
        self._last_rate_limited = []
        self.headers = {
            "User-Agent": "MarketOpsRedditMonitor/0.7.5 by u/ggboy239",
            "Accept": "application/atom+xml, application/xml;q=0.9, */*;q=0.8",
        }

    def get_latest_news(self, limit=25):
        if not self.enabled:
            self._last_status = "OFF"
            return []

        if self._cache_is_valid():
            self._last_status = f"Using cached Reddit items ({len(self._cache_items)} cached)."
            return self._cache_items[:limit]

        items = []
        checked = []
        skipped = []
        rate_limited = []

        for index, subreddit in enumerate(self.subreddits):
            if self._is_blocked(subreddit):
                skipped.append(subreddit)
                continue

            if checked:
                time.sleep(self.request_delay_seconds)

            fetched = self._fetch_subreddit(subreddit)
            checked.append(subreddit)
            if self._is_blocked(subreddit):
                rate_limited.append(subreddit)
            items.extend(fetched)

        items = self._deduplicate(items)
        items = self._sort_items(items)

        if items:
            self._cache_items = items
            self._cache_time = datetime.now(timezone.utc)
            self._last_success_at = self._cache_time
            self._last_status = f"OK — pulled {len(items)} Reddit chatter item(s)."
        elif self._cache_items:
            # If Reddit blocks us, keep showing the last cache instead of making the whole source look broken.
            items = list(self._cache_items)
            self._last_status = "Rate-limited/no new Reddit items — using last cached chatter."
        elif skipped or rate_limited:
            names = sorted(set(skipped + rate_limited))
            self._last_status = "Rate-limited — cooling down: " + ", ".join(f"r/{name}" for name in names)
        else:
            self._last_status = "No Reddit items returned this check."

        self._last_rate_limited = sorted(set(rate_limited + skipped))
        return items[:limit]

    def source_policy(self):
        if not self.enabled:
            return "Reddit monitor is OFF because REDDIT_ENABLED=false."

        return (
            "Reddit monitor is ON. Reddit items are treated as chatter/watchlist leads, "
            "not confirmed news, and are routed to #reddit-hot. Reddit RSS can rate-limit; "
            f"MarketOps now backs off for {self.rate_limit_minutes} minutes per blocked subreddit "
            "instead of repeatedly spamming warnings."
        )

    def status_text(self):
        if not self.enabled:
            return "Reddit: OFF (`REDDIT_ENABLED=false`)."

        now = datetime.now(timezone.utc)
        cooling = []
        for subreddit, until in self._blocked_until.items():
            if until > now:
                minutes_left = max(1, int((until - now).total_seconds() // 60))
                cooling.append(f"r/{subreddit} ({minutes_left}m)")

        pieces = [f"Reddit: {self._last_status}"]
        if cooling:
            pieces.append("Cooling down: " + ", ".join(cooling[:6]))
        if self._last_success_at:
            pieces.append("Last success: " + self._time_label(self._last_success_at))
        return "\n".join(pieces)

    def _fetch_subreddit(self, subreddit):
        url = f"https://www.reddit.com/r/{subreddit}/hot/.rss?limit={self.limit_per_subreddit}"

        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "unknown")
                self._block_subreddit(subreddit, retry_after)
                print(
                    f"⚠️ Reddit rate limit from r/{subreddit}. "
                    f"Cooling down for {self.rate_limit_minutes} min. Retry-After: {retry_after}"
                )
                return []

            response.raise_for_status()
            self._blocked_until.pop(subreddit, None)
            return self._parse_feed(subreddit, response.text)

        except Exception as error:
            print(f"❌ Reddit RSS error from r/{subreddit}: {error}")
            return []

    def _block_subreddit(self, subreddit, retry_after):
        minutes = self.rate_limit_minutes
        try:
            retry_seconds = int(retry_after)
            minutes = max(minutes, int(retry_seconds // 60) + 1)
        except Exception:
            pass
        self._blocked_until[subreddit] = datetime.now(timezone.utc) + timedelta(minutes=minutes)

    def _is_blocked(self, subreddit):
        until = self._blocked_until.get(subreddit)
        if until is None:
            return False
        if until <= datetime.now(timezone.utc):
            self._blocked_until.pop(subreddit, None)
            return False
        return True

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

    def _time_label(self, dt):
        try:
            return dt.astimezone().strftime("%I:%M %p").lstrip("0")
        except Exception:
            return "unknown"

    def _env_bool(self, name, default=False):
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in ("1", "true", "yes", "y", "on")
