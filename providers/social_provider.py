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


class SocialProvider:
    """Fetches public X/social/video items for MarketOps.

    Plain English:
    - X account monitoring only runs when X_BEARER_TOKEN is present.
    - X posts are treated as raw public account posts, not decoded news.
    - Video monitoring uses public YouTube RSS feeds and works without an API key.
    - Social/video feeds stay separate from the normal news channels.
    """

    DEFAULT_X_USERNAMES = [
        "Bloomberg",
        "business",
        "markets",
        "Reuters",
        "CNBC",
        "YahooFinance",
        "AP",
        "NPR",
        "FederalReserve",
        "WhiteHouse",
        "USTreasury",
    ]

    DEFAULT_TRENDING_X_USERNAMES = [
        "Bloomberg",
        "business",
        "markets",
        "CNBC",
        "YahooFinance",
        "Reuters",
        "AP",
        "NPR",
    ]

    DEFAULT_YOUTUBE_FEEDS = [
        # Bloomberg Television
        "https://www.youtube.com/feeds/videos.xml?channel_id=UCIALMKvObZNtJ6AmdCLP7Lg",
        # CNBC Television
        "https://www.youtube.com/feeds/videos.xml?channel_id=UCrp_UI8XtuYfpiqluWLD7Lw",
        # Reuters
        "https://www.youtube.com/feeds/videos.xml?channel_id=UChqUTb7kYRX8-EiaN3XFrSQ",
    ]

    MARKET_TERMS = [
        "market", "markets", "stock", "stocks", "shares", "wall street",
        "s&p", "nasdaq", "dow", "futures", "fed", "federal reserve",
        "powell", "inflation", "cpi", "ppi", "pce", "jobs", "payroll",
        "unemployment", "rates", "rate cut", "rate hike", "yield", "treasury",
        "oil", "crude", "opec", "energy", "gold", "dollar", "bitcoin",
        "crypto", "earnings", "revenue", "profit", "guidance", "ai",
        "artificial intelligence", "nvidia", "amd", "chip", "chips", "semiconductor",
        "data center", "tariff", "tariffs", "sanctions", "china", "taiwan",
        "russia", "ukraine", "iran", "israel", "war", "missile", "attack",
        "cyberattack", "lawsuit", "antitrust", "strike", "supply chain",
        "bank", "banking", "white house", "congress", "supreme court",
    ]

    def __init__(self):
        self.x_token = os.getenv("X_BEARER_TOKEN") or os.getenv("TWITTER_BEARER_TOKEN")
        self.x_enabled = bool(self.x_token)
        self.x_usernames = self._load_csv("X_USERNAMES", self.DEFAULT_X_USERNAMES)
        self.trending_x_usernames = self._load_csv("TRENDING_X_USERNAMES", self.DEFAULT_TRENDING_X_USERNAMES)
        self.x_limit_per_user = max(5, int(os.getenv("X_LIMIT_PER_USER", "5")))
        self.x_backoff_minutes = int(os.getenv("X_RATE_LIMIT_BACKOFF_MINUTES", "60"))
        self.video_feeds = self._load_csv("YOUTUBE_FEEDS", self.DEFAULT_YOUTUBE_FEEDS)
        self.timeout = int(os.getenv("SOCIAL_TIMEOUT_SECONDS", "12"))
        self.max_age_minutes = int(os.getenv("SOCIAL_MAX_AGE_MINUTES", "60"))
        self.request_delay_seconds = float(os.getenv("SOCIAL_REQUEST_DELAY_SECONDS", "1.5"))
        self.x_require_market_terms = self._env_bool("SOCIAL_X_REQUIRE_MARKET_TERMS", default=False)
        self.video_require_market_terms = self._env_bool("SOCIAL_VIDEO_REQUIRE_MARKET_TERMS", default=False)
        self.trending_require_market_terms = self._env_bool("SOCIAL_TRENDING_REQUIRE_MARKET_TERMS", default=False)
        self._user_id_cache = {}
        self._x_blocked_until = None
        self.last_status = "Not checked yet"
        self.last_x_status = "Not checked yet"
        self.last_video_status = "Not checked yet"
        self.last_trending_status = "Not checked yet"
        self.headers = {
            "User-Agent": "MarketOpsSocialMonitor/1.1",
        }

    def get_latest_items(self, limit=25, kind="all"):
        kind = (kind or "all").strip().lower()
        items = []

        if kind in ("all", "x", "twitter", "social"):
            items.extend(self._fetch_x_items(self.x_usernames, source_group="x"))

        if kind in ("trending", "trend", "x-trending", "trending-x"):
            items.extend(self._fetch_x_items(self.trending_x_usernames, source_group="trending"))

        if kind in ("all", "video", "videos", "youtube"):
            items.extend(self._fetch_video_items())

        items = self._deduplicate(items)
        items = [item for item in items if self._is_fresh(item) and self._passes_item_filter(item, kind)]
        items = sorted(
            items,
            key=lambda item: (item.get("published_dt") or datetime.min.replace(tzinfo=timezone.utc), item.get("engagement_score", 0)),
            reverse=True,
        )
        self.last_status = f"OK: {len(items)} fresh social/video item(s) in the last {self.max_age_minutes} min."
        return items[:limit]

    def status_text(self):
        x_mode = "ON" if self.x_enabled else "OFF until X_BEARER_TOKEN is added"
        return (
            f"X monitor: {x_mode}\n"
            f"X accounts: {', '.join(self.x_usernames) if self.x_usernames else 'none'}\n"
            f"Trending X accounts: {', '.join(self.trending_x_usernames) if self.trending_x_usernames else 'none'}\n"
            f"Video feeds: {len(self.video_feeds)} configured\n"
            f"Freshness window: last {self.max_age_minutes} minute(s)\n"
            f"X raw-post mode: {'ON' if not self.x_require_market_terms else 'OFF'}\n"
            f"Last X: {self.last_x_status}\n"
            f"Last Trending: {self.last_trending_status}\n"
            f"Last Video: {self.last_video_status}\n"
            f"Last Overall: {self.last_status}"
        )

    def _fetch_x_items(self, usernames, source_group="x"):
        if not self.x_enabled:
            status = "OFF: X_BEARER_TOKEN missing"
            if source_group == "trending":
                self.last_trending_status = status
            else:
                self.last_x_status = status
            return []

        if self._x_is_blocked():
            remaining = int((self._x_blocked_until - datetime.now(timezone.utc)).total_seconds() // 60) + 1
            status = f"RATE LIMITED: sleeping about {remaining} more minute(s)"
            if source_group == "trending":
                self.last_trending_status = status
            else:
                self.last_x_status = status
            return []

        items = []
        checked = 0
        for username in usernames:
            if checked:
                time.sleep(self.request_delay_seconds)
            fetched = self._fetch_user_posts(username, source_group=source_group)
            items.extend(fetched)
            checked += 1

        status = f"OK: checked {checked} account(s), got {len(items)} raw post(s)"
        if source_group == "trending":
            self.last_trending_status = status
        else:
            self.last_x_status = status
        return items

    def _fetch_user_posts(self, username, source_group="x"):
        user_id = self._get_x_user_id(username)
        if not user_id:
            return []

        url = f"https://api.x.com/2/users/{user_id}/tweets"
        params = {
            "max_results": str(self.x_limit_per_user),
            "exclude": "retweets,replies",
            "tweet.fields": "created_at,public_metrics,entities,attachments",
            "expansions": "attachments.media_keys",
            "media.fields": "type,preview_image_url,url",
        }
        payload = self._x_get(url, params=params)
        if not payload:
            return []

        media_by_key = {}
        for media in payload.get("includes", {}).get("media", []):
            media_key = media.get("media_key")
            if media_key:
                media_by_key[media_key] = media

        items = []
        for post in payload.get("data", []) or []:
            post_id = post.get("id")
            text = self._clean_text(post.get("text", ""))
            if not post_id or not text:
                continue

            media_keys = post.get("attachments", {}).get("media_keys", []) or []
            has_video = any((media_by_key.get(key, {}).get("type") in {"video", "animated_gif"}) for key in media_keys)
            metrics = post.get("public_metrics") or {}
            engagement_score = self._engagement_score(metrics)
            created = self._parse_date(post.get("created_at"))
            source = f"X @{username}"
            items.append(
                {
                    "type": "trending" if source_group == "trending" else "x",
                    "source": source,
                    "title": text,
                    "link": f"https://x.com/{username}/status/{post_id}",
                    "published_dt": created,
                    "provider": "X API",
                    "has_video": has_video,
                    "metrics": metrics,
                    "engagement_score": engagement_score,
                }
            )
        return items

    def _get_x_user_id(self, username):
        username = str(username or "").strip().lstrip("@")
        if not username:
            return ""
        if username in self._user_id_cache:
            return self._user_id_cache[username]

        url = f"https://api.x.com/2/users/by/username/{username}"
        payload = self._x_get(url, params={"user.fields": "id,username,name,verified"})
        user_id = (payload or {}).get("data", {}).get("id")
        if user_id:
            self._user_id_cache[username] = user_id
        return user_id or ""

    def _x_get(self, url, params=None):
        try:
            response = requests.get(
                url,
                headers={**self.headers, "Authorization": f"Bearer {self.x_token}"},
                params=params,
                timeout=self.timeout,
            )

            if response.status_code == 429:
                self._x_blocked_until = datetime.now(timezone.utc) + timedelta(minutes=self.x_backoff_minutes)
                self.last_x_status = f"RATE LIMITED: backing off {self.x_backoff_minutes} minutes"
                print(f"⚠️ X API rate limit. Backing off {self.x_backoff_minutes} minutes.")
                return None

            if response.status_code in (401, 403):
                self.x_enabled = False
                self.last_x_status = f"OFF: X API returned HTTP {response.status_code}. Check X_BEARER_TOKEN."
                print(f"⚠️ X monitor disabled: HTTP {response.status_code}. Check X_BEARER_TOKEN.")
                return None

            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as error:
            self.last_x_status = f"ERROR: {error.__class__.__name__}"
            print(f"⚠️ X monitor request error: {error.__class__.__name__}")
            return None

    def _fetch_video_items(self):
        items = []
        checked = 0
        for feed_url in self.video_feeds:
            if checked:
                time.sleep(self.request_delay_seconds)
            checked += 1
            try:
                response = requests.get(feed_url, headers=self.headers, timeout=self.timeout)
                response.raise_for_status()
                items.extend(self._parse_youtube_feed(response.text, feed_url))
            except Exception as error:
                print(f"⚠️ Video feed error: {error.__class__.__name__} from {feed_url}")

        self.last_video_status = f"OK: checked {checked} feed(s), got {len(items)} raw video(s)"
        return items

    def _parse_youtube_feed(self, text, feed_url):
        root = ET.fromstring(text)
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "yt": "http://www.youtube.com/xml/schemas/2015",
        }
        source = self._find_text(root, "atom:title", ns) or "YouTube"
        items = []

        for entry in root.findall("atom:entry", ns):
            title = self._clean_text(self._find_text(entry, "atom:title", ns))
            published = self._find_text(entry, "atom:published", ns) or self._find_text(entry, "atom:updated", ns)
            video_id = self._find_text(entry, "yt:videoId", ns)
            link = ""
            link_element = entry.find("atom:link", ns)
            if link_element is not None:
                link = link_element.attrib.get("href", "")
            if not link and video_id:
                link = f"https://www.youtube.com/watch?v={video_id}"
            if not title:
                continue

            items.append(
                {
                    "type": "video",
                    "source": source,
                    "title": title,
                    "link": link,
                    "published_dt": self._parse_date(published),
                    "provider": "YouTube RSS",
                    "has_video": True,
                    "feed_url": feed_url,
                    "engagement_score": 0,
                }
            )
        return items

    def _x_is_blocked(self):
        return self._x_blocked_until is not None and datetime.now(timezone.utc) < self._x_blocked_until

    def _is_fresh(self, item):
        published_dt = item.get("published_dt")
        if published_dt is None:
            return False
        if published_dt.tzinfo is None:
            published_dt = published_dt.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - published_dt.astimezone(timezone.utc)
        return timedelta(0) <= age <= timedelta(minutes=self.max_age_minutes)

    def _passes_item_filter(self, item, kind):
        item_type = item.get("type")
        if item_type == "x" and not self.x_require_market_terms:
            return True
        if item_type == "trending" and not self.trending_require_market_terms:
            return True
        if item_type == "video" and not self.video_require_market_terms:
            return True
        return self._is_market_relevant(item)

    def _is_market_relevant(self, item):
        text = self._normalize(f"{item.get('title', '')} {item.get('source', '')}")
        return any(self._keyword_match(text, term) for term in self.MARKET_TERMS)

    def _engagement_score(self, metrics):
        try:
            return (
                int(metrics.get("like_count", 0))
                + int(metrics.get("retweet_count", 0)) * 2
                + int(metrics.get("reply_count", 0))
                + int(metrics.get("quote_count", 0)) * 2
            )
        except Exception:
            return 0

    def _find_text(self, root, tag, ns):
        element = root.find(tag, ns)
        if element is None or element.text is None:
            return ""
        return element.text.strip()

    def _parse_date(self, value):
        if not value:
            return None
        value = str(value).strip()
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except Exception:
            pass
        try:
            parsed = parsedate_to_datetime(value)
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

    def _clean_text(self, value):
        value = html.unescape(value or "")
        value = re.sub(r"<[^>]+>", "", value)
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    def _normalize(self, value):
        return re.sub(r"\s+", " ", str(value or "").lower()).strip()

    def _keyword_match(self, text, keyword):
        keyword = self._normalize(keyword)
        if not keyword:
            return False
        return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None

    def _load_csv(self, env_name, default):
        raw = os.getenv(env_name)
        if raw is None:
            return list(default)
        values = []
        for item in raw.split(","):
            cleaned = item.strip().lstrip("@")
            if cleaned:
                values.append(cleaned)
        return values

    def _env_bool(self, name, default=False):
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in ("1", "true", "yes", "y", "on")
