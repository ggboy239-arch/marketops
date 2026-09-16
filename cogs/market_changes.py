import asyncio
import json
import os
from pathlib import Path
from time import monotonic

import discord
from discord.ext import commands, tasks

from market.market_change_engine import MarketChangeEngine


VERSION = "MarketOps Market Change Explainer v1.1.0"


class MarketChanges(commands.Cog):
    """Compact explanation of what changed and what may be driving it."""

    def __init__(self, bot):
        self.bot = bot
        self.engine = MarketChangeEngine()
        self.enabled = self._env_bool("MARKET_CHANGE_EXPLAINER_ENABLED", True)
        self.auto_post = self._env_bool("MARKET_CHANGE_EXPLAINER_AUTO_POST", True)
        self.create_channel = self._env_bool("MARKET_CHANGE_EXPLAINER_CREATE_CHANNEL", True)
        self.channel_name = os.getenv("MARKET_CHANGE_EXPLAINER_CHANNEL", "market-change-explainers").strip()
        self.poll_minutes = float(os.getenv("MARKET_CHANGE_EXPLAINER_POLL_MINUTES", "30"))
        self.state_file = Path("data/market_change_explainer_state.json")
        self.state = self._load_state()
        self.last_check = "Not checked yet"
        self.last_post = "Not posted yet"
        self.last_error = "None"
        self._last_poll = 0.0

        if self.enabled and self.auto_post and not self.market_change_loop.is_running():
            self.market_change_loop.start()

    def cog_unload(self):
        if self.market_change_loop.is_running():
            self.market_change_loop.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        if self.create_channel:
            for guild in self.bot.guilds:
                await self._ensure_channel(guild)

    @commands.command(name="why", aliases=["whymarket", "marketwhy", "marketchange", "changewatch", "explainmarket"])
    async def why_prefix(self, ctx, action="now"):
        action = (action or "now").strip()
        lowered = action.lower()

        if lowered in {"status", "schedule", "settings"}:
            await ctx.send(embed=self._status_embed())
            return
        if lowered in {"help", "commands"}:
            await ctx.send(embed=self._help_embed())
            return
        if lowered in {"post", "send", "test"}:
            await self._post_explainer(ctx)
            return

        focus = None if lowered == "now" else action
        try:
            report = await asyncio.to_thread(self.engine.build_explainer, focus)
            self.last_check = report.get("updated", "Unknown")
            await ctx.send(embed=self._explainer_embed(report), allowed_mentions=discord.AllowedMentions.none())
        except Exception as error:
            self.last_error = repr(error)
            print(f"❌ !why error: {error!r}")
            await ctx.send("⚠️ MarketOps had trouble explaining the market move. Check the terminal for the error.")

    @commands.command(name="whypost", aliases=["marketwhypost", "changepost"])
    async def whypost_prefix(self, ctx):
        await self._post_explainer(ctx)

    @commands.command(name="whystatus", aliases=["marketwhystatus", "changestatus"])
    async def whystatus_prefix(self, ctx):
        await ctx.send(embed=self._status_embed())

    @commands.command(name="whyhelp", aliases=["marketwhyhelp", "changehelp"])
    async def whyhelp_prefix(self, ctx):
        await ctx.send(embed=self._help_embed())

    @tasks.loop(seconds=30)
    async def market_change_loop(self):
        await self.bot.wait_until_ready()
        if not self.enabled or not self.auto_post:
            return
        if monotonic() - self._last_poll < self.poll_minutes * 60:
            return
        self._last_poll = monotonic()

        try:
            report = await asyncio.to_thread(self.engine.build_explainer)
            self.last_check = report.get("updated", "Unknown")
            if not report.get("significant"):
                return

            signature = report.get("signature", "unknown")
            if self.state.get("last_signature") == signature:
                return

            self.state["last_signature"] = signature
            self.state["last_check"] = self.last_check
            self._save_state()

            for guild in self.bot.guilds:
                channel = await self._ensure_channel(guild)
                if channel is None:
                    continue
                await channel.send(embed=self._explainer_embed(report), allowed_mentions=discord.AllowedMentions.none())
                self.last_post = report.get("updated", "Unknown")
        except Exception as error:
            self.last_error = repr(error)
            print(f"❌ Market change explainer loop error: {error!r}")

    async def _post_explainer(self, ctx):
        if ctx.guild is None:
            await ctx.send("⚠️ Run this inside the Discord server.")
            return

        channel = await self._ensure_channel(ctx.guild)
        if channel is None:
            await ctx.send(f"⚠️ I cannot find or create `#{self.channel_name}`.")
            return

        try:
            report = await asyncio.to_thread(self.engine.build_explainer)
            await channel.send(embed=self._explainer_embed(report), allowed_mentions=discord.AllowedMentions.none())
            self.last_post = report.get("updated", "Unknown")
            await ctx.send(f"✅ Posted market-change explainer to #{channel.name}.")
        except Exception as error:
            self.last_error = repr(error)
            print(f"❌ !whypost error: {error!r}")
            await ctx.send("⚠️ MarketOps had trouble posting the market-change explainer. Check the terminal.")

    def _explainer_embed(self, report):
        biggest = self._biggest_move(report)
        biggest_text = biggest.get("line") if biggest else "No clear major move yet."

        embed = discord.Embed(
            title="🧠 Market Move Explained",
            description=(
                f"**Theme:** {report.get('theme', 'Live Market')}\n"
                f"**Risk:** {report.get('risk', 'Unknown')} • **Score:** {report.get('score', 'Unknown')}/100\n"
                f"**Biggest move:** {biggest_text}"
            ),
            color=discord.Color.blurple(),
        )

        changed = [item for item in report.get("changed_assets", []) if item.get("importance") == "major"]
        if not changed:
            changed = report.get("changed_assets", [])[:3]
        move_lines = [f"• {item.get('line', '')}" for item in changed[:4] if item.get("line")]
        embed.add_field(
            name="1️⃣ What changed?",
            value="\n".join(move_lines)[:1024] if move_lines else "No clear market move yet.",
            inline=False,
        )

        drivers = [self._clean_driver(item) for item in report.get("possible_drivers", [])[:3]]
        embed.add_field(
            name="2️⃣ What may be driving it?",
            value="\n".join(f"• {item}" for item in drivers if item)[:1024] or "No clear driver yet.",
            inline=False,
        )

        economics = [self._short(item, 220) for item in report.get("economics", [])[:3]]
        embed.add_field(
            name="3️⃣ Why does that matter?",
            value="\n".join(f"• {item}" for item in economics if item)[:1024] or "Economic path is still unclear.",
            inline=False,
        )

        sectors = report.get("sectors", [])[:4]
        if sectors:
            embed.add_field(name="Affected", value="\n".join(f"• {item}" for item in sectors)[:1024], inline=False)

        confirm = report.get("confirm", [])[:6]
        embed.add_field(
            name="What to check next",
            value="\n".join(f"• {item}" for item in confirm)[:1024] if confirm else "Use `!pulse`, `!news post`, and a chart to confirm.",
            inline=False,
        )

        policy_items = report.get("policy_items", [])
        if policy_items:
            top_policy = policy_items[0]
            embed.add_field(
                name="🏛️ Government angle",
                value=self._short(f"{top_policy.get('branch', 'Policy')}: {top_policy.get('title', 'Untitled')}", 300),
                inline=False,
            )

        embed.add_field(name="Confidence", value=report.get("confidence", "Unknown"), inline=True)
        embed.set_footer(text=f"Checked {report.get('updated', 'Unknown')} • Use !chart to confirm price action • {VERSION}")
        return embed

    def _status_embed(self):
        embed = discord.Embed(
            title="🧠 Market Change Explainer",
            description="Compact mode: explains meaningful market moves without dumping every signal.",
            color=discord.Color.green() if self.enabled else discord.Color.orange(),
        )
        embed.add_field(name="Enabled", value="YES" if self.enabled else "NO", inline=True)
        embed.add_field(name="Auto-post", value="YES" if self.auto_post else "NO", inline=True)
        embed.add_field(name="Channel", value=f"#{self.channel_name}", inline=True)
        embed.add_field(name="Checks", value=f"Every {self.poll_minutes:g} min", inline=True)
        embed.add_field(name="Last check", value=self.last_check, inline=True)
        embed.add_field(name="Last post", value=self.last_post, inline=True)
        embed.add_field(name="Last error", value=self._short_error(self.last_error), inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _help_embed(self):
        embed = discord.Embed(
            title="🧠 Market Change Help",
            description="Use this when the market moves and you want the explanation in plain English.",
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="Commands",
            value=(
                "`!why` — explain the current move\n"
                "`!why post` — post it to the channel\n"
                "`!whystatus` — monitor status\n"
                "`!whyhelp` — this card"
            ),
            inline=False,
        )
        embed.add_field(name="Reading order", value="**What changed → Driver → Why it matters → What to check next**", inline=False)
        embed.add_field(name="Best flow", value="`!pulse` → `!why` → `!news post` → `!power` → `!chart SPY 1d`", inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _biggest_move(self, report):
        rows = report.get("changed_assets", [])
        return rows[0] if rows else None

    def _clean_driver(self, text):
        value = str(text or "")
        if value.lower().startswith("headline lead:"):
            value = value.split(":", 1)[1].strip()
        if value.lower().startswith("federal/policy lead:"):
            value = "Government/policy: " + value.split(":", 1)[1].strip()
        return self._short(value, 260)

    def _short_error(self, error):
        text = str(error or "None")
        if text == "None":
            return "None"
        if "http" in text:
            text = text.split("http", 1)[0].strip(" :-")
        return self._short(text, 250)

    def _short(self, value, limit):
        text = " ".join(str(value or "").split())
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 1)] + "…"

    async def _ensure_channel(self, guild):
        existing = self._find_channel(guild)
        if existing is not None:
            return existing
        if not self.create_channel:
            return None
        category = None
        dashboard = self._find_named_channel(guild, "market-dashboard")
        if dashboard is not None:
            category = dashboard.category
        try:
            return await guild.create_text_channel(
                self.channel_name,
                category=category,
                reason="MarketOps market-change explanation channel",
            )
        except discord.Forbidden:
            print(f"⚠️ Cannot create #{self.channel_name}; MarketOps needs Manage Channels permission.")
        except Exception as error:
            print(f"⚠️ Could not create #{self.channel_name}: {error!r}")
        return None

    def _find_channel(self, guild):
        return self._find_named_channel(guild, self.channel_name)

    def _find_named_channel(self, guild, target_name):
        target = self._clean_name(target_name)
        for channel in guild.text_channels:
            current = self._clean_name(channel.name)
            if current == target or current.endswith(target):
                return channel
        return None

    def _clean_name(self, value):
        cleaned = (value or "").strip().lower()
        for separator in ("|", "┃", "│"):
            if separator in cleaned:
                cleaned = cleaned.split(separator)[-1].strip()
        while cleaned and not cleaned[0].isalnum():
            cleaned = cleaned[1:].strip()
        return cleaned.replace(" ", "-")

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
            print(f"⚠️ Could not save market-change explainer state: {error!r}")

    def _env_bool(self, name, default=False):
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}


async def setup(bot):
    await bot.add_cog(MarketChanges(bot))