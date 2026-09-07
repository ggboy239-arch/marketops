import asyncio
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from market.brief_engine import BriefEngine


VERSION = "MarketOps v2.4.1"
PT_ZONE = ZoneInfo("America/Los_Angeles")


class Brief(commands.Cog):
    """Discord commands and schedule for the MarketOps brief."""

    def __init__(self, bot):
        self.bot = bot
        self.brief_engine = BriefEngine()
        self.auto_post_enabled = self._env_bool("BRIEF_AUTO_POST", default=False)
        self.brief_channel_name = os.getenv("BRIEF_CHANNEL", "morning-brief").strip()
        self.brief_times = self._load_times()
        self._posted_keys = set()

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
            print(f"❌ /brief error: {error}")
            await interaction.followup.send(
                "⚠️ MarketOps had trouble building the brief. Check the terminal for the error.",
                ephemeral=True,
            )

    @commands.command(name="brief")
    async def brief_prefix(self, ctx, action="now"):
        try:
            action = (action or "now").lower().strip()

            if action in ("schedule", "time", "times", "status"):
                await ctx.send(embed=self._build_schedule_embed())
                return

            brief = await asyncio.to_thread(self.brief_engine.build_brief)
            await ctx.send(embed=self._build_brief_embed(brief))
        except Exception as error:
            print(f"❌ !brief error: {error}")
            await ctx.send("⚠️ MarketOps had trouble building the brief. Check the terminal for the error.")

    @tasks.loop(seconds=30)
    async def scheduled_brief_loop(self):
        await self.bot.wait_until_ready()

        now = datetime.now(PT_ZONE)
        current_time = now.strftime("%H:%M")
        current_date = now.strftime("%Y-%m-%d")

        if current_time not in self.brief_times:
            return

        post_key = f"{current_date}-{current_time}"
        if post_key in self._posted_keys:
            return

        self._posted_keys.add(post_key)

        for guild in self.bot.guilds:
            channel = discord.utils.get(guild.text_channels, name=self.brief_channel_name)
            if channel is None:
                print(f"⚠️ Brief channel #{self.brief_channel_name} not found in {guild.name}.")
                continue

            try:
                brief = await asyncio.to_thread(self.brief_engine.build_brief)
                await channel.send(embed=self._build_brief_embed(brief))
                print(f"🌅 Posted scheduled brief to #{self.brief_channel_name} at {current_time} PT.")
            except Exception as error:
                print(f"❌ Scheduled brief error: {error}")

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
            value="\n".join(f"• {item}" for item in brief.get("watch_list", [])),
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
            description="Brief auto-posting uses Pacific Time automatically.",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Auto-post", value=f"**{status}**", inline=True)
        embed.add_field(name="Channel", value=f"`#{self.brief_channel_name}`", inline=True)
        embed.add_field(name="Current PT Time", value=now, inline=True)
        embed.add_field(name="Brief Times PT", value=f"`{times}`", inline=False)
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
