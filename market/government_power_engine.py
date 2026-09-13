import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests


PT_ZONE = ZoneInfo("America/Los_Angeles")


class GovernmentPowerEngine:
    """Three-branch policy monitor for MarketOps.

    Pulls public government records and turns them into structured market-learning
    briefs. It does not replace legal research or broker data; it gives Eduardo a
    fast economic filter for laws, rules, and court rulings.
    """

    CONGRESS_ENDPOINT = "https://api.congress.gov/v3/bill"
    FEDERAL_REGISTER_ENDPOINT = "https://www.federalregister.gov/api/v1/documents.json"
    COURTLISTENER_ENDPOINT = "https://www.courtlistener.com/api/rest/v4/clusters/"

    FEDERAL_REGISTER_TYPES = ["RULE", "PRORULE", "NOTICE", "PRESDOCU"]

    KEYWORDS = {
        "AI / Chips": [
            "ai", "artificial intelligence", "openai", "chatgpt", "algorithm",
            "semiconductor", "chip", "chips", "gpu", "data center", "data centers",
            "export control", "technology transfer", "advanced computing",
        ],
        "Defense / Aerospace": [
            "defense", "pentagon", "dod", "missile", "weapons", "aerospace",
            "munitions", "shipbuilding", "national security", "nato",
        ],
        "Energy / Oil": [
            "oil", "gas", "lng", "pipeline", "drilling", "opec", "energy",
            "electric grid", "power grid", "refinery", "fuel", "lease sale",
        ],
        "Banks / Credit": [
            "bank", "banks", "banking", "capital requirement", "credit",
            "loan", "lending", "mortgage", "deposit", "fdic", "occ", "stress test",
        ],
        "Crypto / Fintech": [
            "crypto", "cryptocurrency", "bitcoin", "ethereum", "stablecoin",
            "digital asset", "coinbase", "sec", "cftc", "token",
        ],
        "Healthcare / Pharma": [
            "healthcare", "health care", "medicare", "medicaid", "drug",
            "pharma", "fda", "vaccine", "hospital", "insurance",
        ],
        "Trade / Tariffs": [
            "tariff", "tariffs", "trade", "import", "export", "customs",
            "sanction", "sanctions", "china", "mexico", "canada", "ustr",
        ],
        "Labor / Wages": [
            "labor", "wage", "wages", "union", "overtime", "worker",
            "workers", "strike", "immigration", "visa", "h-1b", "minimum wage",
        ],
        "Consumer / Retail": [
            "consumer", "retail", "credit card", "privacy", "data breach",
            "recall", "food", "usda", "ftc", "cfpb",
        ],
        "Transportation / Supply Chain": [
            "rail", "railroad", "truck", "trucking", "port", "ports", "shipping",
            "airline", "aviation", "boeing", "faa", "supply chain",
        ],
        "Housing / Real Estate": [
            "housing", "real estate", "rent", "mortgage", "zoning", "hud",
            "construction", "homebuilder", "home builders",
        ],
    }

    EVENT_WORDS = [
        "rule", "final rule", "proposed rule", "executive order", "order",
        "bill", "act", "passed", "introduced", "committee", "signed",
        "opinion", "ruling", "injunction", "appeal", "supreme court",
        "tariff", "sanction", "lawsuit", "antitrust", "ban", "permit",
        "approval", "subsidy", "tax", "credit", "fine", "penalty",
        "requirements", "compliance", "enforcement", "investigation",
    ]

    SECTOR_TICKERS = {
        "AI / Chips": "QQQ, NVDA, AMD, SMH, SOXX",
        "Defense / Aerospace": "LMT, RTX, NOC, GD, ITA",
        "Energy / Oil": "XOM, CVX, XLE, CL=F",
        "Banks / Credit": "JPM, BAC, KRE, XLF, US10Y",
        "Crypto / Fintech": "BTC-USD, COIN, IBIT, ETH-USD",
        "Healthcare / Pharma": "XLV, UNH, PFE, LLY, JNJ",
        "Trade / Tariffs": "SPY, QQQ, XLI, XLY, DXY",
        "Labor / Wages": "WMT, AMZN, TSN, XLY, XLI",
        "Consumer / Retail": "WMT, TGT, COST, XLY, XLP",
        "Transportation / Supply Chain": "IYT, XLI, BA, FDX, UPS",
        "Housing / Real Estate": "XHB, ITB, VNQ, HD, LOW",
    }

    def __init__(self):
        self.congress_api_key = os.getenv("CONGRESS_API_KEY", "").strip()
        self.courtlistener_token = os.getenv("COURTLISTENER_TOKEN", "").strip() or os.getenv("COURTLISTENER_API_TOKEN", "").strip()
        self.lookback_days = int(os.getenv("GOV_POWER_LOOKBACK_DAYS", "7"))
        self.limit_per_branch = int(os.getenv("GOV_POWER_LIMIT_PER_BRANCH", "25"))
        self.min_score = int(os.getenv("GOV_POWER_MIN_SCORE", "3"))
        self.congress_enabled = self._env_bool("GOV_POWER_CONGRESS_ENABLED", True)
        self.federal_register_enabled = self._env_bool("GOV_POWER_FEDREG_ENABLED", True)
        self.courtlistener_enabled = self._env_bool("GOV_POWER_COURTLISTENER_ENABLED", True)
        self.timeout_seconds = int(os.getenv("GOV_POWER_TIMEOUT_SECONDS", "20"))
        self.last_errors = []

    def build_report(self):
        self.last_errors = []
        raw_items = []

        if self.congress_enabled:
            raw_items.extend(self._fetch_congress())
        if self.federal_register_enabled:
            raw_items.extend(self._fetch_federal_register())
        if self.courtlistener_enabled:
            raw_items.extend(self._fetch_courtlistener())

        lessons = []
        for item in raw_items:
            lesson = self._build_lesson(item)
            if lesson["score"] >= self.min_score:
                lessons.append(lesson)

        lessons.sort(key=lambda row: (row["score"], row.get("date", "")), reverse=True)

        return {
            "items": lessons,
            "counts": self._counts(lessons),
            "errors": list(self.last_errors),
            "lookback_days": self.lookback_days,
            "min_score": self.min_score,
            "updated": self._timestamp(),
            "sources": {
                "legislative": "Congress.gov API" if self.congress_api_key else "Congress.gov API key missing",
                "executive": "Federal Register API",
                "judicial": "CourtListener API" + (" with token" if self.courtlistener_token else " without token"),
            },
        }

    def status(self):
        return {
            "congress_enabled": self.congress_enabled,
            "congress_ready": bool(self.congress_api_key),
            "federal_register_enabled": self.federal_register_enabled,
            "courtlistener_enabled": self.courtlistener_enabled,
            "courtlistener_token": bool(self.courtlistener_token),
            "lookback_days": self.lookback_days,
            "limit_per_branch": self.limit_per_branch,
            "min_score": self.min_score,
            "last_errors": list(self.last_errors),
            "updated": self._timestamp(),
        }

    def _fetch_congress(self):
        if not self.congress_api_key:
            self.last_errors.append("Congress.gov skipped: CONGRESS_API_KEY missing.")
            return []

        since = datetime.now(timezone.utc) - timedelta(days=self.lookback_days)
        params = {
            "api_key": self.congress_api_key,
            "format": "json",
            "limit": min(self.limit_per_branch, 250),
            "fromDateTime": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        try:
            data = self._get_json(self.CONGRESS_ENDPOINT, params=params)
        except Exception as error:
            self.last_errors.append(f"Congress.gov error: {error}")
            return []

        items = []
        for bill in data.get("bills", [])[: self.limit_per_branch]:
            latest = bill.get("latestAction") or {}
            title = bill.get("title") or bill.get("shortTitle") or "Untitled bill"
            summary = latest.get("text") or latest.get("action") or "Latest congressional action."
            date = latest.get("actionDate") or bill.get("updateDate") or bill.get("introducedDate") or ""
            congress = bill.get("congress", "")
            bill_type = bill.get("type", "").lower()
            number = bill.get("number", "")
            link = bill.get("url") or self._congress_web_url(congress, bill_type, number)
            items.append(
                self._raw_item(
                    branch="Legislative",
                    source="Congress.gov",
                    event_type="Bill / congressional action",
                    title=title,
                    summary=summary,
                    date=date,
                    link=link,
                )
            )
        return items

    def _fetch_federal_register(self):
        since = (datetime.now(PT_ZONE).date() - timedelta(days=self.lookback_days)).isoformat()
        params = [
            ("per_page", min(self.limit_per_branch, 100)),
            ("order", "newest"),
            ("conditions[publication_date][gte]", since),
            ("fields[]", "title"),
            ("fields[]", "type"),
            ("fields[]", "abstract"),
            ("fields[]", "publication_date"),
            ("fields[]", "agencies"),
            ("fields[]", "html_url"),
            ("fields[]", "document_number"),
        ]
        for document_type in self.FEDERAL_REGISTER_TYPES:
            params.append(("conditions[type][]", document_type))

        try:
            data = self._get_json(self.FEDERAL_REGISTER_ENDPOINT, params=params)
        except Exception as error:
            self.last_errors.append(f"Federal Register error: {error}")
            return []

        items = []
        for row in data.get("results", [])[: self.limit_per_branch]:
            agencies = row.get("agencies") or []
            agency_names = ", ".join(agency.get("name", "") for agency in agencies if agency.get("name"))
            doc_type = row.get("type", "Federal Register document")
            items.append(
                self._raw_item(
                    branch="Executive",
                    source=f"Federal Register{f' / {agency_names}' if agency_names else ''}",
                    event_type=doc_type,
                    title=row.get("title") or "Untitled Federal Register document",
                    summary=row.get("abstract") or "Official Federal Register document.",
                    date=row.get("publication_date") or "",
                    link=row.get("html_url") or "",
                )
            )
        return items

    def _fetch_courtlistener(self):
        since = (datetime.now(PT_ZONE).date() - timedelta(days=self.lookback_days)).isoformat()
        params = {
            "date_filed__gte": since,
            "order_by": "-date_filed",
            "page_size": min(self.limit_per_branch, 100),
        }
        headers = {}
        if self.courtlistener_token:
            headers["Authorization"] = f"Token {self.courtlistener_token}"

        try:
            data = self._get_json(self.COURTLISTENER_ENDPOINT, params=params, headers=headers)
        except Exception as error:
            self.last_errors.append(f"CourtListener error: {error}")
            return []

        items = []
        for row in data.get("results", [])[: self.limit_per_branch]:
            case_name = row.get("case_name") or row.get("case_name_full") or "Court opinion"
            summary = row.get("syllabus") or row.get("procedural_history") or row.get("posture") or "CourtListener court record."
            date = row.get("date_filed") or row.get("date_created") or ""
            absolute_url = row.get("absolute_url") or ""
            link = f"https://www.courtlistener.com{absolute_url}" if absolute_url.startswith("/") else absolute_url
            items.append(
                self._raw_item(
                    branch="Judicial",
                    source="CourtListener",
                    event_type="Court opinion / ruling",
                    title=case_name,
                    summary=summary,
                    date=date,
                    link=link,
                )
            )
        return items

    def _raw_item(self, branch, source, event_type, title, summary, date, link):
        title = self._clean_text(title)
        summary = self._clean_text(summary)
        return {
            "id": self._item_id(branch, title, date, link),
            "branch": branch,
            "source": source,
            "event_type": event_type,
            "title": title,
            "summary": summary,
            "date": date,
            "link": link,
        }

    def _build_lesson(self, item):
        text = self._normalize(f'{item.get("title", "")} {item.get("summary", "")} {item.get("source", "")}')
        sectors = self._detect_sectors(text)
        event_hits = [word for word in self.EVENT_WORDS if self._term_match(text, word)]
        score = len(sectors) + min(len(event_hits), 3)

        if item["branch"] == "Executive":
            score += 1
        if item["branch"] == "Judicial" and any(word in text for word in ("supreme court", "injunction", "antitrust", "sec", "ftc", "epa")):
            score += 2
        if item["branch"] == "Legislative" and any(word in text for word in ("passed", "signed", "committee", "appropriation", "budget", "tax", "tariff")):
            score += 1

        economics = self._economics(item, sectors, event_hits)
        confirm = self._confirm_list(sectors)
        payload = {
            "branch": item["branch"],
            "event_type": item["event_type"],
            "economic_paths": economics["paths"],
            "affected_sectors": sectors or ["Unclear / needs review"],
            "confirm_next": confirm,
            "not_financial_advice": True,
        }

        return {
            **item,
            "score": score,
            "sectors": sectors,
            "event_hits": event_hits[:6],
            "identify": self._identify(item, event_hits),
            "translate": economics["text"],
            "confirm": confirm,
            "payload": payload,
        }

    def _identify(self, item, event_hits):
        hits = ", ".join(event_hits[:4]) if event_hits else "official action"
        return f'{item["branch"]} branch event: {item["event_type"]}. Trigger words found: {hits}.'

    def _economics(self, item, sectors, event_hits):
        paths = []
        text = self._normalize(f'{item.get("title", "")} {item.get("summary", "")}')
        if any(word in text for word in ("tariff", "import", "customs", "sanction", "export control")):
            paths.append("Costs / supply chain")
        if any(word in text for word in ("tax", "credit", "subsidy", "grant", "appropriation")):
            paths.append("Revenue / government support")
        if any(word in text for word in ("rule", "requirements", "compliance", "enforcement", "ban", "permit")):
            paths.append("Compliance cost / operating risk")
        if any(word in text for word in ("lawsuit", "ruling", "injunction", "antitrust", "fine", "penalty")):
            paths.append("Legal risk / business model risk")
        if any(word in text for word in ("oil", "gas", "energy", "pipeline", "lease")):
            paths.append("Input prices / energy supply")
        if any(word in text for word in ("bank", "credit", "loan", "capital requirement", "deposit")):
            paths.append("Credit conditions / bank risk")

        if not paths:
            paths.append("Policy uncertainty / sector sentiment")

        sector_text = ", ".join(sectors[:4]) if sectors else "the affected sector"
        return {
            "paths": paths,
            "text": (
                f"This may affect {sector_text} through "
                f"{', '.join(paths[:4]).lower()}. First ask who pays more, who receives support, "
                "whose margins change, and whether the rule/ruling is final or only proposed."
            ),
        }

    def _confirm_list(self, sectors):
        checks = ["SPY", "QQQ", "VIX", "US10Y", "DXY"]
        for sector in sectors[:3]:
            tickers = self.SECTOR_TICKERS.get(sector)
            if tickers:
                checks.extend([item.strip() for item in tickers.split(",")])
        deduped = []
        for item in checks:
            if item and item not in deduped:
                deduped.append(item)
        return deduped[:10]

    def _detect_sectors(self, text):
        sectors = []
        for sector, terms in self.KEYWORDS.items():
            if any(self._term_match(text, term) for term in terms):
                sectors.append(sector)
        return sectors

    def _counts(self, lessons):
        counts = {"Legislative": 0, "Executive": 0, "Judicial": 0}
        for item in lessons:
            counts[item["branch"]] = counts.get(item["branch"], 0) + 1
        return counts

    def _get_json(self, url, params=None, headers=None):
        response = requests.get(url, params=params, headers=headers or {}, timeout=self.timeout_seconds)
        response.raise_for_status()
        return response.json()

    def _congress_web_url(self, congress, bill_type, number):
        if not congress or not bill_type or not number:
            return "https://www.congress.gov/"
        return f"https://www.congress.gov/bill/{congress}th-congress/{bill_type}/{number}"

    def _item_id(self, branch, title, date, link):
        raw = f"{branch}|{title}|{date}|{link}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def _clean_text(self, value):
        value = re.sub(r"<[^>]+>", " ", str(value or ""))
        value = re.sub(r"\s+", " ", value).strip()
        return value[:1200]

    def _normalize(self, value):
        return re.sub(r"\s+", " ", str(value or "").lower()).strip()

    def _term_match(self, text, term):
        term = self._normalize(term)
        if not term:
            return False
        if " " in term or "-" in term:
            return term in text
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None

    def _timestamp(self):
        return datetime.now(PT_ZONE).strftime("%I:%M %p PT").lstrip("0")

    def _env_bool(self, name, default=False):
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
