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

VERSION = "MarketOps Federal Power v1.0.0"
PT_ZONE = ZoneInfo("America/Los_Angeles")


class GovernmentPower(commands.Cog):
    """Three-branch government monitor for economy/market learning."""

    def __init__(self, bot):
        self.bot = bot
        self.engine = GovernmentPowerEngine()
        self.enabled = self._env_bool("GOV_POWER_ENABLED", True)
        self.channel_name = os.getenv("GOV_POWER_CHANNEL", "federal-power-briefs").strip()
        self.create_channel = self._env_bool("GOV_POWER_CREATE_CHANNEL", True)
        self.poll_minutes = float(os.getenv("GOV_POWER_POLL_MINUTES", "180"))
        self.max_auto_posts = int(os.getenv("GOV_POWER_MAX_AUTO_POSTS", "3"))
        self.state_file = Path("data/government_power_state.json")
        self.state = self._load_state()
        self.last_check = "Not checked yet"
        self.last_post = "Not posted yet"
        self.last_error = "None"
        self._last_poll = 0.0
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
        try:
            report = await asyncio.to_thread(self.engine.build_report)
            self.last_check = report.get("updated", "Unknown")
            items = report.get("items", [])
            if not items:
                await ctx.send(embed=self._empty_embed(report))
                return
            await ctx.send(embed=self._summary_embed(report))
            for item in items[:5]:
                await ctx.send(embed=self._lesson_embed(item), allowed_mentions=discord.AllowedMentions.none())
        except Exception as error:
            self.last_error = repr(error)
            print(f"❌ !power error: {error!r}")
            await ctx.send("⚠️ MarketOps had trouble building the federal power brief. Check the terminal for the error.")

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
            new_items = self._new_items(report.get("items", []))[: self.max_auto_posts]
            if not new_items:
                return
            for guild in self.bot.guilds:
                channel = await self._ensure_channel(guild)
                if channel is None:
                    continue
                await channel.send(embed=self._summary_embed({**report, "items": new_items}), allowed_mentions=discord.AllowedMentions.none())
                for item in new_items:
                    await channel.send(embed=self._lesson_embed(item), allowed_mentions=discord.AllowedMentions.none())
            self._remember_items(new_items)
            self.last_post = datetime.now(PT_ZONE).strftime("%I:%M %p PT").lstrip("0")
            self.last_error = "None"
        except Exception as error:
            self.last_error = repr(error)
            print(f"❌ Government power loop error: {error!r}")

    async def _post_report(self, ctx):
        try:
            if ctx.guild is None:
                await ctx.send("⚠️ Run this inside the Discord server.")
                return
            channel = await self._ensure_channel(ctx.guild)
            if channel is None:
                await ctx.send(f"⚠️ I cannot find or create `#{self.channel_name}`. Create it or give MarketOps Manage Channels.")
                return
            report = await asyncio.to_thread(self.engine.build_report)
            self.last_check = report.get("updated", "Unknown")
            items = report.get("items", [])
            if not items:
                await channel.send(embed=self._empty_embed(report), allowed_mentions=discord.AllowedMentions.none())
                await ctx.send(f"✅ Checked government sources. No matching high-impact item found for #{channel.name}.")
                return
            await channel.send(embed=self._summary_embed(report), allowed_mentions=discord.AllowedMentions.none())
            for item in items[:5]:
                await channel.send(embed=self._lesson_embed(item), allowed_mentions=discord.AllowedMentions.none())
            self._remember_items(items[:5])
            self.last_post = datetime.now(PT_ZONE).strftime("%I:%M %p PT").lstrip("0")
            await ctx.send(f"✅ Posted {min(len(items), 5)} federal power brief(s) to #{channel.name}.")
        except Exception as error:
            self.last_error = repr(error)
            print(f"❌ !power post error: {error!r}")
            await ctx.send("⚠️ MarketOps had trouble posting federal power briefs. Check the terminal for the error.")

    def _lesson_embed(self, item):
        branch_emoji = {"Legislative": "🏛", "Executive": "⚙️", "Judicial": "⚖️"}.get(item.get("branch"), "🏛")
        title = self._trim(item.get("title", "Untitled"), 240)
        embed = discord.Embed(title=f"{branch_emoji} Federal Power Shift Brief", description=f"**{title}**", color=self._branch_color(item.get("branch")))
        source_line = f'{item.get("branch", "Unknown")} • {item.get("source", "Unknown")} • {item.get("date", "Unknown date")} • Score {item.get("score", 0)}'
        embed.add_field(name="Source Event", value=self._trim(source_line, 1024), inline=False)
        embed.add_field(name="1️⃣ Identify", value=self._trim(item.get("identify", "Identify what changed."), 1024), inline=False)
        embed.add_field(name="2️⃣ Translate Economics", value=self._trim(item.get("translate", "Translate who pays more, who benefits, and what changes."), 1024), inline=False)
        confirm = ", ".join(item.get("confirm", [])) or "SPY, QQQ, VIX, affected sector"
        embed.add_field(name="3️⃣ Confirm Market Reaction", value=f"Watch: **{confirm}**\nUse `!pulse`, `!watchtest`, and `!chart SYMBOL 1d`.", inline=False)
        compact_payload = json.dumps(item.get("payload", {}), ensure_ascii=False, separators=(",", ":"))
        embed.add_field(name="ChatGPT JSON Payload", value=f"```json\n{self._trim(compact_payload, 900)}\n```", inline=False)
        link = item.get("link")
        if link:
            embed.add_field(name="Official / Public Link", value=f"[Open source](<{self._clean_link(link)}>)", inline=False)
        embed.set_footer(text=f"Public government info only • Verify before acting • {VERSION}")
        return embed

    def _summary_embed(self, report):
        counts = report.get("counts", {})
        embed = discord.Embed(title="🏛 Three-Branch Power Monitor", description="Congress.gov + Federal Register + CourtListener → economy lesson briefs.", color=discord.Color.blurple())
        embed.add_field(name="Found", value=f"Legislative: **{counts.get('Legislative', 0)}**\nExecutive: **{counts.get('Executive', 0)}**\nJudicial: **{counts.get('Judicial', 0)}**", inline=True)
        embed.add_field(name="Lookback", value=f"Last **{report.get('lookback_days', '?')} day(s)**", inline=True)
        embed.add_field(name="Minimum Score", value=str(report.get("min_score", "?")), inline=True)
        errors = report.get("errors", [])
        if errors:
            embed.add_field(name="Source Notes", value="\n".join(f"• {error}" for error in errors[:4])[:1024], inline=False)
        embed.add_field(name="Learning Filter", value="Identify branch/action → Translate revenue/cost/demand/supply/margins/risk → Confirm with market reaction.", inline=False)
        embed.set_footer(text=f'Checked {report.get("updated", "Unknown")} • {VERSION}')
        return embed

    def _empty_embed(self, report):
        embed = discord.Embed(title="🏛 Three-Branch Power Monitor", description="No new high-impact government item matched the filter in the current lookback window.", color=discord.Color.gold())
        errors = report.get("errors", [])
        if errors:
            embed.add_field(name="Source Notes", value="\n".join(f"• {error}" for error in errors[:6])[:1024], inline=False)
        embed.add_field(name="Next Step", value="Use `!power status`, add API keys, or widen `GOV_POWER_LOOKBACK_DAYS`.", inline=False)
        embed.set_footer(text=f'Checked {report.get("updated", "Unknown")} • {VERSION}')
        return embed

    def _status_embed(self):
        status = self.engine.status()
        embed = discord.Embed(title="⚙️ Federal Power Monitor Status", description="Tracks laws, rules, executive actions, and court rulings that may affect the economy.", color=discord.Color.green() if self.enabled else discord.Color.orange())
        embed.add_field(name="Auto Monitor", value="ON" if self.enabled else "OFF", inline=True)
        embed.add_field(name="Channel", value=f"#{self.channel_name}", inline=True)
        embed.add_field(name="Poll", value=f"Every {self.poll_minutes:g} minute(s)", inline=True)
        embed.add_field(name="Congress.gov", value="Ready" if status.get("congress_ready") else "Needs CONGRESS_API_KEY", inline=True)
        embed.add_field(name="Federal Register", value="ON" if status.get("federal_register_enabled") else "OFF", inline=True)
        embed.add_field(name="CourtListener", value="ON" if status.get("courtlistener_enabled") else "OFF", inline=True)
        embed.add_field(name="CourtListener Token", value="Added" if status.get("courtlistener_token") else "Optional / not added", inline=True)
        embed.add_field(name="Last Check", value=self.last_check, inline=True)
        embed.add_field(name="Last Post", value=self.last_post, inline=True)
        embed.add_field(name="Last Error", value=self.last_error[:900], inline=False)
        embed.add_field(name="Test", value="Use `!power post` to force-post into the configured channel.", inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _help_embed(self):
        embed = discord.Embed(title="🏛 Federal Power Monitor Help", description="Learn how government power shifts move markets.", color=discord.Color.blurple())
        embed.add_field(name="Commands", value="`!power` — show current federal power briefs\n`!power post` — post current briefs to the configured channel\n`!power status` — show source/API status\n`!powerhelp` — show this help card", inline=False)
        embed.add_field(name="Sources", value="Congress.gov API, Federal Register API, and CourtListener API.", inline=False)
        embed.add_field(name="Framework", value="Document → Identify → Translate economics → Confirm with chart/sector reaction.", inline=False)
        embed.set_footer(text=VERSION)
        return embed

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
            return await guild.create_text_channel(self.channel_name, category=category, reason="MarketOps federal power shift monitor")
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
    await bot.add_cog(GovernmentPower(bot))
