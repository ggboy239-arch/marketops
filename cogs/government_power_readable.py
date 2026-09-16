import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from time import monotonic
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

from market.government_power_engine import GovernmentPowerEngine

VERSION = "MarketOps Federal Power v1.1.0"
PT_ZONE = ZoneInfo("America/Los_Angeles")


class GovernmentPowerReadable(commands.Cog):
    """Compact three-branch monitor designed for fast Discord reading."""

    LOW_VALUE_PHRASES = (
        "information collection activities",
        "comment request",
        "notice of public meeting",
        "hearing",
        "extension",
        "paperwork reduction act",
    )

    HIGH_IMPACT_TERMS = (
        "final rule", "executive order", "supreme court", "injunction",
        "tariff", "sanction", "antitrust", "ban", "tax", "subsidy",
        "appropriation", "budget", "export control", "bank", "crypto",
        "semiconductor", "defense", "energy", "medicare", "medicaid",
    )

    def __init__(self, bot):
        self.bot = bot
        self.engine = GovernmentPowerEngine()
        self.enabled = self._env_bool("GOV_POWER_ENABLED", True)
        self.channel_name = os.getenv("GOV_POWER_CHANNEL", "federal-power-briefs").strip()
        self.create_channel = self._env_bool("GOV_POWER_CREATE_CHANNEL", True)
        self.poll_minutes = float(os.getenv("GOV_POWER_POLL_MINUTES", "180"))
        self.max_auto_posts = int(os.getenv("GOV_POWER_MAX_AUTO_POSTS", "2"))
        self.max_manual_posts = int(os.getenv("GOV_POWER_MAX_MANUAL_POSTS", "3"))
        self.state_file = Path("data/government_power_state.json")
        self.state = self._load_state()
        self.last_check = "Not checked yet"
        self.last_post = "Not posted yet"
        self.last_error = "None"
        self._last_poll = 0.0

        # Avoid repeated bad requests and giant error URLs when keys are not configured.
        if self._looks_placeholder(self.engine.congress_api_key):
            self.engine.congress_enabled = False
        if not self.engine.courtlistener_token:
            self.engine.courtlistener_enabled = False

        if self.enabled and not self.gov_power_loop.is_running():
            self.gov_power_loop.start()

    def cog_unload(self):
        if self.gov_power_loop.is_running():
            self.gov_power_loop.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        if self.create_channel:
            for guild in self.bot.guilds:
                await self._ensure_channel(guild)

    @commands.command(name="power", aliases=["govpower", "fedpower", "branchwatch", "lawwatch", "courtwatch", "rulewatch"])
    async def power_prefix(self, ctx, action="now"):
        action = (action or "now").lower().strip()
        if action in {"status", "schedule", "settings"}:
            await ctx.send(embed=self._status_embed())
            return
        if action in {"help", "commands"}:
            await ctx.send(embed=self._help_embed())
            return
        if action in {"post", "send", "test"}:
            await self._post_report(ctx)
            return

        show_all = action in {"all", "more", "details"}
        try:
            report = await asyncio.to_thread(self.engine.build_report)
            self.last_check = report.get("updated", "Unknown")
            items = self._display_items(report.get("items", []), show_all=show_all)
            await ctx.send(embed=self._summary_embed(report, items))
            if not items:
                return
            limit = 8 if show_all else self.max_manual_posts
            for item in items[:limit]:
                await ctx.send(embed=self._lesson_embed(item), allowed_mentions=discord.AllowedMentions.none())
        except Exception as error:
            self.last_error = repr(error)
            print(f"❌ !power error: {error!r}")
            await ctx.send("⚠️ Federal Power Monitor could not refresh. Use `!power status` and check the terminal.")

    @commands.command(name="powerpost", aliases=["govpost", "branchpost"])
    async def powerpost_prefix(self, ctx):
        await self._post_report(ctx)

    @commands.command(name="powerstatus", aliases=["govstatus", "branchstatus"])
    async def powerstatus_prefix(self, ctx):
        await ctx.send(embed=self._status_embed())

    @commands.command(name="powerhelp", aliases=["govhelp", "branchhelp"])
    async def powerhelp_prefix(self, ctx):
        await ctx.send(embed=self._help_embed())

    @tasks.loop(seconds=30)
    async def gov_power_loop(self):
        await self.bot.wait_until_ready()
        if not self.enabled:
            return
        if monotonic() - self._last_poll < self.poll_minutes * 60:
            return
        self._last_poll = monotonic()

        try:
            report = await asyncio.to_thread(self.engine.build_report)
            self.last_check = report.get("updated", "Unknown")
            meaningful = self._display_items(report.get("items", []))
            new_items = self._new_items(meaningful)[: self.max_auto_posts]
            if not new_items:
                return

            for guild in self.bot.guilds:
                channel = await self._ensure_channel(guild)
                if channel is None:
                    continue
                await channel.send(embed=self._summary_embed(report, new_items), allowed_mentions=discord.AllowedMentions.none())
                for item in new_items:
                    await channel.send(embed=self._lesson_embed(item), allowed_mentions=discord.AllowedMentions.none())

            self._remember_items(new_items)
            self.last_post = self._timestamp()
            self.last_error = "None"
        except Exception as error:
            self.last_error = repr(error)
            print(f"❌ Government power loop error: {error!r}")

    async def _post_report(self, ctx):
        if ctx.guild is None:
            await ctx.send("⚠️ Run this inside the Discord server.")
            return

        channel = await self._ensure_channel(ctx.guild)
        if channel is None:
            await ctx.send(f"⚠️ I cannot find or create `#{self.channel_name}`.")
            return

        try:
            report = await asyncio.to_thread(self.engine.build_report)
            self.last_check = report.get("updated", "Unknown")
            items = self._display_items(report.get("items", []))[: self.max_manual_posts]
            await channel.send(embed=self._summary_embed(report, items), allowed_mentions=discord.AllowedMentions.none())
            for item in items:
                await channel.send(embed=self._lesson_embed(item), allowed_mentions=discord.AllowedMentions.none())

            if items:
                self._remember_items(items)
                self.last_post = self._timestamp()
                await ctx.send(f"✅ Posted {len(items)} high-priority federal brief(s) to #{channel.name}.")
            else:
                await ctx.send(f"✅ Checked government sources. Nothing high-priority to post to #{channel.name}.")
        except Exception as error:
            self.last_error = repr(error)
            print(f"❌ !power post error: {error!r}")
            await ctx.send("⚠️ Federal Power Monitor could not post. Use `!power status` and check the terminal.")

    def _display_items(self, items, show_all=False):
        ranked = []
        for item in items:
            score = int(item.get("score", 0) or 0)
            sectors = [sector for sector in item.get("sectors", []) if sector and "unclear" not in sector.lower()]
            title = (item.get("title") or "").lower()
            branch = item.get("branch", "")
            high_impact = any(term in title for term in self.HIGH_IMPACT_TERMS)
            low_value = any(term in title for term in self.LOW_VALUE_PHRASES)

            if show_all:
                ranked.append(item)
                continue

            if branch in {"Legislative", "Judicial"} and score >= 4:
                ranked.append(item)
                continue
            if high_impact and score >= 4:
                ranked.append(item)
                continue
            if sectors and score >= 5:
                ranked.append(item)
                continue
            if sectors and score >= 4 and not low_value:
                ranked.append(item)

        ranked.sort(key=lambda row: (int(row.get("score", 0) or 0), row.get("date", "")), reverse=True)
        return ranked

    def _lesson_embed(self, item):
        branch = item.get("branch", "Unknown")
        branch_emoji = {"Legislative": "🏛️", "Executive": "⚙️", "Judicial": "⚖️"}.get(branch, "🏛️")
        score = int(item.get("score", 0) or 0)
        impact = "HIGH" if score >= 6 else "MEDIUM" if score >= 4 else "LOW"
        sectors = [sector for sector in item.get("sectors", []) if sector and "unclear" not in sector.lower()]
        sector_text = ", ".join(sectors[:3]) if sectors else "No clear market sector yet"
        title = self._trim(item.get("title", "Untitled"), 180)
        link = self._clean_link(item.get("link", ""))

        embed = discord.Embed(
            title=f"{branch_emoji} {impact} IMPACT • {branch}",
            description=f"**{title}**",
            color=self._branch_color(branch),
            url=link or None,
        )

        embed.add_field(
            name="What changed?",
            value=self._plain_change(item),
            inline=False,
        )
        embed.add_field(
            name="Why it matters",
            value=self._plain_economics(item),
            inline=False,
        )
        embed.add_field(name="Affected", value=sector_text, inline=True)

        confirm = item.get("confirm", [])
        watch = ", ".join(confirm[:7]) if confirm else "SPY, QQQ, VIX"
        embed.add_field(name="Watch", value=watch, inline=True)

        if link:
            embed.add_field(name="Source", value=f"[Open official record](<{link}>)", inline=False)

        embed.set_footer(text=f"Score {score} • {item.get('date', 'Unknown date')} • {VERSION}")
        return embed

    def _summary_embed(self, report, displayed_items):
        counts = report.get("counts", {})
        embed = discord.Embed(
            title="🏛️ Federal Power — Market Impact",
            description="Only the government changes most likely to matter for markets are shown below.",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Sources scanned",
            value=(
                f"🏛️ Congress: **{counts.get('Legislative', 0)}**\n"
                f"⚙️ Executive: **{counts.get('Executive', 0)}**\n"
                f"⚖️ Courts: **{counts.get('Judicial', 0)}**"
            ),
            inline=True,
        )
        embed.add_field(name="Showing", value=f"**{len(displayed_items)}** higher-impact item(s)", inline=True)
        embed.add_field(name="Lookback", value=f"{report.get('lookback_days', '?')} days", inline=True)

        setup_notes = self._setup_notes(report)
        if setup_notes:
            embed.add_field(name="Source setup", value="\n".join(setup_notes), inline=False)

        embed.add_field(
            name="How to read this",
            value="**What changed → Why it matters → Affected → Watch**",
            inline=False,
        )
        embed.set_footer(text=f"Checked {report.get('updated', 'Unknown')} • Use `!power all` for more")
        return embed

    def _status_embed(self):
        congress_ready = self.engine.congress_enabled and not self._looks_placeholder(self.engine.congress_api_key)
        court_ready = self.engine.courtlistener_enabled and bool(self.engine.courtlistener_token)

        embed = discord.Embed(
            title="⚙️ Federal Power Monitor",
            description="Compact mode: only higher-impact laws, rules, and court actions are posted automatically.",
            color=discord.Color.green() if self.enabled else discord.Color.orange(),
        )
        embed.add_field(name="Monitor", value="ON" if self.enabled else "OFF", inline=True)
        embed.add_field(name="Channel", value=f"#{self.channel_name}", inline=True)
        embed.add_field(name="Checks", value=f"Every {self.poll_minutes:g} min", inline=True)
        embed.add_field(name="Congress.gov", value="✅ Ready" if congress_ready else "⚠️ Add valid API key", inline=True)
        embed.add_field(name="Federal Register", value="✅ Ready" if self.engine.federal_register_enabled else "OFF", inline=True)
        embed.add_field(name="CourtListener", value="✅ Ready" if court_ready else "⚠️ Add token", inline=True)
        embed.add_field(name="Last check", value=self.last_check, inline=True)
        embed.add_field(name="Last post", value=self.last_post, inline=True)
        embed.add_field(name="Last error", value=self._short_error(self.last_error), inline=False)
        embed.add_field(name="Test", value="`!power post`", inline=True)
        embed.add_field(name="More results", value="`!power all`", inline=True)
        embed.set_footer(text=VERSION)
        return embed

    def _help_embed(self):
        embed = discord.Embed(
            title="🏛️ Federal Power Help",
            description="Learn the economic meaning of government changes without reading the entire document.",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Commands",
            value=(
                "`!power` — top market-relevant changes\n"
                "`!power all` — show more results\n"
                "`!power post` — send top results to the channel\n"
                "`!power status` — source/API health\n"
                "`!powerhelp` — this card"
            ),
            inline=False,
        )
        embed.add_field(
            name="Reading order",
            value="**What changed → Why it matters → Affected → Watch**",
            inline=False,
        )
        embed.set_footer(text=VERSION)
        return embed

    def _plain_change(self, item):
        event_type = item.get("event_type", "Government action")
        source = item.get("source", "Official source")
        source = source.replace("Federal Register / ", "")
        return self._trim(f"{event_type} from {source}.", 350)

    def _plain_economics(self, item):
        text = str(item.get("translate", "No clear economic path yet."))
        marker = " First ask"
        if marker in text:
            text = text.split(marker, 1)[0].strip()
        text = text.replace("This may affect the affected sector through", "Possible market path:")
        return self._trim(text, 650)

    def _setup_notes(self, report):
        notes = []
        if not self.engine.congress_enabled or self._looks_placeholder(self.engine.congress_api_key):
            notes.append("⚠️ Congress.gov: add a valid API key")
        if not self.engine.courtlistener_enabled or not self.engine.courtlistener_token:
            notes.append("⚠️ CourtListener: add an API token")
        for error in report.get("errors", [])[:3]:
            short = self._short_error(error)
            if short and short not in notes:
                notes.append(f"⚠️ {short}")
        return notes[:3]

    def _short_error(self, error):
        text = str(error or "None")
        if text == "None":
            return "None"
        lower = text.lower()
        if "congress" in lower and ("403" in lower or "forbidden" in lower):
            return "Congress.gov rejected the API key"
        if "courtlistener" in lower and ("401" in lower or "unauthorized" in lower):
            return "CourtListener needs authentication"
        if "http" in text:
            text = text.split("http", 1)[0].strip(" :-")
        return self._trim(text, 250)

    def _looks_placeholder(self, value):
        text = (value or "").strip().upper()
        if not text:
            return True
        return any(token in text for token in ("PASTE_", "YOUR_", "API_KEY_HERE", "TOKEN_HERE", "REPLACE_"))

    def _new_items(self, items):
        seen = set(self.state.get("seen_ids", []))
        return [item for item in items if item.get("id") not in seen]

    def _remember_items(self, items):
        seen = list(self.state.get("seen_ids", []))
        for item in items:
            item_id = item.get("id")
            if item_id and item_id not in seen:
                seen.append(item_id)
        self.state["seen_ids"] = seen[-500:]
        self.state["updated"] = datetime.now(PT_ZONE).isoformat()
        self._save_state()

    async def _ensure_channel(self, guild):
        existing = self._find_text_channel(guild, self.channel_name)
        if existing is not None:
            return existing
        if not self.create_channel:
            return None
        category = None
        for name in ("market-school", "owner-audit", "morning-brief"):
            channel = self._find_text_channel(guild, name)
            if channel is not None:
                category = channel.category
                break
        try:
            return await guild.create_text_channel(self.channel_name, category=category, reason="MarketOps federal power monitor")
        except discord.Forbidden:
            print(f"⚠️ Cannot create #{self.channel_name}; MarketOps needs Manage Channels permission.")
        except Exception as error:
            print(f"⚠️ Could not create #{self.channel_name}: {error!r}")
        return None

    def _find_text_channel(self, guild, target_name):
        target = self._clean_name(target_name)
        for channel in guild.text_channels:
            current = self._clean_name(channel.name)
            if current == target or current.endswith(target):
                return channel
        return None

    def _branch_color(self, branch):
        if branch == "Legislative":
            return discord.Color.blue()
        if branch == "Executive":
            return discord.Color.gold()
        if branch == "Judicial":
            return discord.Color.purple()
        return discord.Color.blurple()

    def _clean_name(self, value):
        cleaned = (value or "").strip().lower()
        for separator in ("|", "┃", "│"):
            if separator in cleaned:
                cleaned = cleaned.split(separator)[-1].strip()
        while cleaned and not cleaned[0].isalnum():
            cleaned = cleaned[1:].strip()
        return cleaned.replace(" ", "-")

    def _clean_link(self, link):
        return (link or "").replace(" ", "%20").strip()

    def _trim(self, value, limit):
        value = str(value or "")
        if len(value) <= limit:
            return value
        return value[: max(0, limit - 1)] + "…"

    def _timestamp(self):
        return datetime.now(PT_ZONE).strftime("%I:%M %p PT").lstrip("0")

    def _load_state(self):
        try:
            if self.state_file.exists():
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
        except Exception:
            pass
        return {}

    def _save_state(self):
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        except Exception as error:
            print(f"⚠️ Could not save government power state: {error!r}")

    def _env_bool(self, name, default=False):
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}


async def setup(bot):
    await bot.add_cog(GovernmentPowerReadable(bot))