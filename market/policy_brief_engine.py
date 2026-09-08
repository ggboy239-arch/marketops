import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from market.news_engine import NewsEngine


PT_ZONE = ZoneInfo("America/Los_Angeles")


class PolicyBriefEngine:
    """Build a sourced, plain-language policy-to-market lesson with OpenAI."""

    POLICY_WORDS = (
        "white house", "congress", "senate", "supreme court", "treasury",
        "commerce department", "usda", "federal reserve", "sec", "ftc",
        "doj", "fda", "epa", "tariff", "trade", "sanction", "regulation",
        "regulator", "executive order", "proclamation", "government",
        "policy", "export control", "import", "antitrust", "subsidy",
        "loan guarantee", "contract award", "shutdown", "tax",
    )

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.model = os.getenv("OPENAI_MODEL", "gpt-5-mini").strip()
        self.timeout_seconds = int(os.getenv("OPENAI_POLICY_TIMEOUT_SECONDS", "120"))
        self.lookback_hours = float(os.getenv("POLICY_BRIEF_LOOKBACK_HOURS", "30"))
        self.news = NewsEngine()

    @property
    def enabled(self):
        return bool(self.api_key)

    def build_brief(self):
        if not self.api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is missing. Add it to .env; never paste it into Discord or GitHub."
            )

        now = datetime.now(PT_ZONE)
        candidates = self._candidate_headlines()
        prompt = self._prompt(now, candidates)
        text = self._request_brief(prompt)

        if not text or text.strip() == "NO_MEANINGFUL_UPDATE":
            return {
                "no_update": True,
                "text": "No new high-confidence policy development was found.",
                "updated": now.strftime("%I:%M %p PT").lstrip("0"),
                "model": self.model,
            }

        return {
            "no_update": False,
            "text": text.strip(),
            "updated": now.strftime("%I:%M %p PT").lstrip("0"),
            "model": self.model,
        }

    def _candidate_headlines(self):
        # The regular news bot is intentionally very fresh. The policy lesson
        # needs a longer window because official actions often arrive after close.
        self.news.max_age_hours = max(self.news.max_age_hours, self.lookback_hours)
        report = self.news.get_top_news(limit=40, category="all")
        items = [
            item for item in report.get("items", [])
            if item.get("provider") != "Reddit RSS"
        ]

        policy_items = []
        other_items = []
        for item in items:
            searchable = f'{item.get("title", "")} {item.get("summary", "")}'.lower()
            target = policy_items if any(word in searchable for word in self.POLICY_WORDS) else other_items
            target.append(item)

        selected = (policy_items + other_items)[:14]
        lines = []
        for item in selected:
            title = " ".join(str(item.get("title", "Untitled")).split())
            summary = " ".join(str(item.get("summary", "")).split())[:450]
            source = item.get("source", "Unknown")
            link = item.get("link", "")
            lines.append(f"- {source}: {title}\n  Summary: {summary}\n  Link: {link}")
        return "\n".join(lines) or "- No useful feed candidates were available; search the web directly."

    def _prompt(self, now, candidates):
        return f"""
Today is {now.strftime('%A, %B %d, %Y')} in the United States. Create one short,
plain-language policy-to-market briefing that is easy to hear read aloud.

Choose ONE important new or developing U.S. policy, tariff, trade action,
regulation, court ruling, sanction, or government decision. Use web search to
verify it. Prefer something new in the last 24 hours. If nothing meaningful is
new, a major developing action from the last 72 hours is acceptable. Do not
repeat a stale story merely to fill space.

Required content:
- Start: **Today’s policy-to-market lesson:** followed by a short title.
- **Confirmed:** what officially changed, with an exact date.
- **Industries affected:** name the sectors and useful public stock symbols when relevant.
- **Who may pay more or lose:** explain the direct path in plain English.
- **Who may benefit:** explain the direct path in plain English.
- **Market reaction:** say whether prices appear to have reacted already. Do not
  claim one headline caused a move unless reliable reporting supports that link.
- **Proposal or rumor:** clearly separate anything not final. If none, say so briefly.
- **Watch next:** give 3 or 4 concrete things to monitor.
- **Simple takeaway:** finish with one or two sentences.

Source rules:
- Verify confirmed facts with the best primary source: White House, Federal
  Register, Congress, court, Federal Reserve, Treasury/OFAC, USTR, USDA, SEC,
  FTC, DOJ, FDA, EPA, or another responsible agency.
- Include clickable Markdown links beside the claims they support.
- A high-quality reporting source may support market reaction, but never turn a
  social-media rumor into a confirmed fact.

Style and safety:
- 300 to 450 words, short paragraphs, ordinary words, no jargon pile-up.
- Do not tell the reader to buy, sell, or hold anything.
- Do not promise returns or call something guaranteed.
- This is public-information education, not private insider information.
- If there is no meaningful, verifiable update, return only: NO_MEANINGFUL_UPDATE

Fresh candidate headlines from MarketOps are below. They are leads, not proof.
Independently verify the chosen topic before writing:
{candidates}
""".strip()

    def _request_brief(self, prompt):
        endpoint = "https://api.openai.com/v1/responses"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        preferred_tool = os.getenv("OPENAI_WEB_SEARCH_TOOL", "web_search_preview").strip()
        tool_types = [preferred_tool]
        if preferred_tool != "web_search":
            tool_types.append("web_search")

        last_error = None
        for tool_type in tool_types:
            payload = {
                "model": self.model,
                "tools": [{"type": tool_type}],
                "input": prompt,
                "max_output_tokens": 2200,
            }
            response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
            )
            if response.ok:
                return self._output_text(response.json())

            last_error = f"OpenAI HTTP {response.status_code}: {response.text[:500]}"
            # Retry only when the API rejected the web-search tool name.
            if response.status_code != 400:
                break

        raise RuntimeError(last_error or "OpenAI did not return a policy brief.")

    def _output_text(self, data):
        pieces = []
        for output_item in data.get("output", []):
            if output_item.get("type") != "message":
                continue
            for content_item in output_item.get("content", []):
                if content_item.get("type") == "output_text" and content_item.get("text"):
                    pieces.append(content_item["text"])
        return "\n".join(pieces).strip()
