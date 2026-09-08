import asyncio
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from market.brief_engine import BriefEngine


VERSION = "MarketOps v2.9.1"
PT_ZONE = ZoneInfo("America/Los_Angeles")


class Brief(commands.Cog):
    """Discord commands and schedule for the MarketOps brief."""

    def __init__(self, bot):
        self.bot = bot
        self.brief_engine = BriefEngine()
        self.auto_post_enabled = self._env_bool("BRIEF_AUTO_POST", default=True)
        self.brief_channel_name = os.getenv("BRIEF_CHANNEL", "morning-brief").strip()
        self.brief_times = self._load_times()
        self.catchup_minutes = int(os.getenv("BRIEF_CATCHUP_MINUTES", "10"))
        self._posted_keys = set()
        self._last_auto_post = "Not posted yet"
        self._last_auto_error = "None"

        if self.auto_post_enabled and not self.scheduled_brief_loop.is_running():
            self.scheduled_brief_loop.start()

    def cog_unload(self):
        if self.scheduled_brief_loop.is_running():
            self.scheduled_brief_loop.cancel()

    @app_commands.command(name="brief", description="View the MarketOps brief.")
    async def brief_slash(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        try:
            brief = await asyncio.to_thread(self.brief_engine.build_brief)
            await interaction.followup.send(embed=self._build_brief_embed(brief))
        except Exception as error:
            print(f"❌ /brief error: {error!r}")
            await interaction.followup.send(
                "⚠️ MarketOps had trouble building the brief. Check the terminal for the error.",
                ephemeral=True,
            )

    @commands.command(name="brief", aliases=["briefnow", "morningbrief"])
    async def brief_prefix(self, ctx, action="now"):
        try:
            action = (action or "now").lower().strip()

            if action in ("schedule", "time", "times", "status"):
                await ctx.send(embed=self._build_schedule_embed())
                return

            if action in ("post", "test", "send"):
                await self._post_brief_to_configured_channel(ctx)
                return

            brief = await asyncio.to_thread(self.brief_engine.build_brief)
            await ctx.send(embed=self._build_brief_embed(brief))
        except Exception as error:
            print(f"❌ !brief error: {error!r}")
            await ctx.send("⚠️ MarketOps had trouble building the brief. Check the terminal for the error.")

    @tasks.loop(seconds=30)
    async def scheduled_brief_loop(self):
        await self.bot.wait_until_ready()

        if not self.auto_post_enabled:
            return

        now = datetime.now(PT_ZONE)
        due_time = self._due_brief_time(now)
        if not due_time:
            return

        post_key = f"{now.strftime('%Y-%m-%d')}-{due_time}"
        if post_key in self._posted_keys:
            return

        self._posted_keys.add(post_key)

        for guild in self.bot.guilds:
            channel = self._find_text_channel(guild, self.brief_channel_name)
            if channel is None:
                message = f"Brief channel #{self.brief_channel_name} not found in {guild.name}."
                self._last_auto_error = message
                print(f"⚠️ {message}")
                continue

            try:
                brief = await asyncio.to_thread(self.brief_engine.build_brief)
                await channel.send(embed=self._build_brief_embed(brief))
                self._last_auto_post = f"{now.strftime('%I:%M %p PT').lstrip('0')} for scheduled {due_time}"
                self._last_auto_error = "None"
                print(f"🌅 Posted scheduled brief to #{channel.name} for scheduled {due_time} PT.")
            except Exception as error:
                self._last_auto_error = repr(error)
                print(f"❌ Scheduled brief error: {error!r}")

    async def _post_brief_to_configured_channel(self, ctx):
        if ctx.guild is None:
            await ctx.send("⚠️ Scheduled channel posting only works inside a Discord server.")
            return
        channel = self._find_text_channel(ctx.guild, self.brief_channel_name)
        if channel is None:
            await ctx.send(f"⚠️ I cannot find `#{self.brief_channel_name}`. Create it or fix `BRIEF_CHANNEL` in `.env`.")
            return
        brief = await asyncio.to_thread(self.brief_engine.build_brief)
        await channel.send(embed=self._build_brief_embed(brief))
        await ctx.send(f"✅ Sent test brief to #{channel.name}.")

    def _build_brief_embed(self, brief):
        dashboard = brief["dashboard"]
        top_items = brief["top_items"]

        embed = discord.Embed(
            title="🌅 MarketOps Brief",
            description="One quick read before you look at charts or headlines.",
            color=self._risk_color(dashboard["score"]),
        )

        embed.add_field(
            name="🧠 Market Mood",
            value=(
                f'**{dashboard["risk"]}**\n'
                f'Score: **{dashboard["score"]}/100**\n'
                f'Confidence: {dashboard["confidence"]}'
            ),
            inline=False,
        )

        embed.add_field(name="Why?", value=self._format_reasons(dashboard.get("reasons", [])), inline=False)

        embed.add_field(
            name="⚡ Fast Market Check",
            value=(
                f'**Leader:** {dashboard["leader"]}\n'
                f'**Weakest:** {dashboard["loser"]}\n'
                f'**Warning:** {dashboard["warning_signal"]}\n'
                f'**Oil/Geo:** {dashboard["energy_signal"]}\n'
                f'**Gold/Safety:** {dashboard.get("gold_signal", "Gold unavailable")}\n'
                f'**Crypto:** {dashboard["crypto_signal"]}'
            ),
            inline=False,
        )

        sections = [
            ("📰 Top Market News", "market", False),
            ("🏦 Fed / Rates", "fed", False),
            ("🛢 Geopolitics / Oil Risk", "geo", False),
            ("🤖 AI / Tech", "ai", False),
            ("₿ Crypto", "crypto", False),
            ("🗞 General News", "general", False),
            ("🧵 Reddit Chatter", "reddit", True),
        ]

        for name, key, reddit in sections:
            embed.add_field(name=name, value=self._format_item(top_items.get(key), reddit=reddit), inline=False)

        embed.add_field(
            name="🎯 What To Watch",
            value="\n".join(f"• {item}" for item in brief.get("watch_list", [])) or "No clear watch list yet.",
            inline=False,
        )
        embed.add_field(
            name="📈 Chart Step",
            value="Use `!pulse` for a fast snapshot, then `!chart SPY 1d`, `!chart QQQ 1d`, `!chart GC=F 5d`, or `!candles`.",
            inline=False,
        )

        embed.set_footer(
            text=(
                f'Updated {brief.get("updated", "Unknown")} PT • '
                f'Providers checked: {brief.get("provider_used", "Unknown")} • {VERSION}'
            )
        )
        return embed

    def _build_schedule_embed(self):
        status = "ON" if self.auto_post_enabled else "OFF"
        times = ", ".join(self.brief_times) if self.brief_times else "No times set"
        now = datetime.now(PT_ZONE).strftime("%I:%M %p PT").lstrip("0")

        embed = discord.Embed(
            title="⏰ MarketOps Brief Schedule",
            description="Brief auto-posting uses Pacific Time and has a catch-up window so it does not miss the minute.",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Auto-post", value=f"**{status}**", inline=True)
        embed.add_field(name="Channel", value=f"`#{self.brief_channel_name}`", inline=True)
        embed.add_field(name="Current PT Time", value=now, inline=True)
        embed.add_field(name="Brief Times PT", value=f"`{times}`", inline=False)
        embed.add_field(name="Catch-up Window", value=f"Posts if the bot checks within **{self.catchup_minutes} minute(s)** after the scheduled time.", inline=False)
        embed.add_field(name="Last Auto Post", value=self._last_auto_post, inline=True)
        embed.add_field(name="Last Auto Error", value=self._last_auto_error, inline=True)
        embed.add_field(
            name="Test It",
            value="Use `!brief post` in `#morning-brief` to force-send one brief into the configured brief channel.",
            inline=False,
        )
        embed.add_field(
            name="Recommended Times",
            value="`05:30` pre-market setup\n`09:30` mid-morning check\n`13:15` after-close recap",
            inline=False,
        )
        embed.set_footer(text=VERSION)
        return embed

    def _format_item(self, item, reddit=False):
        if item is None:
            return "No fresh item found."

        title = discord.utils.escape_markdown(item.get("title", "Untitled"))
        source = item.get("source", "Unknown")
        age = item.get("age_label", "Unknown")
        route = item.get("channel", "unknown")
        link = self._clean_link(item.get("link", ""))

        warning = "⚠️ Reddit chatter only — verify first.\n" if reddit else ""
        open_line = f"\n🔗 [Open item](<{link}>)" if link else ""

        return (
            f"{warning}**{title}**\n"
            f"Source: {source} • Age: {age} • Route: `#{route}`"
            f"{open_line}"
        )

    def _due_brief_time(self, now):
        for scheduled in self.brief_times:
            try:
                hour, minute = [int(part) for part in scheduled.split(":", 1)]
            except Exception:
                continue
            scheduled_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if scheduled_time <= now <= scheduled_time + timedelta(minutes=self.catchup_minutes):
                return scheduled
        return None

    def _find_text_channel(self, guild, target_name):
        target = self._clean_channel_name(target_name)
        for channel in guild.text_channels:
            if self._clean_channel_name(channel.name).endswith(target):
                return channel
        return None

    def _clean_channel_name(self, channel_name):
        cleaned = (channel_name or "").strip().lower()
        for separator in ("|", "┃", "│"):
            if separator in cleaned:
                cleaned = cleaned.split(separator)[-1].strip()
        while cleaned and not cleaned[0].isalnum():
            cleaned = cleaned[1:].strip()
        return cleaned.replace(" ", "-")

    def _clean_link(self, link):
        return (link or "").replace(" ", "%20").strip()

    def _format_reasons(self, reasons):
        if not reasons:
            return "No clear reason yet."
        return "\n".join(f"• {reason}" for reason in reasons[:5])

    def _risk_color(self, score):
        if score >= 60:
            return discord.Color.green()
        if score <= 30:
            return discord.Color.red()
        if score <= 45:
            return discord.Color.orange()
        return discord.Color.gold()

    def _load_times(self):
        raw = os.getenv("BRIEF_TIMES_PT") or os.getenv("BRIEF_TIME_PT") or "05:30"
        times = []

        for item in raw.split(","):
            cleaned = item.strip()
            if self._valid_time(cleaned):
                times.append(cleaned)

        return times or ["05:30"]

    def _valid_time(self, value):
        try:
            datetime.strptime(value, "%H:%M")
            return True
        except Exception:
            return False

    def _env_bool(self, name, default=False):
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in ("1", "true", "yes", "y", "on")


async def setup(bot):
    await bot.add_cog(Brief(bot))